"""Shared harness for ORLA acceptance tests (acceptance/criteria.md).

PROTECTED: the autobuild loop may not edit anything under tests/acceptance/.
If a test here is wrong, it goes under "Needs Mauricio" — it is never weakened.

What is real and what is faked
------------------------------
Real: the FastAPI app, every route/dependency, the domain/analytics/import/
report code, SQLAlchemy models, JWT verification (ES256, real PyJWT), Stripe
webhook signature verification (real HMAC via the stripe SDK).

Faked ONLY at external network boundaries, never the behaviour under test:
  * Supabase JWKS fetch   -> a local EC key (tokens are still really signed/verified)
  * Cloudflare R2         -> an in-memory object store that records deletes/puts
  * Resend email          -> a recorder (app.email.client.send_email)
  * OpenRouter            -> a scripted fake (app.ai.client.chat_completion)
  * Stripe API calls      -> real test-mode API where a criterion requires it
                             (AC-044/048); otherwise recorded at app.billing.client

Database: a fresh SQLite file per test (never DATABASE_URL), so acceptance
tests can never touch Neon, dev or production data.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Never let a developer .env leak a real database or live key into these tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"


def _load_env_test_local() -> None:
    """Loads repo-root .env.test.local (git-ignored) for the few criteria that
    need real test-mode credentials (Stripe sandbox). Never required for the
    rest of the suite."""
    path = REPO_ROOT / ".env.test.local"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_test_local()

# ---------------------------------------------------------------- JWT ----
_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


class _SigningKey:
    def __init__(self, key):
        self.key = key


class _LocalJWKS:
    def get_signing_key_from_jwt(self, token):
        return _SigningKey(_PUBLIC_KEY)


def make_token(user_id: str, email: str | None = None, *, private_key=None, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email or f"{user_id}@example.com",
        "aud": "authenticated",
        "iat": now,
        "exp": now + 3600,
        "session_id": str(uuid.uuid4()),
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key or _PRIVATE_KEY, algorithm="ES256")


def auth(user_id: str, email: str | None = None) -> dict:
    return {"Authorization": f"Bearer {make_token(user_id, email)}"}


# ------------------------------------------------------------- fakes ----
@dataclass
class FakeR2:
    objects: dict = field(default_factory=dict)
    deleted: list = field(default_factory=list)
    puts: list = field(default_factory=list)


@dataclass
class FakeEmail:
    sent: list = field(default_factory=list)


def canned_ai(content: str, *, model: str = "acceptance-fake-model") -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.0001},
        "model": model,
    }


class FakeAI:
    """Scripted stand-in for OpenRouter. `classify` is the JSON the classify
    call returns; `explain` is the text the explain call returns. Every call's
    messages are recorded so tests can inspect what context the AI was given."""

    def __init__(self):
        self.calls: list[dict] = []
        self.classify: dict = {"intent": "financial_performance", "period": "default_recent", "metric": None}
        self.explain: str = "Here is a summary of how the business is doing."
        self.raise_error: Exception | None = None

    def __call__(self, *, messages, response_format=None, max_tokens=500, temperature=0.2, **kwargs):
        self.calls.append({"messages": messages, "response_format": response_format})
        if self.raise_error is not None:
            raise self.raise_error
        if response_format is not None:
            return canned_ai(json.dumps(self.classify))
        return canned_ai(self.explain)

    def all_text(self) -> str:
        return "\n".join(m.get("content", "") or "" for c in self.calls for m in c["messages"])


# ----------------------------------------------------------- the app ----
class Orla:
    """One isolated ORLA backend: real app + fresh SQLite DB + boundary fakes."""

    def __init__(self, tmp_path: Path, monkeypatch):
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.api.deps import get_db
        from app.main import app
        from app.models import Base
        from app.security import auth as auth_module

        monkeypatch.setattr(auth_module, "_jwks_client", lambda: _LocalJWKS())

        self.monkeypatch = monkeypatch
        self.engine = create_engine(f"sqlite:///{tmp_path / 'acceptance.db'}")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

        def _override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_get_db
        # Code paths that open their own session (scheduler, jobs) must use this DB too.
        import app.models.base as models_base

        monkeypatch.setattr(models_base, "SessionLocal", self.SessionLocal, raising=False)
        self.app = app
        self.client = TestClient(app)

        self.r2 = FakeR2()
        self._install_r2(monkeypatch)
        self.email = FakeEmail()
        self._install_email(monkeypatch)
        self.ai = FakeAI()
        from app.ai import client as ai_client

        monkeypatch.setattr(ai_client, "chat_completion", self.ai)

    # -- boundaries -----------------------------------------------------
    def _install_r2(self, monkeypatch):
        from app.imports import r2_client

        r2 = self.r2
        monkeypatch.setattr(r2_client, "generate_upload_url", lambda *, storage_key: f"https://r2.test/{storage_key}")
        monkeypatch.setattr(r2_client, "get_object_size", lambda *, storage_key: len(r2.objects.get(storage_key, b"")))
        monkeypatch.setattr(r2_client, "download_object", lambda *, storage_key: r2.objects[storage_key])

        def _put(*, storage_key, data, content_type):
            r2.puts.append(storage_key)
            r2.objects[storage_key] = data

        def _delete(*, storage_key):
            r2.deleted.append(storage_key)
            r2.objects.pop(storage_key, None)

        monkeypatch.setattr(r2_client, "put_object_bytes", _put)
        monkeypatch.setattr(r2_client, "delete_object", _delete)

    def _install_email(self, monkeypatch):
        from app.email import client as email_client

        sent = self.email.sent

        def _send(*, to, subject, html, **kwargs):
            sent.append({"to": to, "subject": subject, "html": html})
            return {"id": f"email_{len(sent)}"}

        monkeypatch.setattr(email_client, "send_email", _send)
        from app.settings.config import get_settings

        monkeypatch.setattr(get_settings(), "resend_api_key", "re_acceptance_placeholder", raising=False)
        monkeypatch.setattr(get_settings(), "resend_from_email", "orla@example.com", raising=False)

    # -- helpers --------------------------------------------------------
    def session(self):
        return self.SessionLocal()

    def create_business(self, user: str, name: str | None = None, *, template: str = "bicycle_shop",
                        timezone_name: str = "Europe/Dublin", subscribe: bool = True) -> dict:
        resp = self.client.post(
            "/businesses",
            json={"name": name or f"{user} shop", "template": template, "timezone": timezone_name},
            headers=auth(user),
        )
        assert resp.status_code == 201, f"creating a business failed: {resp.status_code} {resp.text}"
        business = resp.json()
        if subscribe:
            self.seed_subscription(business["id"])
        return business

    def seed_subscription(self, business_id: str, status: str = "active") -> None:
        from app.models.subscription import Subscription

        with self.session() as s:
            s.add(Subscription(
                business_id=uuid.UUID(business_id),
                stripe_customer_id=f"cus_acc_{business_id[:8]}",
                stripe_subscription_id=f"sub_acc_{business_id[:8]}",
                status=status,
            ))
            s.commit()

    def add_member(self, business_id: str, user_id: str, role: str) -> None:
        from app.models.membership import Membership
        from app.models.user import User

        with self.session() as s:
            if s.get(User, user_id) is None:
                s.add(User(id=user_id, email=f"{user_id}@example.com"))
                s.flush()
            s.add(Membership(business_id=uuid.UUID(business_id), user_id=user_id, role=role))
            s.commit()

    def start_upload(self, user: str, business_id: str, filename: str, content: bytes,
                     entity_type: str = "sales") -> str:
        from app.models.upload import Upload

        resp = self.client.post(
            f"/businesses/{business_id}/uploads",
            json={"filename": filename, "entity_type": entity_type},
            headers=auth(user),
        )
        assert resp.status_code == 201, f"requesting an upload failed: {resp.status_code} {resp.text}"
        upload_id = resp.json()["id"]
        with self.session() as s:
            storage_key = s.get(Upload, uuid.UUID(upload_id)).storage_key
        self.r2.objects[storage_key] = content
        done = self.client.post(f"/businesses/{business_id}/uploads/{upload_id}/complete", headers=auth(user))
        assert done.status_code == 200, done.text
        return upload_id

    def detect(self, user: str, business_id: str, upload_id: str) -> dict:
        resp = self.client.post(
            f"/businesses/{business_id}/uploads/{upload_id}/detect-mapping", json={}, headers=auth(user)
        )
        assert resp.status_code == 200, f"detect-mapping failed: {resp.status_code} {resp.text}"
        return resp.json()

    def confirm(self, user: str, business_id: str, upload_id: str, mapping: dict, **extra) -> dict:
        resp = self.client.post(
            f"/businesses/{business_id}/uploads/{upload_id}/confirm-mapping",
            json={"field_mapping": mapping, **extra},
            headers=auth(user),
        )
        assert resp.status_code == 200, f"confirm-mapping failed: {resp.status_code} {resp.text}"
        return resp.json()

    def run_import(self, user: str, business_id: str, upload_id: str) -> dict:
        resp = self.client.post(f"/businesses/{business_id}/uploads/{upload_id}/import", headers=auth(user))
        assert resp.status_code == 200, f"import failed: {resp.status_code} {resp.text}"
        return resp.json()

    def import_file(self, user: str, business_id: str, filename: str, content: bytes,
                    entity_type: str = "sales", mapping: dict | None = None) -> dict:
        """The full user journey: upload -> detect -> confirm (the detected
        mapping, untouched, unless `mapping` is given) -> import."""
        upload_id = self.start_upload(user, business_id, filename, content, entity_type)
        detected = self.detect(user, business_id, upload_id)
        chosen = dict(detected["suggested_mapping"])
        if mapping is not None:
            chosen = {k: None for k in chosen} | mapping
        self.confirm(user, business_id, upload_id, chosen, confirm_multiple_locations=True)
        result = self.run_import(user, business_id, upload_id)
        result["_upload_id"] = upload_id
        result["_detected"] = detected
        return result

    def sales(self, user: str, business_id: str, **params) -> list[dict]:
        rows, offset = [], 0
        while True:
            resp = self.client.get(
                f"/businesses/{business_id}/transactions/sales",
                params={"limit": 100, "offset": offset, **params},
                headers=auth(user),
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            page = body["items"] if isinstance(body, dict) and "items" in body else body
            rows.extend(page)
            if len(page) < 100:
                return rows
            offset += 100


@pytest.fixture()
def orla(tmp_path, monkeypatch):
    instance = Orla(tmp_path, monkeypatch)
    yield instance
    instance.app.dependency_overrides.clear()


# ------------------------------------------------------- file builders ----
def csv_bytes(rows: list[list[object]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def xlsx_bytes(rows: list[list[object]], merge: str | None = None) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    if merge:
        ws.merge_cells(merge)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SALES_HEADER = ["Date", "Product", "SKU", "Qty", "Unit Price", "Cost Price"]


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def recent_weekly_run(tz: str = "Europe/Dublin"):
    """The most recent Monday 08:00 (business-local) that is in the past, as
    UTC, plus the previous completed week's Monday..Sunday dates. Lets tests
    generate reports that are still inside their 7-day availability window."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    now_local = datetime.now(zone)
    monday = now_local.date() - timedelta(days=now_local.weekday())
    run_local = datetime(monday.year, monday.month, monday.day, 8, 0, tzinfo=zone)
    if run_local > now_local:
        monday -= timedelta(days=7)
        run_local = datetime(monday.year, monday.month, monday.day, 8, 0, tzinfo=zone)
    week_start = monday - timedelta(days=7)
    return run_local.astimezone(timezone.utc), [week_start + timedelta(days=i) for i in range(7)]
