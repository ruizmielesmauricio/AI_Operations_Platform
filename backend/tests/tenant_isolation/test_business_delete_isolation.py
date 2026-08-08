import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app
from app.models import Base
from tests.auth_helpers import bearer_header, patch_jwks


@pytest.fixture()
def client(tmp_path, monkeypatch):
    patch_jwks(monkeypatch)
    db_path = tmp_path / "business_delete_isolation_test.db"
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
    test_client._SessionLocal = TestSessionLocal
    yield test_client
    app.dependency_overrides.clear()


def test_owner_can_delete_their_own_shop(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    response = client.delete(f"/businesses/{business['id']}", headers=headers)
    assert response.status_code == 204

    # Gone from the account's listing...
    listing = client.get("/businesses", headers=headers).json()
    assert listing == []
    # ...but a direct fetch by id still 404s the normal way (not a
    # membership error) — deleted, not made inaccessible in some other
    # confusing way.
    get_response = client.get(f"/businesses/{business['id']}", headers=headers)
    assert get_response.status_code == 404


def test_deleting_a_shop_frees_up_the_one_shop_per_account_limit(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.delete(f"/businesses/{business['id']}", headers=headers)

    response = client.post("/businesses", json={"name": "Shop A New"}, headers=headers)
    assert response.status_code == 201


def test_a_non_owner_member_cannot_delete_the_shop(client):
    # The first real enforcement of Membership.ROLES anywhere in this
    # codebase — a manager/staff membership must not be able to delete
    # the business they belong to.
    import uuid

    from app.models.membership import Membership

    headers_owner = bearer_header("user-a", "a@example.com")
    headers_staff = bearer_header("user-b", "b@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers_owner).json()

    session = client._SessionLocal()
    session.add(Membership(business_id=uuid.UUID(business["id"]), user_id="user-b", role="staff"))
    session.commit()
    session.close()

    response = client.delete(f"/businesses/{business['id']}", headers=headers_staff)
    assert response.status_code == 403

    # And it's genuinely still there afterward.
    listing = client.get("/businesses", headers=headers_owner).json()
    assert len(listing) == 1


def test_cross_tenant_cannot_delete_another_business_s_shop(client):
    """The core tenant-isolation guarantee (PR-6.1/6.2, ED-008) extended to
    delete: business A's owner must not be able to delete business B just
    by knowing its id.
    """
    headers_a = bearer_header("user-a", "a@example.com")
    headers_b = bearer_header("user-b", "b@example.com")
    business_b = client.post("/businesses", json={"name": "Shop B"}, headers=headers_b).json()

    response = client.delete(f"/businesses/{business_b['id']}", headers=headers_a)
    assert response.status_code == 403

    # Confirmed still there via B's own credentials.
    listing = client.get("/businesses", headers=headers_b).json()
    assert len(listing) == 1


def test_deleting_an_already_deleted_shop_404s_not_500s(client):
    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()
    client.delete(f"/businesses/{business['id']}", headers=headers)

    response = client.delete(f"/businesses/{business['id']}", headers=headers)
    assert response.status_code == 404


def test_deleting_a_shop_does_not_touch_its_existing_data(client):
    # Confirmed at the API layer too, not just the repository unit test —
    # a seeded product must still be directly queryable after deletion.
    import uuid

    from app.models.product import Product

    headers = bearer_header("user-a", "a@example.com")
    business = client.post("/businesses", json={"name": "Shop A"}, headers=headers).json()

    session = client._SessionLocal()
    product = Product(business_id=uuid.UUID(business["id"]), name="Chain Lube", sku="CL-100")
    session.add(product)
    session.commit()
    product_id = product.id
    session.close()

    client.delete(f"/businesses/{business['id']}", headers=headers)

    session = client._SessionLocal()
    still_there = session.get(Product, product_id)
    assert still_there is not None
    assert still_there.name == "Chain Lube"
    session.close()
