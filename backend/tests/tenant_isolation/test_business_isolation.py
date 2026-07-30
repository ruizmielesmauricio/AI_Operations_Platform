import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from app.settings.config import get_settings

settings = get_settings()


@pytest.fixture()
def client(tmp_path):
    """A fresh, isolated database per test, wired into the FastAPI app via
    dependency override — proves the real route/dependency wiring, not a
    reimplementation of it.
    """
    db_path = tmp_path / "tenant_isolation_test.db"
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def bearer_header(user_id: str, email: str) -> dict:
    token = jwt.encode(
        {"sub": user_id, "email": email, "aud": "authenticated"},
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_missing_token_is_rejected(client):
    response = client.post("/businesses", json={"name": "No Auth Shop"})
    assert response.status_code == 401


def test_owner_can_create_and_read_their_own_business(client):
    headers = bearer_header("user-a", "a@example.com")
    create_response = client.post("/businesses", json={"name": "Shop A"}, headers=headers)
    assert create_response.status_code == 201
    business_id = create_response.json()["id"]

    get_response = client.get(f"/businesses/{business_id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["role"] == "owner"


def test_cross_tenant_access_is_forbidden(client):
    """The core tenant-isolation guarantee (PR-6.1/6.2, ED-008): business A
    can never read business B's data, even though the browser can put
    business B's real id in the URL.
    """
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")

    business_a = client.post("/businesses", json={"name": "Shop A"}, headers=headers_a).json()
    client.post("/businesses", json={"name": "Shop B"}, headers=headers_b)

    # User B tries to read business A's data using A's real id.
    response = client.get(f"/businesses/{business_a['id']}", headers=headers_b)
    assert response.status_code == 403


def test_listing_businesses_only_returns_the_caller_s_own(client):
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")

    client.post("/businesses", json={"name": "Shop A"}, headers=headers_a)
    client.post("/businesses", json={"name": "Shop B"}, headers=headers_b)
    client.post("/businesses", json={"name": "Shop A2"}, headers=headers_a)

    response = client.get("/businesses", headers=headers_a)
    assert response.status_code == 200
    names = {row["name"] for row in response.json()}
    assert names == {"Shop A", "Shop A2"}
