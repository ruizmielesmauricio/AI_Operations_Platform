"""Auth and roles — AC-051..AC-055 (criteria §7)."""

import re
import time
import uuid

from cryptography.hazmat.primitives.asymmetric import ec

from conftest import BACKEND, REPO_ROOT, auth, make_token


def test_jwt_verification(orla):
    """AC-051: only correctly signed, unexpired, audience-'authenticated'
    Supabase tokens are accepted."""
    orla.create_business("jwt-user")
    other_key = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    cases = {
        "valid": (make_token("jwt-user"), 200),
        "expired": (make_token("jwt-user", exp=now - 60, iat=now - 3600), 401),
        "wrong audience": (make_token("jwt-user", aud="anon"), 401),
        "foreign signing key": (make_token("jwt-user", private_key=other_key), 401),
        "garbage": ("not.a.jwt", 401),
    }
    import jwt as pyjwt

    cases["alg none"] = (pyjwt.encode({"sub": "jwt-user", "aud": "authenticated", "iat": now, "exp": now + 600},
                                      key=None, algorithm="none"), 401)
    for name, (token, expected) in cases.items():
        r = orla.client.get("/businesses", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == expected, f"{name}: expected {expected}, got {r.status_code}"


def test_signup_creates_owner_membership(orla):
    """AC-052: signup requires a business type; the result is user + business
    of that type + owner membership. Contract: GET /business-templates lists
    the selectable types as [{"key", "label"}] for the signup form."""
    h = auth("new-owner")
    templates = orla.client.get("/business-templates", headers=h)
    assert templates.status_code == 200, "no endpoint listing business types for signup"
    keys = {t["key"] for t in templates.json()}
    assert {"bicycle_shop", "coffee_shop"} <= keys
    assert all(t["label"].strip() for t in templates.json())

    missing = orla.client.post("/businesses", json={"name": "No Type"}, headers=h)
    assert missing.status_code == 422, "a business was created without choosing a type"
    created = orla.client.post("/businesses", json={"name": "Typed Shop", "template": "coffee_shop"}, headers=h)
    assert created.status_code == 201
    body = created.json()
    assert body["template"] == "coffee_shop" and body["role"] == "owner"

    from app.models.membership import Membership
    from app.models.user import User

    with orla.session() as s:
        assert s.get(User, "new-owner") is not None
        m = s.query(Membership).filter(Membership.business_id == uuid.UUID(body["id"])).one()
        assert (m.user_id, m.role) == ("new-owner", "owner")


def test_role_permissions_server_side(orla, monkeypatch):
    """AC-053: staff calling owner/manager actions directly get 403."""
    from app.billing import client as billing_client

    monkeypatch.setattr(billing_client, "create_checkout_session",
                        lambda **k: type("S", (), {"url": "https://checkout.stripe.com/c/pay/cs_test_x"})())
    biz = orla.create_business("perm-owner")
    orla.add_member(biz["id"], "perm-staff", "staff")
    bid = biz["id"]
    calls = [
        ("PATCH", f"/businesses/{bid}", {"name": "Hijacked"}),
        ("DELETE", f"/businesses/{bid}", None),
        ("POST", f"/businesses/{bid}/billing/checkout-session", None),
        ("POST", f"/businesses/{bid}/billing/portal-session", None),
        ("POST", f"/businesses/{bid}/employee-seats",
         {"first_name": "Eve", "surname": "X", "email": "eve@example.com", "role": "manager"}),
        ("POST", f"/businesses/{bid}/suppliers", {"name": "Staff Supplier"}),
        ("POST", f"/businesses/{bid}/branches", {"name": "Staff Branch", "template": "bicycle_shop"}),
        ("GET", f"/businesses/{bid}/audit-logs", None),
    ]
    product_cat = orla.client.get(f"/businesses/{bid}/product-categories", headers=auth("perm-owner"))
    allowed = []
    for method, url, body in calls:
        r = orla.client.request(method, url, json=body, headers=auth("perm-staff"))
        if r.status_code != 403:
            allowed.append(f"{method} {url} -> {r.status_code}")
    assert not allowed, "staff could perform owner/manager actions:\n" + "\n".join(allowed)
    assert product_cat.status_code == 200


def test_supabase_auth_only():
    """AC-054: Supabase provides identity only — never the database or storage."""
    problems = []
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text()
        if re.search(r"^\s*(from|import)\s+(supabase|postgrest|storage3|gotrue)\b", text, re.M):
            problems.append(f"{path.relative_to(REPO_ROOT)} imports a Supabase client")
    pyproject = (BACKEND / "pyproject.toml").read_text()
    if re.search(r'"(supabase|postgrest|storage3)[^"]*"', pyproject):
        problems.append("backend depends on a Supabase data/storage client")
    for env in [REPO_ROOT / ".env.example", BACKEND / ".env.example"]:
        for line in env.read_text().splitlines():
            if line.startswith("DATABASE_URL") and "supabase" in line:
                problems.append(f"{env.name}: DATABASE_URL points at Supabase")
    from app.settings.config import Settings

    if "supabase" in Settings.model_fields["database_url"].default:
        problems.append("default DATABASE_URL points at Supabase")
    for path in (REPO_ROOT / "frontend").rglob("*.ts*"):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        if re.search(r"supabase\s*\.\s*(from|storage|rpc|channel)\s*\(", text) or ".storage.from(" in text:
            problems.append(f"{path.relative_to(REPO_ROOT)} uses Supabase data/storage APIs")
    assert not problems, "\n".join(problems)


def test_invite_with_role(orla, monkeypatch):
    """AC-055: the owner invites someone as manager; the invite email goes out
    through the email boundary; once their seat is paid and they sign in they
    hold exactly that role."""
    import hashlib
    import hmac
    import json

    from app.billing import client as billing_client
    from app.settings.config import get_settings

    monkeypatch.setattr(billing_client, "create_checkout_session",
                        lambda **k: type("S", (), {"url": "https://checkout.stripe.com/c/pay/cs_test_seat"})())
    secret = "whsec_acceptance_invite"
    monkeypatch.setattr(get_settings(), "stripe_webhook_secret", secret)
    monkeypatch.setattr(get_settings(), "stripe_employee_seat_price_id", "price_seat_placeholder")

    biz = orla.create_business("inv-owner")
    r = orla.client.post(f"/businesses/{biz['id']}/employee-seats",
                         json={"first_name": "Niamh", "surname": "Byrne", "email": "niamh@example.com",
                               "role": "manager"}, headers=auth("inv-owner"))
    assert r.status_code in (200, 201), r.text
    assert [e["to"] for e in orla.email.sent] == ["niamh@example.com"], "invite email not sent via Resend boundary"
    seat_id = r.json()["employee_seat"]["id"]

    def post(event_id, etype, obj):
        payload = json.dumps({"id": event_id, "object": "event", "type": etype, "data": {"object": obj}}).encode()
        ts = int(time.time())
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
        resp = orla.client.post("/billing/webhooks/stripe", content=payload,
                                headers={"stripe-signature": f"t={ts},v1={sig}"})
        assert resp.status_code == 200, resp.text

    meta = {"business_id": biz["id"], "employee_seat_id": seat_id}
    post("evt_seat_cs", "checkout.session.completed", {"customer": "cus_seat", "metadata": meta})
    post("evt_seat_sub", "customer.subscription.updated", {
        "id": "sub_seat", "customer": "cus_seat", "status": "active", "metadata": meta,
        "items": {"data": [{"current_period_end": int(time.time()) + 86400 * 30}]}})

    joined = orla.client.get("/businesses", headers=auth("niamh-user", "niamh@example.com"))
    assert joined.status_code == 200
    mine = [b for b in joined.json() if b["id"] == biz["id"]]
    assert mine and mine[0]["role"] == "manager"
