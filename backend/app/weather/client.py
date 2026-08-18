"""Direct boundary to Met Éireann's public forecast API — no other module
makes this HTTP call, mirroring app/geocoding/client.py's own boundary
role. Confirmed live (18/08/2026): no API key, HTTP only (HTTPS fails at
the TLS handshake on this host — not a bug here, a real limitation of the
endpoint itself), real data ~10 days ahead. See docs/governance/
11_Development_Roadmap.md v1.80 for the vendor-spike writeup this is
built from.

Deliberately the only file that parses Met Éireann's XML shape — callers
(app/application/weather_ingestion.py, app/application/weather_insights.py)
only ever see plain DailyForecast values, never the raw response.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx

from app.weather.exceptions import WeatherProviderError

_FORECAST_URL = "http://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast"
_TIMEOUT_SECONDS = 15.0
_MPS_TO_KPH = Decimal("3.6")
_TWO_DP = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DailyForecast:
    """One calendar day's weather, aggregated from Met Éireann's raw
    hourly/interval response — day-of-week-local-timezone bucketed by the
    caller-supplied business_timezone, not UTC. Mirrors WeatherObservation's
    columns 1:1 (app/models/weather_observation.py); callers that only
    need the fields app/analytics/weather_patterns.py actually uses build
    a DailyWeather from a subset of this.
    """

    day: date
    rain_mm: Decimal
    temp_mean_c: Decimal
    temp_min_c: Decimal
    temp_max_c: Decimal
    wind_speed_kph: Decimal


def get_forecast(*, lat: Decimal, lon: Decimal, business_timezone: str) -> list[DailyForecast]:
    """Real daily aggregates for roughly the next 10 days (Met Éireann's
    own hourly-then-3hr-then-6hr resolution taper — confirmed live, not
    assumed). The query string is deliberately built by hand rather than
    passed as an httpx `params` dict: Met Éireann's endpoint expects
    `lat=X;long=Y` (semicolon-joined), not the standard `&`-joined query
    string every `params` dict would produce — confirmed live; the
    request 400s otherwise.

    Raises WeatherProviderError for a network failure, non-2xx, or a body
    that doesn't parse as the expected XML shape — always caught by
    callers, never left to bubble up and break a scheduler tick or a
    Findings computation.
    """
    url = f"{_FORECAST_URL}?lat={lat};long={lon}"
    try:
        response = httpx.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        xml_text = response.text
    except httpx.HTTPError as exc:
        raise WeatherProviderError(str(exc)) from exc

    try:
        return _parse_forecast_xml(xml_text, business_timezone=business_timezone)
    except ElementTree.ParseError as exc:
        raise WeatherProviderError(f"Met Éireann returned unparseable XML: {exc}") from exc


def _parse_forecast_xml(xml_text: str, *, business_timezone: str) -> list[DailyForecast]:
    root = ElementTree.fromstring(xml_text)
    tz = ZoneInfo(business_timezone)

    temps_by_day: dict[date, list[Decimal]] = {}
    winds_by_day: dict[date, list[Decimal]] = {}
    rain_by_day: dict[date, Decimal] = {}

    for time_el in root.iter("time"):
        from_attr = time_el.get("from")
        if not from_attr:
            continue
        # Met Éireann's timestamps are always Z-suffixed UTC — Python's
        # fromisoformat only accepts "+00:00" for older versions still in
        # this image's support window, so normalize explicitly rather
        # than assume a newer stdlib.
        from_dt = datetime.fromisoformat(from_attr.replace("Z", "+00:00"))
        local_date = from_dt.astimezone(tz).date()

        location_el = time_el.find("location")
        if location_el is None:
            continue

        temp_el = location_el.find("temperature")
        if temp_el is not None and temp_el.get("value") is not None:
            temps_by_day.setdefault(local_date, []).append(Decimal(temp_el.get("value")))

        wind_el = location_el.find("windSpeed")
        if wind_el is not None and wind_el.get("mps") is not None:
            winds_by_day.setdefault(local_date, []).append(Decimal(wind_el.get("mps")) * _MPS_TO_KPH)

        # Precipitation is reported on separate interval blocks (from < to
        # — an accumulation over that window), not on the same instant
        # blocks as temperature/wind — Met Éireann's own response shape,
        # confirmed live. Interval blocks are contiguous and non-
        # overlapping by construction, so summing every block whose
        # `from` falls on a given local day yields that day's real total,
        # regardless of whether the underlying blocks are hourly (near
        # term) or 3-/6-hourly (further out).
        precip_el = location_el.find("precipitation")
        if precip_el is not None and precip_el.get("value") is not None:
            rain_by_day[local_date] = rain_by_day.get(local_date, Decimal("0")) + Decimal(precip_el.get("value"))

    days: list[DailyForecast] = []
    for day in sorted(temps_by_day):
        temps = temps_by_day[day]
        winds = winds_by_day.get(day, [])
        days.append(
            DailyForecast(
                day=day,
                rain_mm=_quantize(rain_by_day.get(day, Decimal("0"))),
                temp_mean_c=_quantize(sum(temps) / len(temps)),
                temp_min_c=_quantize(min(temps)),
                temp_max_c=_quantize(max(temps)),
                wind_speed_kph=_quantize(max(winds)) if winds else Decimal("0.00"),
            )
        )
    return days
