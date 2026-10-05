"""Complimentary pilot/tester accounts (Subscription.is_complimentary,
app/cli/pilot_accounts.py): free, fully working access with no Stripe
involvement — and a clean conversion to a paying customer later.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.billing import client as billing_client
from app.cli import pilot_accounts
from app.email import client as email_client
from app.imports import r2_client
from app.main import app
from app.models import Base
from app.models.business import Business
from app.models.subscription import Subscription
from app.repositories.subscription import SubscriptionRepository
from app.settings.config import get_settings
from tests.auth_helpers import bearer_header, patch_jwks, seed_active_subscription

_checkout_calls: list[dict] = []


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    monkeypatch.setenv("STRIPE_EMPLOYEE_SEAT_PRICE_ID", "price_employee_seat")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_main")
    get_settings.cache_clear()
    # Never a real email: the invite path would otherwise call the real
    # Resend API whenever a RESEND_API_KEY is present in the environment.
    monkeypatch.setattr(email_client, "send_email", lambda **kwargs: {"id": "test"})
    monkeypatch.setattr(r2_client, "generate_upload_url", lambda *, storage_key: f"https://r2.test/{storage_key}")
    engine = create_engine(f"sqlite:///{tmp_path / 'complimentary_test.db'}")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    _checkout_calls.clear()

    def fake_checkout(**kwargs):
        _checkout_calls.append(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.com/fake")

    monkeypatch.setattr(billing_client, "create_checkout_session", fake_checkout)
    test_client = TestClient(app)
    test_client._SessionLocal = TestSessionLocal
    test_client._engine = engine
    yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _owner_with_shop(client, user="user-a", email="a@example.com", name="Shop A"):
    headers = bearer_header(user, email)
    return headers, client.post("/businesses", json={"name": name}, headers=headers).json()


def _grant(client, **kwargs):
    with client._SessionLocal() as db:
        return pilot_accounts.grant(db, **kwargs)


def _upload_status(client, headers, business_id):
    return client.post(
        f"/businesses/{business_id}/uploads", json={"filename": "sales.csv", "entity_type": "sales"}, headers=headers
    ).status_code


def test_access_is_blocked_before_and_open_after_a_complimentary_grant(client):
    headers, business = _owner_with_shop(client)
    assert _upload_status(client, headers, business["id"]) == 402

    _grant(client, business_id=uuid.UUID(business["id"]))

    assert _upload_status(client, headers, business["id"]) == 201


def test_the_subscription_endpoint_reports_a_complimentary_account(client):
    headers, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))

    body = client.get(f"/businesses/{business['id']}/billing/subscription", headers=headers).json()

    assert body["status"] == "active" and body["is_complimentary"] is True


def test_a_paying_business_is_not_reported_as_complimentary(client):
    headers, business = _owner_with_shop(client)
    seed_active_subscription(client._engine, business["id"])

    assert client.get(f"/businesses/{business['id']}/billing/subscription", headers=headers).json()["is_complimentary"] is False


def test_there_is_no_billing_portal_for_a_complimentary_account(client):
    headers, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))

    response = client.post(f"/businesses/{business['id']}/billing/portal-session", headers=headers)

    assert response.status_code == 400 and "complimentary" in response.json()["detail"].lower()


def test_subscribing_later_never_sends_the_placeholder_customer_id_to_stripe(client):
    headers, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))

    response = client.post(f"/businesses/{business['id']}/billing/checkout-session", headers=headers)

    assert response.status_code == 200
    assert _checkout_calls[-1]["existing_stripe_customer_id"] is None


def test_a_real_stripe_event_converts_the_account_and_clears_the_flag(client):
    _, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))

    with client._SessionLocal() as db:
        SubscriptionRepository(db).upsert_from_stripe(
            business_id=uuid.UUID(business["id"]), stripe_customer_id="cus_real", stripe_subscription_id="sub_real", status="active"
        )
        db.commit()
        row = db.query(Subscription).filter_by(business_id=uuid.UUID(business["id"])).one()

    assert row.is_complimentary is False
    assert row.stripe_customer_id == "cus_real" and row.status == "active"


def test_revoking_ends_access(client):
    headers, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))
    with client._SessionLocal() as db:
        assert len(pilot_accounts.revoke(db, business_id=uuid.UUID(business["id"]))) == 1

    assert _upload_status(client, headers, business["id"]) == 402


def test_revoking_a_business_that_was_never_complimentary_changes_nothing(client):
    _, business = _owner_with_shop(client)
    seed_active_subscription(client._engine, business["id"])
    with client._SessionLocal() as db:
        assert pilot_accounts.revoke(db, business_id=uuid.UUID(business["id"])) == []
        assert db.query(Subscription).filter_by(business_id=uuid.UUID(business["id"])).one().status == "active"


def test_a_real_paying_subscription_is_never_overwritten_by_a_grant(client):
    _, business = _owner_with_shop(client)
    with client._SessionLocal() as db:
        SubscriptionRepository(db).upsert_from_stripe(
            business_id=uuid.UUID(business["id"]), stripe_customer_id="cus_paying", stripe_subscription_id="sub_paying", status="active"
        )
        db.commit()

    with pytest.raises(pilot_accounts.PilotAccountError, match="real Stripe subscription"):
        _grant(client, business_id=uuid.UUID(business["id"]))


def test_a_cancelled_stripe_subscription_can_be_replaced_by_a_complimentary_one(client):
    headers, business = _owner_with_shop(client)
    with client._SessionLocal() as db:
        SubscriptionRepository(db).upsert_from_stripe(
            business_id=uuid.UUID(business["id"]), stripe_customer_id="cus_old", stripe_subscription_id="sub_old", status="canceled"
        )
        db.commit()

    _grant(client, business_id=uuid.UUID(business["id"]))

    assert _upload_status(client, headers, business["id"]) == 201


def test_grant_by_email_covers_every_shop_the_person_owns_including_branches(client):
    headers, business = _owner_with_shop(client, email="owner@shop.ie")
    seed_active_subscription(client._engine, business["id"])  # branches need an owner-active parent to be created normally
    branch = client.post(f"/businesses/{business['id']}/branches", json={"name": "Branch B"}, headers=headers).json()
    # Fresh owner state: neither shop is complimentary yet.
    with client._SessionLocal() as db:
        db.query(Subscription).delete()
        db.commit()

    granted = _grant(client, email="OWNER@shop.ie")  # case-insensitive

    assert {str(b.id) for b in granted} == {business["id"], branch["id"]}


def test_grant_by_email_explains_when_the_person_has_not_signed_up_or_has_no_shop(client):
    with pytest.raises(pilot_accounts.PilotAccountError, match="sign up first"):
        _grant(client, email="nobody@example.com")

    bearer_header("user-x", "x@example.com")  # token only — the account is created on first request
    client.get("/businesses", headers=bearer_header("user-x", "x@example.com"))
    with pytest.raises(pilot_accounts.PilotAccountError, match="create one first"):
        _grant(client, email="x@example.com")


def test_a_branch_added_under_a_complimentary_shop_is_complimentary_too(client):
    headers, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))

    branch = client.post(f"/businesses/{business['id']}/branches", json={"name": "Branch B"}, headers=headers).json()

    body = client.get(f"/businesses/{branch['id']}/billing/subscription", headers=headers).json()
    assert body["status"] == "active" and body["is_complimentary"] is True


def test_a_branch_under_a_normal_paying_shop_is_not_made_complimentary(client):
    headers, business = _owner_with_shop(client)
    seed_active_subscription(client._engine, business["id"])

    branch = client.post(f"/businesses/{business['id']}/branches", json={"name": "Branch B"}, headers=headers).json()

    assert client.get(f"/businesses/{branch['id']}/billing/subscription", headers=headers).json()["is_complimentary"] is False


def test_staff_can_be_added_to_a_complimentary_shop_with_no_payment_step(client):
    headers, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))

    response = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "bea@example.com", "role": "staff"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["checkout_url"] is None
    assert body["employee_seat"]["status"] == "active"
    assert _checkout_calls == []  # Stripe never involved


def test_an_existing_account_added_as_complimentary_staff_gets_access_immediately(client):
    headers_owner, business = _owner_with_shop(client)
    headers_staff = bearer_header("user-b", "bea@example.com")
    client.get("/businesses", headers=headers_staff)  # Bea already has an account
    _grant(client, business_id=uuid.UUID(business["id"]))

    client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "bea@example.com", "role": "staff"},
        headers=headers_owner,
    )

    assert client.get(f"/businesses/{business['id']}/billing/subscription", headers=headers_staff).status_code == 200


def test_staff_added_before_signing_up_get_access_on_first_login(client):
    headers_owner, business = _owner_with_shop(client)
    _grant(client, business_id=uuid.UUID(business["id"]))
    client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Cal", "surname": "Ryan", "email": "cal@example.com", "role": "manager"},
        headers=headers_owner,
    )

    headers_cal = bearer_header("user-c", "cal@example.com")
    client.get("/businesses", headers=headers_cal)  # first login: the call that syncs the account and links the seat

    assert client.get(f"/businesses/{business['id']}/billing/subscription", headers=headers_cal).status_code == 200


def test_staff_on_a_normal_paying_shop_still_go_through_stripe(client):
    headers, business = _owner_with_shop(client)
    seed_active_subscription(client._engine, business["id"])

    body = client.post(
        f"/businesses/{business['id']}/employee-seats",
        json={"first_name": "Bea", "surname": "O'Brien", "email": "bea@example.com", "role": "staff"},
        headers=headers,
    ).json()

    assert body["employee_seat"]["status"] == "pending_payment"
    assert "checkout.stripe.com" in body["checkout_url"]


def test_list_shows_only_complimentary_accounts(client):
    _, comped = _owner_with_shop(client, name="Comped Shop")
    _, paying = _owner_with_shop(client, user="user-b", email="b@example.com", name="Paying Shop")
    seed_active_subscription(client._engine, paying["id"])
    _grant(client, business_id=uuid.UUID(comped["id"]))

    with client._SessionLocal() as db:
        rows = pilot_accounts.list_complimentary(db)

    assert [b.name for b, _ in rows] == ["Comped Shop"]


def test_the_command_line_entry_point_works_end_to_end(client, monkeypatch, capsys):
    headers, business = _owner_with_shop(client, email="cli@shop.ie")
    monkeypatch.setattr(pilot_accounts, "SessionLocal", client._SessionLocal)

    assert pilot_accounts.main(["grant", "--email", "cli@shop.ie"]) == 0
    assert "Granted complimentary access to: Shop A" in capsys.readouterr().out
    assert _upload_status(client, headers, business["id"]) == 201

    assert pilot_accounts.main(["list"]) == 0
    assert "1 complimentary account(s)" in capsys.readouterr().out

    assert pilot_accounts.main(["grant", "--email", "ghost@shop.ie"]) == 1
    assert "sign up first" in capsys.readouterr().err

    assert pilot_accounts.main(["revoke", "--email", "cli@shop.ie"]) == 0
    assert _upload_status(client, headers, business["id"]) == 402
