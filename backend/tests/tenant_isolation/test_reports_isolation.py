import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.application.report import generate_report
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks

# Real "now," not a fixed past date: the list/detail routes filter on
# real wall-clock expiry (`datetime.now(timezone.utc)`), so a report
# generated against a stale fixed `now` would already read as expired by
# the time this test runs. The exact period this resolves to doesn't
# matter for these tests — only whether the report is visible/isolated.
_NOW = datetime.now(timezone.utc)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "reports_isolation_test.db"
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
    test_client._SessionLocal = TestSessionLocal  # stashed so tests can seed a report directly
    yield test_client
    app.dependency_overrides.clear()


def _create_business(client, headers, name):
    return client.post("/businesses", json={"name": name}, headers=headers).json()


def test_reports_list_is_tenant_scoped(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    business_b = _create_business(client, headers_b, "Shop B")

    db = client._SessionLocal()
    generate_report(db, business_id=uuid.UUID(business_a["id"]), report_type="weekly", now=_NOW)
    db.close()

    response_a = client.get(f"/businesses/{business_a['id']}/reports", headers=headers_a)
    response_b = client.get(f"/businesses/{business_b['id']}/reports", headers=headers_b)

    assert response_a.status_code == 200
    assert len(response_a.json()) == 1
    assert response_b.status_code == 200
    assert response_b.json() == []  # business B sees none of business A's reports


def test_cannot_fetch_another_business_s_report_by_id(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    _create_business(client, headers_b, "Shop B")

    db = client._SessionLocal()
    report = generate_report(db, business_id=uuid.UUID(business_a["id"]), report_type="weekly", now=_NOW)
    report_id = str(report.id)
    db.close()

    # Business A can fetch its own report.
    own_response = client.get(f"/businesses/{business_a['id']}/reports/{report_id}", headers=headers_a)
    assert own_response.status_code == 200

    # Business B cannot fetch it even by guessing/reusing the ID, scoped
    # under its own business_id in the URL. A third user/business, not a
    # second one for user B — one shop per account now, see
    # test_business_isolation.py's own test of that limit.
    headers_c = bearer_header("user-c", "c@example.com")
    cross_business = _create_business(client, headers_c, "Shop C")
    cross_response = client.get(f"/businesses/{cross_business['id']}/reports/{report_id}", headers=headers_c)
    assert cross_response.status_code == 404


# --- Report downloads (PDF/DOCX) -------------------------------------------


def test_owner_can_download_pdf_and_docx(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")

    db = client._SessionLocal()
    report = generate_report(db, business_id=uuid.UUID(business["id"]), report_type="weekly", now=_NOW)
    report_id = str(report.id)
    db.close()

    pdf_response = client.get(f"/businesses/{business['id']}/reports/{report_id}/download.pdf", headers=headers)
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    assert pdf_response.content[:4] == b"%PDF"
    assert "attachment" in pdf_response.headers["content-disposition"]

    docx_response = client.get(f"/businesses/{business['id']}/reports/{report_id}/download.docx", headers=headers)
    assert docx_response.status_code == 200
    assert docx_response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx_response.content[:2] == b"PK"  # a .docx is a zip archive
    assert "attachment" in docx_response.headers["content-disposition"]


def test_download_filename_is_safe_and_identifiable(client):
    headers = bearer_header("user-a", "a@example.com")
    # A name with characters that must never reach a Content-Disposition
    # header unescaped (quotes, path separators) — the safe-filename
    # helper must strip these, not just hope none ever appear.
    business = _create_business(client, headers, 'Shop "A"/../evil')

    db = client._SessionLocal()
    report = generate_report(db, business_id=uuid.UUID(business["id"]), report_type="weekly", now=_NOW)
    report_id = str(report.id)
    db.close()

    response = client.get(f"/businesses/{business['id']}/reports/{report_id}/download.pdf", headers=headers)
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    filename = disposition.split("filename=", 1)[1].strip('"')
    # The unsafe characters from the business name above are all gone —
    # neither a header-injection risk nor a path-traversal-shaped string
    # ever reaches the response.
    assert '"' not in filename
    assert ".." not in filename
    assert "/" not in filename
    assert "weekly" in filename
    assert filename.endswith(".pdf")


def test_cannot_download_another_business_s_report(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    _create_business(client, headers_b, "Shop B")

    db = client._SessionLocal()
    report = generate_report(db, business_id=uuid.UUID(business_a["id"]), report_type="weekly", now=_NOW)
    report_id = str(report.id)
    db.close()

    headers_c = bearer_header("user-c", "c@example.com")
    cross_business = _create_business(client, headers_c, "Shop C")
    cross_pdf = client.get(f"/businesses/{cross_business['id']}/reports/{report_id}/download.pdf", headers=headers_c)
    assert cross_pdf.status_code == 404
    cross_docx = client.get(f"/businesses/{cross_business['id']}/reports/{report_id}/download.docx", headers=headers_c)
    assert cross_docx.status_code == 404


def test_cannot_download_a_nonexistent_report(client):
    headers = bearer_header("user-a", "a@example.com")
    business = _create_business(client, headers, "Shop A")

    response = client.get(
        f"/businesses/{business['id']}/reports/{uuid.uuid4()}/download.pdf", headers=headers
    )
    assert response.status_code == 404


def test_download_requires_real_membership_not_just_a_hidden_button(client):
    """The prompt's own explicit requirement: permission must be enforced
    server-side, never only a frontend button being hidden. A stranger
    with no Membership on the business at all gets 403 before the report
    lookup even runs."""
    headers_owner = bearer_header("user-a", "a@example.com")
    headers_stranger = bearer_header("user-stranger", "stranger@example.com")
    business = _create_business(client, headers_owner, "Shop A")

    db = client._SessionLocal()
    report = generate_report(db, business_id=uuid.UUID(business["id"]), report_type="weekly", now=_NOW)
    report_id = str(report.id)
    db.close()

    response = client.get(f"/businesses/{business['id']}/reports/{report_id}/download.pdf", headers=headers_stranger)
    assert response.status_code == 403
