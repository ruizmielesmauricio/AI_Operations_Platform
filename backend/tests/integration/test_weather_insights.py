"""Verifies app/application/weather_insights.py::get_weather_pattern_findings
wires the real repositories/DB correctly and honors every graceful-
degradation gate. The pure comparison math itself is already covered by
tests/unit/test_weather_patterns.py's hand-computed fixtures — this file
only proves the orchestration reads the right rows, calls the (mocked)
weather client correctly, and produces a Finding shaped the way
app/analytics/findings.py expects, never leaking a raw Met Éireann value
into evidence.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.application.weather_insights import (
    get_weather_pattern_comparisons_for_category,
    get_weather_pattern_findings,
    get_weather_sales_rankings,
)
from app.models.business import Business
from app.models.product import Product, ProductCategory
from app.models.sale import Sale, SaleItem
from app.models.weather_observation import WeatherObservation
from app.weather import client as weather_client
from app.weather.client import DailyForecast
from app.weather.exceptions import WeatherProviderError

_TODAY = date(2026, 2, 20)
_NOW = datetime(2026, 2, 20, 10, 0, tzinfo=timezone.utc)


def _set_coordinates(db_session, business_id):
    business = db_session.get(Business, business_id)
    business.latitude = Decimal("53.3806")
    business.longitude = Decimal("-6.1750")
    db_session.commit()
    return business


def _make_category(db_session, business_id, *, name):
    category = ProductCategory(business_id=business_id, name=name)
    db_session.add(category)
    db_session.flush()
    return category


def _make_product(db_session, business_id, *, name, category_id):
    product = Product(
        business_id=business_id, sku=None, name=name, category_id=category_id,
        cost_price=Decimal("5.00"), sell_price=Decimal("10.00"),
    )
    db_session.add(product)
    db_session.flush()
    return product


def _make_sale(db_session, business_id, *, sold_at, product_id, quantity):
    sale = Sale(business_id=business_id, sold_at=sold_at, total_amount=Decimal("10.00") * quantity, order_reference=None)
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(
            business_id=business_id, sale_id=sale.id, product_id=product_id,
            quantity=quantity, unit_price=Decimal("10.00"), cost_price_at_sale=Decimal("5.00"),
        )
    )
    db_session.flush()


def _make_weather_row(db_session, business_id, *, day, rain=Decimal("0"), temp=Decimal("15"), wind=Decimal("10")):
    db_session.add(
        WeatherObservation(
            business_id=business_id, observed_date=day, rain_mm=rain, temp_mean_c=temp,
            temp_min_c=temp, temp_max_c=temp, wind_speed_kph=wind,
        )
    )
    db_session.flush()


def _seed_rainy_pattern_history(db_session, business_id, category_id, *, anchor_today=_TODAY):
    """40 days of history ending the day before `anchor_today`: 12 rainy
    days with high sales (10/day), 28 dry days with low sales (2/day) —
    mirrors tests/unit/test_weather_patterns.py's own hand-computable
    fixture shape, just via real DB rows this time."""
    start = anchor_today - timedelta(days=40)
    for offset in range(40):
        day = start + timedelta(days=offset)
        rainy = offset < 12
        _make_weather_row(db_session, business_id, day=day, rain=Decimal("5") if rainy else Decimal("0"))
        product = _make_product(db_session, business_id, name=f"Item {offset}", category_id=category_id)
        quantity = 10 if rainy else 2
        _make_sale(db_session, business_id, sold_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc), product_id=product.id, quantity=quantity)
    db_session.commit()


def _mock_upcoming_rainy_forecast(monkeypatch, *, days=7, anchor_today=_TODAY):
    forecast = [
        DailyForecast(
            day=anchor_today + timedelta(days=i), rain_mm=Decimal("5.00"), temp_mean_c=Decimal("10.00"),
            temp_min_c=Decimal("8.00"), temp_max_c=Decimal("12.00"), wind_speed_kph=Decimal("10.00"),
        )
        for i in range(days)
    ]
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: forecast)


def test_no_coordinates_resolved_returns_no_findings(db_session, business_id):
    business = db_session.get(Business, business_id)
    assert business.latitude is None and business.longitude is None

    findings = get_weather_pattern_findings(db_session, business=business, now=_NOW)

    assert findings == []


def test_no_weather_history_yet_returns_no_findings(db_session, business_id):
    business = _set_coordinates(db_session, business_id)

    findings = get_weather_pattern_findings(db_session, business=business, now=_NOW)

    assert findings == []


def test_weather_sales_rankings_return_top_and_bottom_products_for_rainy_days(db_session, business_id):
    business = _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Accessories")
    top = _make_product(db_session, business_id, name="Rain Cape", category_id=category.id)
    middle = _make_product(db_session, business_id, name="Mudguard", category_id=category.id)
    bottom = _make_product(db_session, business_id, name="Bottle", category_id=category.id)

    start = _TODAY - timedelta(days=20)
    for offset in range(12):
        day = start + timedelta(days=offset)
        _make_weather_row(db_session, business_id, day=day, rain=Decimal("5"))
        sold_at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        _make_sale(db_session, business_id, sold_at=sold_at, product_id=top.id, quantity=10)
        _make_sale(db_session, business_id, sold_at=sold_at, product_id=middle.id, quantity=4)
        _make_sale(db_session, business_id, sold_at=sold_at, product_id=bottom.id, quantity=1)
    db_session.commit()

    result = get_weather_sales_rankings(
        db_session, business=business, bucket="rainy", entity_type="product", limit=2, now=_NOW
    )

    assert result is not None
    assert result.bucket_day_count == 12
    assert [(row.name, row.units_sold) for row in result.top] == [
        ("Rain Cape", Decimal("120")),
        ("Mudguard", Decimal("48")),
    ]
    assert [(row.name, row.units_sold) for row in result.bottom] == [
        ("Bottle", Decimal("12")),
        ("Mudguard", Decimal("48")),
    ]


def test_weather_sales_rankings_aggregate_by_category(db_session, business_id):
    business = _set_coordinates(db_session, business_id)
    rain_category = _make_category(db_session, business_id, name="Rain gear")
    other_category = _make_category(db_session, business_id, name="Other")
    rain_a = _make_product(db_session, business_id, name="Cape", category_id=rain_category.id)
    rain_b = _make_product(db_session, business_id, name="Overshoes", category_id=rain_category.id)
    other = _make_product(db_session, business_id, name="Bottle", category_id=other_category.id)

    start = _TODAY - timedelta(days=20)
    for offset in range(12):
        day = start + timedelta(days=offset)
        _make_weather_row(db_session, business_id, day=day, rain=Decimal("5"))
        sold_at = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        _make_sale(db_session, business_id, sold_at=sold_at, product_id=rain_a.id, quantity=6)
        _make_sale(db_session, business_id, sold_at=sold_at, product_id=rain_b.id, quantity=4)
        _make_sale(db_session, business_id, sold_at=sold_at, product_id=other.id, quantity=2)
    db_session.commit()

    result = get_weather_sales_rankings(
        db_session, business=business, bucket="rainy", entity_type="category", limit=5, now=_NOW
    )

    assert result is not None
    assert [(row.name, row.units_sold) for row in result.top] == [
        ("Rain gear", Decimal("120")),
        ("Other", Decimal("24")),
    ]


def test_a_real_pattern_with_a_matching_upcoming_forecast_produces_a_finding(db_session, business_id, monkeypatch):
    business = _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")
    _seed_rainy_pattern_history(db_session, business_id, category.id)
    _mock_upcoming_rainy_forecast(monkeypatch)

    findings = get_weather_pattern_findings(db_session, business=business, now=_NOW)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.type == "weather_pattern_insight"
    assert finding.severity == "info"
    assert finding.rule_id == "weather_pattern_insight"
    assert "Waterproof Gear" in finding.message
    assert finding.evidence["bucket"] == "rainy"
    assert finding.evidence["category_name"] == "Waterproof Gear"
    assert finding.evidence["bucket_day_count"] == 12
    # Compliance boundary: no raw Met Éireann figure anywhere in evidence
    # or the message — only the bucket label and this business's own real
    # sales numbers.
    forbidden_keys = {"rain_mm", "temp_mean_c", "temp_min_c", "temp_max_c", "wind_speed_kph"}
    assert not (forbidden_keys & finding.evidence.keys())


def test_upcoming_forecast_not_matching_any_bucket_produces_no_findings(db_session, business_id, monkeypatch):
    business = _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")
    _seed_rainy_pattern_history(db_session, business_id, category.id)

    # A cold upcoming week -- the seeded history has no "cold" days at all
    # (every seeded row is temp=15), so even though this forecast clears
    # classify_upcoming_buckets' own gate, there's no real historical
    # comparison for that bucket to surface. (A mild/dry forecast would
    # be the wrong choice here: the seeded dry days themselves legitimately
    # clear the mild_dry comparison gates too, so that forecast would
    # produce a second, equally real finding for that bucket instead of
    # testing "no match" at all.)
    forecast = [
        DailyForecast(
            day=_TODAY + timedelta(days=i), rain_mm=Decimal("0.00"), temp_mean_c=Decimal("3.00"),
            temp_min_c=Decimal("1.00"), temp_max_c=Decimal("5.00"), wind_speed_kph=Decimal("5.00"),
        )
        for i in range(7)
    ]
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: forecast)

    findings = get_weather_pattern_findings(db_session, business=business, now=_NOW)

    assert findings == []


def test_weather_provider_failure_returns_no_findings_not_an_exception(db_session, business_id, monkeypatch):
    business = _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")
    _seed_rainy_pattern_history(db_session, business_id, category.id)

    def _fail(**kwargs):
        raise WeatherProviderError("Met Éireann is unreachable")

    monkeypatch.setattr(weather_client, "get_forecast", _fail)

    findings = get_weather_pattern_findings(db_session, business=business, now=_NOW)

    assert findings == []


def test_get_findings_includes_weather_findings_when_no_category_filter_is_active(db_session, business_id, monkeypatch):
    # get_findings has no `now` parameter of its own (it resolves periods
    # from start_date/end_date directly, never "now") — get_weather_pattern_
    # findings still resolves its own "today" from the real wall clock in
    # this path, exactly as it would in production, so this seeds relative
    # to the real current date rather than a fixed fictional one.
    from app.application.findings import get_findings

    real_today = datetime.now(timezone.utc).date()
    _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")
    _seed_rainy_pattern_history(db_session, business_id, category.id, anchor_today=real_today)
    _mock_upcoming_rainy_forecast(monkeypatch, anchor_today=real_today)

    summary = get_findings(
        db_session, business_id=business_id, start_date=real_today - timedelta(days=6), end_date=real_today
    )

    weather_findings = [f for f in summary.findings if f.type == "weather_pattern_insight"]
    assert len(weather_findings) == 1
    weather_recommendations = [r for r in summary.recommendations if r.finding_type == "weather_pattern_insight"]
    assert len(weather_recommendations) == 1


def test_get_findings_excludes_weather_findings_when_a_category_filter_is_active(db_session, business_id, monkeypatch):
    from app.application.findings import get_findings

    real_today = datetime.now(timezone.utc).date()
    _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")
    _seed_rainy_pattern_history(db_session, business_id, category.id, anchor_today=real_today)
    _mock_upcoming_rainy_forecast(monkeypatch, anchor_today=real_today)

    summary = get_findings(
        db_session, business_id=business_id, start_date=real_today - timedelta(days=6), end_date=real_today,
        category_id=category.id,
    )

    assert [f for f in summary.findings if f.type == "weather_pattern_insight"] == []


# --- get_weather_pattern_comparisons_for_category -----------------------
# Ask ORLA's "does weather affect sales of [category]" intent
# (app/ai/service.py::_dispatch_weather_category_lookup) — deliberately
# NOT gated on the upcoming forecast matching, unlike
# get_weather_pattern_findings above. No weather_client mocking needed at
# all in these tests: this function never calls the forecast API.


def test_category_comparisons_no_coordinates_resolved_returns_empty(db_session, business_id):
    business = db_session.get(Business, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")

    comparisons = get_weather_pattern_comparisons_for_category(
        db_session, business=business, category_id=category.id, now=_NOW
    )

    assert comparisons == []


def test_category_comparisons_no_weather_history_yet_returns_empty(db_session, business_id):
    business = _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")

    comparisons = get_weather_pattern_comparisons_for_category(
        db_session, business=business, category_id=category.id, now=_NOW
    )

    assert comparisons == []


def test_category_comparisons_real_pattern_returned_with_no_upcoming_forecast_at_all(db_session, business_id):
    # The key distinguishing behavior versus get_weather_pattern_findings:
    # this must surface the real historical pattern even though nothing
    # here ever calls/mocks the forecast API — "tell me what my own
    # history shows," not "tell me only what matches this week."
    business = _set_coordinates(db_session, business_id)
    category = _make_category(db_session, business_id, name="Waterproof Gear")
    _seed_rainy_pattern_history(db_session, business_id, category.id)

    comparisons = get_weather_pattern_comparisons_for_category(
        db_session, business=business, category_id=category.id, now=_NOW
    )

    rainy = [c for c in comparisons if c.bucket == "rainy"]
    assert len(rainy) == 1
    comparison = rainy[0]
    assert comparison.category_id == category.id
    assert comparison.category_name == "Waterproof Gear"
    assert comparison.bucket_day_count == 12
    assert comparison.pct_difference > 0


def test_category_comparisons_unknown_category_id_returns_empty(db_session, business_id):
    business = _set_coordinates(db_session, business_id)
    known_category = _make_category(db_session, business_id, name="Waterproof Gear")
    _seed_rainy_pattern_history(db_session, business_id, known_category.id)

    other_category = _make_category(db_session, business_id, name="Bells")

    comparisons = get_weather_pattern_comparisons_for_category(
        db_session, business=business, category_id=other_category.id, now=_NOW
    )

    assert comparisons == []
