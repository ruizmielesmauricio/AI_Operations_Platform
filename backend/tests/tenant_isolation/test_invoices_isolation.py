"""Cross-business tenant isolation for app/api/invoices.py — every route
is scoped by the URL's business_id + get_current_membership (PR-6.1/6.2),
same as every other tenant-scoped router; these tests prove business B's
membership can never read, correct, confirm, undo, discard, or download
the original PDF for a draft that belongs to business A, and that a
duplicate check never reaches across businesses.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.imports import r2_client
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks, seed_active_subscription
from tests.invoice_pdf_helpers import build_invoice_pdf


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    store: dict[str, bytes] = {}
    monkeypatch.setattr(r2_client, "put_object_bytes", lambda *, storage_key, data, content_type: store.__setitem__(storage_key, data))
    monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: store[storage_key])
    monkeypatch.setattr(r2_client, "delete_object", lambda *, storage_key: store.pop(storage_key, None))

    db_path = tmp_path / "invoices_isolation_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    test_client._engine = engine
    yield test_client
    app.dependency_overrides.clear()


def _create_business(client, headers, name):
    business = client.post("/businesses", json={"name": name}, headers=headers).json()
    seed_active_subscription(client._engine, business["id"])
    return business


def _upload(client, headers, business_id, **kwargs):
    return client.post(
        f"/businesses/{business_id}/invoices",
        files={"file": ("invoice.pdf", build_invoice_pdf(**kwargs), "application/pdf")},
        headers=headers,
    ).json()


@pytest.fixture()
def two_businesses_and_an_invoice(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")
    invoice = _upload(client, headers_a, business_a["id"])
    return headers_a, headers_b, business_a, business_b, invoice


def test_get_via_the_wrong_business_id_404s_not_403s_or_200s(client, two_businesses_and_an_invoice):
    # A genuine member of business_b (not a permissions failure -- b is
    # real membership, just the wrong business) must still never see a's
    # invoice by guessing its id under b's own URL.
    _, headers_b, _, business_b, invoice = two_businesses_and_an_invoice

    response = client.get(f"/businesses/{business_b['id']}/invoices/{invoice['id']}", headers=headers_b)

    assert response.status_code == 404


def test_list_never_includes_another_businesss_drafts(client, two_businesses_and_an_invoice):
    headers_a, headers_b, business_a, business_b, invoice = two_businesses_and_an_invoice
    _upload(client, headers_b, business_b["id"])

    response = client.get(f"/businesses/{business_a['id']}/invoices", headers=headers_a)

    ids = {inv["id"] for inv in response.json()}
    assert invoice["id"] in ids
    assert len(ids) == 1


def test_header_patch_via_the_wrong_business_id_is_blocked(client, two_businesses_and_an_invoice):
    _, headers_b, _, business_b, invoice = two_businesses_and_an_invoice

    response = client.patch(
        f"/businesses/{business_b['id']}/invoices/{invoice['id']}",
        json={"invoice_reference": "hijacked"},
        headers=headers_b,
    )

    assert response.status_code == 404


def test_line_patch_via_the_wrong_business_id_is_blocked(client, two_businesses_and_an_invoice):
    _, headers_b, _, business_b, invoice = two_businesses_and_an_invoice
    line_id = invoice["lines"][0]["id"]

    response = client.patch(
        f"/businesses/{business_b['id']}/invoices/{invoice['id']}/lines/{line_id}",
        json={"resolution_action": "excluded"},
        headers=headers_b,
    )

    assert response.status_code == 404


def test_confirm_via_the_wrong_business_id_is_blocked(client, two_businesses_and_an_invoice):
    _, headers_b, _, business_b, invoice = two_businesses_and_an_invoice

    response = client.post(f"/businesses/{business_b['id']}/invoices/{invoice['id']}/confirm", headers=headers_b)

    assert response.status_code == 404


def test_undo_via_the_wrong_business_id_is_blocked(client, two_businesses_and_an_invoice):
    _, headers_b, _, business_b, invoice = two_businesses_and_an_invoice

    response = client.post(f"/businesses/{business_b['id']}/invoices/{invoice['id']}/undo", headers=headers_b)

    assert response.status_code == 404


def test_discard_via_the_wrong_business_id_is_blocked(client, two_businesses_and_an_invoice):
    _, headers_b, _, business_b, invoice = two_businesses_and_an_invoice

    response = client.delete(f"/businesses/{business_b['id']}/invoices/{invoice['id']}", headers=headers_b)

    assert response.status_code == 404


def test_pdf_download_via_the_wrong_business_id_is_blocked_never_public(client, two_businesses_and_an_invoice):
    # Deliberately distinct from the company-logo route (public, no
    # membership dependency at all) -- an invoice is real commercial
    # data, always tenant-scoped (spec §5.3).
    _, headers_b, _, business_b, invoice = two_businesses_and_an_invoice

    response = client.get(f"/businesses/{business_b['id']}/invoices/{invoice['id']}/pdf", headers=headers_b)

    assert response.status_code == 404


def test_a_non_member_of_either_business_is_rejected_outright(client, two_businesses_and_an_invoice):
    headers_a, _, business_a, _, invoice = two_businesses_and_an_invoice
    headers_c = bearer_header("user-c", "c@example.com")

    response = client.get(f"/businesses/{business_a['id']}/invoices/{invoice['id']}", headers=headers_c)

    assert response.status_code == 403


def test_duplicate_detection_never_matches_across_businesses(client):
    # Two different businesses uploading byte-identical invoice PDFs
    # (e.g. the same accounting-software template) must never see each
    # other's upload as a duplicate -- every duplicate signal is
    # business_id-scoped by construction (app/invoices/duplicates.py).
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    invoice_a = _upload(client, headers_a, business_a["id"])
    invoice_b = _upload(client, headers_b, business_b["id"])  # identical default fixture bytes

    assert invoice_a["duplicate_status"] == "none"
    assert invoice_b["duplicate_status"] == "none"
