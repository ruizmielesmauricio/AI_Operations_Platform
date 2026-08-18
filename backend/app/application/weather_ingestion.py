"""ORLA's own daily weather snapshot — the reason this exists at all
(rather than reading from Met Éireann's own historical-observation
archive) is that archive being unavailable at the time this was built
(cli.fusio.net, confirmed down 18/08/2026 — see
docs/governance/11_Development_Roadmap.md v1.80). Production only ever
talks to Met Éireann's live forecast API (app/weather/client.py); this
module just decides *when* to call it and stores one row per business per
local calendar day, building up ORLA's own historical record forward from
whenever this ships. Swappable later for a real observation source
without touching app/analytics/weather_patterns.py at all, since that
module only ever consumes the stored rows, never how they got there.
"""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.business import Business
from app.repositories.weather_observation import WeatherObservationRepository
from app.weather import client as weather_client
from app.weather.exceptions import WeatherProviderError

logger = logging.getLogger(__name__)

# Late enough in the local day that the forecast API's near-term nowcast
# for "today" is a reasonable stand-in for that day's actual conditions —
# mirrors app/analytics/period.py's own "run once, at a fixed local
# moment" pattern (report_generation_moment), for a different job.
SNAPSHOT_HOUR_LOCAL = 20


def _is_past_snapshot_moment(business_timezone: str, *, now: datetime) -> bool:
    local_now = now.astimezone(ZoneInfo(business_timezone))
    return local_now.time() >= time(SNAPSHOT_HOUR_LOCAL, 0)


def snapshot_daily_weather(db: Session, *, business: Business, now: datetime) -> bool:
    """Writes today's weather_observations row for one business, if it
    has a resolved latitude/longitude, it's past this business's own
    local snapshot moment today, and no row exists yet for today's local
    date. Returns whether a row was actually written — purely for the
    scheduler tick's own counters, callers don't need to branch on it.

    Never raises: a network failure, a malformed response, or any other
    error here must not break the rest of the scheduler tick (matches
    every other per-business try/except already in app/scheduler/tick.py) —
    callers still wrap this in their own try/except regardless, since a
    genuinely unexpected bug (not just a provider failure) shouldn't be
    trusted to stay contained here either.
    """
    if business.latitude is None or business.longitude is None:
        # No resolved coordinates — most commonly geocoding not
        # configured/no address saved yet (see app/geocoding/service.py::
        # resolve_and_persist_coordinates) — quietly skip, same
        # graceful-degradation posture as every other optional provider
        # in this codebase.
        return False

    if not _is_past_snapshot_moment(business.timezone, now=now):
        return False

    local_today = now.astimezone(ZoneInfo(business.timezone)).date()
    repo = WeatherObservationRepository(db)
    if repo.get(business_id=business.id, observed_date=local_today) is not None:
        return False

    try:
        forecast_days = weather_client.get_forecast(
            lat=business.latitude, lon=business.longitude, business_timezone=business.timezone
        )
    except WeatherProviderError as exc:
        logger.warning("Weather snapshot failed for business=%s: %s", business.id, exc)
        return False

    todays_entry = next((d for d in forecast_days if d.day == local_today), None)
    if todays_entry is None:
        # The forecast response's own hourly/interval data didn't cover
        # today's local date at all (a real, if unlikely, possibility this
        # late in the day) — nothing honest to store.
        return False

    repo.upsert(
        business_id=business.id,
        observed_date=local_today,
        rain_mm=todays_entry.rain_mm,
        temp_mean_c=todays_entry.temp_mean_c,
        temp_min_c=todays_entry.temp_min_c,
        temp_max_c=todays_entry.temp_max_c,
        wind_speed_kph=todays_entry.wind_speed_kph,
    )
    return True
