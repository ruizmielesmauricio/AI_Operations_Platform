import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai import client as ai_client
from app.api.deps import get_db
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks


def _canned_out_of_scope_response(*args, **kwargs):
    return {
        "choices": [{"message": {"content": json.dumps({"intent": "out_of_scope", "period": None, "metric": None})}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.0},
        "model": "test-model",
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    monkeypatch.setattr(ai_client, "chat_completion", _canned_out_of_scope_response)

    db_path = tmp_path / "ai_chat_isolation_test.db"
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
    yield test_client
    app.dependency_overrides.clear()


def _create_business(client, headers, name):
    return client.post("/businesses", json={"name": name}, headers=headers).json()


def test_cannot_chat_against_a_business_you_are_not_a_member_of(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_a = _create_business(client, headers_a, "Shop A")
    _create_business(client, headers_b, "Shop B")

    own_response = client.post(
        f"/businesses/{business_a['id']}/ai/chat", json={"question": "How's my revenue?"}, headers=headers_a
    )
    assert own_response.status_code == 200

    cross_response = client.post(
        f"/businesses/{business_a['id']}/ai/chat", json={"question": "How's my revenue?"}, headers=headers_b
    )
    assert cross_response.status_code == 403
