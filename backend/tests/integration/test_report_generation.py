"""Stage D17/D18 — verifies app/application/report.py's assembly (SQL
wiring, payload shape, idempotency) against a real (SQLite) database. The
underlying calculations are already covered by their own dedicated test
suites (C9-C13) — this file only needs to prove the report assembly reads
the right rows and produces a sane, complete payload.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.application.report import generate_report
from app.models.inventory_movement import InventoryMovement
from app.models.product import Product
from app.models.sale import Sale, SaleItem
from app.repositories.report import ReportRepository

# January in Dublin (the default business timezone) is GMT — UTC+0, no DST
# offset to account for — keeping the fixture data's UTC timestamps equal
# to local wall-clock time (same precaution as test_forecast_service.py).
# 2026-01-05 is a Monday.
_NOW = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
_LAST_WEEK_START = date(2025, 12, 29)
_LAST_WEEK_END = date(2026, 1, 4)


def _make_product(db_session, business_id, *, name="Chain Lube"):
    product = Product(business_id=business_id, sku=None, name=name, cost_price=Decimal("5.00"), sell_price=Decimal("10.00"))
    db_session.add(product)
    db_session.flush()
    return product


def _make_sale(db_session, business_id, *, sold_date, product_id, quantity):
    sold_at = datetime.combine(sold_date, time.min, tzinfo=timezone.utc)
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=Decimal("10.00") * quantity, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(
        business_id=business_id, sale_id=sale.id, product_id=product_id, quantity=quantity,
        unit_price=Decimal("10.00"), cost_price_at_sale=Decimal("5.00"),
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(InventoryMovement(business_id=business_id, product_id=product_id, quantity_delta=-quantity, reason="sale", event_date=sold_date))
    db_session.flush()


def test_generate_report_produces_a_complete_payload_for_a_seeded_business(db_session, business_id):
    product = _make_product(db_session, business_id)
    for offset in range(7):  # every day of last week
        _make_sale(db_session, business_id, sold_date=_LAST_WEEK_START + timedelta(days=offset), product_id=product.id, quantity=2)
    db_session.commit()

    report = generate_report(db_session, business_id=business_id, report_type="weekly", now=_NOW)

    assert report.status == "completed"
    assert report.period_start.date() == _LAST_WEEK_START
    # period_end is exclusive (MetricPeriod's own convention) — midnight
    # the day *after* the last included day, not that day itself.
    assert report.period_end.date() == _LAST_WEEK_END + timedelta(days=1)
    # expires_at is 7 days after the injected `now` used for generation
    # (not real wall-clock created_at — those only coincide when `now` is
    # left to default to the real clock, as it does in production).
    # SQLite round-trips a DateTime(timezone=True) column as naive (a
    # SQLAlchemy/SQLite quirk, not an app behavior) — .replace(tzinfo=None)
    # is a no-op if already naive, so this works regardless.
    assert report.expires_at.replace(tzinfo=None) == (_NOW + timedelta(days=7)).replace(tzinfo=None)

    payload = report.payload
    assert payload["business_name"] == "Test Business"
    assert payload["business_type"] == "bicycle_shop"
    assert payload["report_type"] == "weekly"
    assert payload["executive_summary"]["transactions"] == 7
    assert payload["executive_summary"]["narrative"]  # non-empty
    assert payload["financial_performance"]["revenue"]["current"] == "140.00"  # 7 days * 2 units * 10.00
    assert payload["retail_operations"] is not None
    assert payload["forecast"] is not None
    assert payload["findings"] is not None
    # Bike shop template -> workshop section present (even with no repairs data).
    assert payload["workshop_performance"] is not None


def test_generate_report_omits_workshop_section_for_a_non_bicycle_template(db_session, business_id):
    from app.models.business import Business

    business = db_session.get(Business, business_id)
    business.template = "other"
    db_session.commit()

    report = generate_report(db_session, business_id=business_id, report_type="weekly", now=_NOW)

    assert report.payload["workshop_performance"] is None


def test_generate_report_is_idempotent(db_session, business_id):
    first = generate_report(db_session, business_id=business_id, report_type="weekly", now=_NOW)
    second = generate_report(db_session, business_id=business_id, report_type="weekly", now=_NOW)

    assert first.id == second.id

    all_reports = ReportRepository(db_session).list_active_for_business(business_id, now=_NOW)
    assert len(all_reports) == 1


def test_generate_report_monthly_covers_the_previous_calendar_month(db_session, business_id):
    report = generate_report(db_session, business_id=business_id, report_type="monthly", now=_NOW)

    assert report.period_start.date() == date(2025, 12, 1)
    assert report.period_end.date() == date(2026, 1, 1)  # exclusive — midnight starting Jan 1
    assert report.payload["report_type"] == "monthly"
