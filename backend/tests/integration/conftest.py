import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    AIRequest,
    Alert,
    AuditLog,
    Base,
    Business,
    EmployeeSeat,
    ImportMappingProfile,
    ImportRecord,
    InventoryMovement,
    Membership,
    Notification,
    ProcessedStripeEvent,
    Product,
    ProductCategory,
    ProductionEvent,
    ProductSupplier,
    Report,
    Return,
    Sale,
    SaleItem,
    Subscription,
    Supplier,
    Upload,
    User,
)


@pytest.fixture(scope="session")
def _engine(tmp_path_factory):
    # A dedicated SQLite file, never the app's own DATABASE_URL — these tests
    # used to create_all()/drop_all() against whatever database that pointed
    # to, which meant running pytest against a local dev setup wiped every
    # table in it. Models are dialect-portable by design (see PKMixin), so
    # SQLite here is safe and gets everything the same isolation for free.
    db_path = tmp_path_factory.mktemp("integration") / "billing_webhook_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(_engine):
    TestSessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    session = TestSessionLocal()
    yield session
    # Code under test may call session.commit() itself, so tear down by
    # deleting rows rather than relying on a rollback to undo everything.
    session.rollback()
    session.query(AIRequest).delete()
    session.query(Report).delete()
    session.query(Notification).delete()
    session.query(Alert).delete()
    session.query(ProductionEvent).delete()
    session.query(InventoryMovement).delete()
    session.query(Return).delete()
    session.query(SaleItem).delete()
    session.query(Sale).delete()
    session.query(ProductSupplier).delete()
    session.query(Product).delete()
    session.query(ProductCategory).delete()
    session.query(Supplier).delete()
    session.query(ImportRecord).delete()
    session.query(ImportMappingProfile).delete()
    session.query(Upload).delete()
    session.query(Subscription).delete()
    session.query(ProcessedStripeEvent).delete()
    session.query(AuditLog).delete()
    session.query(EmployeeSeat).delete()
    session.query(Membership).delete()
    session.query(Business).delete()
    session.query(User).delete()
    session.commit()
    session.close()


@pytest.fixture
def business_id(db_session):
    business = Business(name="Test Business")
    db_session.add(business)
    db_session.commit()
    return business.id
