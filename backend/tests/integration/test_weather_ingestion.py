"""Verifies app/application/weather_ingestion.py::snapshot_daily_weather's
SQL wiring and every gate (no coordinates, not yet the local snapshot
moment, already snapshotted today, provider failure, today missing from
the response) against a real (SQLite) database. Never touches the real
Met Éireann endpoint — app.weather.client.get_forecast is always mocked.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.application.weather_ingestion import SNAPSHOT_HOUR_LOCAL, snapshot_daily_weather
from app.models.business import Business
from app.repositories.weather_observation import WeatherObservationRepository
from app.weather import client as weather_client
from app.weather.client import DailyForecast
from app.weather.exceptions import WeatherProviderError

# February in Dublin (the default business timezone) is GMT — UTC+0, no
# DST offset to account for, matching this repo's other UTC-fixture tests.
_TODAY = date(2026, 2, 20)
_BEFORE_SNAPSHOT_MOMENT = datetime(2026, 2, 20, 10, 0, tzinfo=timezone.utc)
_AFTER_SNAPSHOT_MOMENT = datetime(2026, 2, 20, SNAPSHOT_HOUR_LOCAL + 1, 0, tzinfo=timezone.utc)


def _forecast_for_today(**overrides) -> list[DailyForecast]:
    defaults = dict(
        day=_TODAY, rain_mm=Decimal("2.50"), temp_mean_c=Decimal("11.00"),
        temp_min_c=Decimal("8.00"), temp_max_c=Decimal("14.00"), wind_speed_kph=Decimal("15.00"),
    )
    defaults.update(overrides)
    return [DailyForecast(**defaults)]


def test_no_coordinates_resolved_writes_nothing(db_session, business_id):
    business = db_session.get(Business, business_id)
    assert business.latitude is None

    written = snapshot_daily_weather(db_session, business=business, now=_AFTER_SNAPSHOT_MOMENT)

    assert written is False
    assert WeatherObservationRepository(db_session).get(business_id=business_id, observed_date=_TODAY) is None


def test_before_the_local_snapshot_moment_writes_nothing(db_session, business_id, monkeypatch):
    business = db_session.get(Business, business_id)
    business.latitude, business.longitude = Decimal("53.3806"), Decimal("-6.1750")
    db_session.commit()
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: _forecast_for_today())

    written = snapshot_daily_weather(db_session, business=business, now=_BEFORE_SNAPSHOT_MOMENT)

    assert written is False
    assert WeatherObservationRepository(db_session).get(business_id=business_id, observed_date=_TODAY) is None


def test_after_the_snapshot_moment_writes_a_real_row_from_the_forecast(db_session, business_id, monkeypatch):
    business = db_session.get(Business, business_id)
    business.latitude, business.longitude = Decimal("53.3806"), Decimal("-6.1750")
    db_session.commit()
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: _forecast_for_today())

    written = snapshot_daily_weather(db_session, business=business, now=_AFTER_SNAPSHOT_MOMENT)

    assert written is True
    row = WeatherObservationRepository(db_session).get(business_id=business_id, observed_date=_TODAY)
    assert row is not None
    assert row.rain_mm == Decimal("2.50")
    assert row.temp_mean_c == Decimal("11.00")
    assert row.wind_speed_kph == Decimal("15.00")


def test_a_row_already_present_for_today_is_left_alone_and_the_provider_is_not_even_called(
    db_session, business_id, monkeypatch
):
    business = db_session.get(Business, business_id)
    business.latitude, business.longitude = Decimal("53.3806"), Decimal("-6.1750")
    db_session.commit()
    WeatherObservationRepository(db_session).upsert(
        business_id=business_id, observed_date=_TODAY, rain_mm=Decimal("0"),
        temp_mean_c=Decimal("9"), temp_min_c=Decimal("9"), temp_max_c=Decimal("9"), wind_speed_kph=Decimal("5"),
    )
    db_session.commit()

    calls = []
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: calls.append(1) or _forecast_for_today())

    written = snapshot_daily_weather(db_session, business=business, now=_AFTER_SNAPSHOT_MOMENT)

    assert written is False
    assert calls == []  # never even reached the provider — the existence check short-circuits first
    row = WeatherObservationRepository(db_session).get(business_id=business_id, observed_date=_TODAY)
    assert row.rain_mm == Decimal("0")  # untouched, not overwritten by the (never-called) mock's 2.50


def test_provider_failure_writes_nothing_and_does_not_raise(db_session, business_id, monkeypatch):
    business = db_session.get(Business, business_id)
    business.latitude, business.longitude = Decimal("53.3806"), Decimal("-6.1750")
    db_session.commit()

    def _fail(**kwargs):
        raise WeatherProviderError("Met Éireann is unreachable")

    monkeypatch.setattr(weather_client, "get_forecast", _fail)

    written = snapshot_daily_weather(db_session, business=business, now=_AFTER_SNAPSHOT_MOMENT)

    assert written is False
    assert WeatherObservationRepository(db_session).get(business_id=business_id, observed_date=_TODAY) is None


def test_todays_date_missing_from_the_forecast_response_writes_nothing(db_session, business_id, monkeypatch):
    business = db_session.get(Business, business_id)
    business.latitude, business.longitude = Decimal("53.3806"), Decimal("-6.1750")
    db_session.commit()
    # A real, if unlikely, possibility this late in the day -- the
    # response's own hourly/interval data just didn't cover today at all.
    monkeypatch.setattr(weather_client, "get_forecast", lambda **kwargs: [])

    written = snapshot_daily_weather(db_session, business=business, now=_AFTER_SNAPSHOT_MOMENT)

    assert written is False
