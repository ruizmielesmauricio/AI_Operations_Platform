import pytest

from app.models import Base, Business, ProcessedStripeEvent, Subscription
from app.models.base import SessionLocal, engine


@pytest.fixture(scope="session", autouse=True)
def _tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    # Code under test may call session.commit() itself, so tear down by
    # deleting rows rather than relying on a rollback to undo everything.
    session.rollback()
    session.query(Subscription).delete()
    session.query(ProcessedStripeEvent).delete()
    session.query(Business).delete()
    session.commit()
    session.close()


@pytest.fixture
def business_id(db_session):
    business = Business(name="Test Business")
    db_session.add(business)
    db_session.commit()
    return business.id
