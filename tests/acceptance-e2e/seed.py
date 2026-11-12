"""Browser-test database seeding for ORLA acceptance e2e tests.

PROTECTED: the autobuild loop may not edit tests/acceptance-e2e/.

  python seed.py reset                 -> drop + recreate the e2e schema, migrate to head
  python seed.py data OWNER STAFF      -> subscription, staff membership, two weeks of
                                          sales and a fresh weekly report for OWNER's business

Safety: refuses to touch any database that is not on localhost/127.0.0.1 or
whose name doesn't contain "e2e". It never reads DATABASE_URL — only
ORLA_E2E_DATABASE_URL.
"""

import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))


def _load_env():
    path = REPO / ".env.test.local"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _db_url() -> str:
    _load_env()
    url = os.environ.get("ORLA_E2E_DATABASE_URL", "postgresql+psycopg://aiops:aiops_dev_password@localhost:5432/orla_e2e")
    parsed = urlparse(url.replace("+psycopg", ""))
    if parsed.hostname not in {"localhost", "127.0.0.1"} or "e2e" not in (parsed.path or ""):
        sys.exit(f"refusing to seed non-local / non-e2e database: host={parsed.hostname} db={parsed.path}")
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("ENVIRONMENT", "test")
    return url


def reset():
    url = _db_url()
    from sqlalchemy import create_engine, text

    parsed = urlparse(url.replace("+psycopg", ""))
    dbname = parsed.path.lstrip("/")
    admin = create_engine(url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin.dispose()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ, "DATABASE_URL": url})


def data(owner_id: str, staff_id: str):
    url = _db_url()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.application.report import generate_report
    from app.models.membership import Membership
    from app.models.product import Product
    from app.models.sale import Sale, SaleItem
    from app.models.subscription import Subscription
    from app.models.user import User

    engine = create_engine(url)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    owner_membership = s.query(Membership).filter(Membership.user_id == owner_id, Membership.role == "owner").one()
    bid = owner_membership.business_id
    s.add(Subscription(business_id=bid, stripe_customer_id="cus_e2e_owner", stripe_subscription_id="sub_e2e_owner",
                       status="active"))
    if s.get(User, staff_id) is None:
        s.add(User(id=staff_id, email=os.environ.get("ORLA_TEST_STAFF_EMAIL", "staff@example.com")))
        s.flush()
    s.add(Membership(business_id=bid, user_id=staff_id, role="staff"))

    products = {}
    for name, sku, cost in [("Flat White", "FW", "0.90"), ("Almond Croissant", "AC", "1.10"), ("Scone", "SC", "0.80")]:
        p = Product(business_id=bid, name=name, sku=sku, cost_price=Decimal(cost))
        s.add(p)
        products[name] = (p, Decimal(cost))
    s.flush()
    today = date.today()
    for d in range(1, 15):
        day = today - timedelta(days=d)
        for name, qty, price in [("Flat White", 20 + d % 5, "3.80"), ("Almond Croissant", 8, "3.50"), ("Scone", 3, "2.90")]:
            product, cost = products[name]
            sale = Sale(business_id=bid, sold_at=datetime(day.year, day.month, day.day, 10, tzinfo=timezone.utc),
                        total_amount=Decimal(price) * qty)
            s.add(sale)
            s.flush()
            s.add(SaleItem(business_id=bid, sale_id=sale.id, product_id=product.id, quantity=qty,
                           unit_price=Decimal(price), cost_price_at_sale=cost))
    s.commit()

    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Dublin")
    now_local = datetime.now(zone)
    monday = now_local.date() - timedelta(days=now_local.weekday())
    run_local = datetime(monday.year, monday.month, monday.day, 8, 0, tzinfo=zone)
    if run_local > now_local:
        run_local -= timedelta(days=7)
    from app.scheduler.tick import run_tick

    run_tick(s, now=run_local.astimezone(timezone.utc))
    s.commit()
    s.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["reset"]:
        reset()
    elif sys.argv[1:2] == ["data"] and len(sys.argv) == 4:
        data(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
