"""Covers app/weather/client.py::_parse_forecast_xml against a real
response shape from Met Éireann's forecast API (field names/nesting
confirmed live 18/08/2026 — see docs/governance/11_Development_Roadmap.md
v1.80), trimmed to a handful of <time> blocks spanning two calendar days.
Uses February timestamps rather than the real August capture date,
matching this codebase's own established fixture convention (see
tests/integration/test_forecast_service.py's own comment) — Dublin is
GMT+0 with no DST offset in February, so UTC timestamps equal local
wall-clock time and every expected value below is directly hand-
computable. No live network call in this test — get_forecast() itself
(the httpx call) is exercised only by the disclosed live scripts this
feature was validated with, never in the automated suite.
"""

from datetime import date
from decimal import Decimal

from app.weather.client import _parse_forecast_xml

# Real response shape: separate "instant" <time> blocks (from == to, carry
# temperature/windSpeed/etc under <location>) and "interval" blocks
# (from < to, carry only <precipitation> as an accumulation over that
# window) — confirmed live, not assumed. 3 instant + 2 interval blocks
# spanning 2026-02-18 (two instants, one interval) and 2026-02-19 (one
# instant, one interval).
_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<weatherdata xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
   <meta>
      <model name="harmonie" termin="2026-02-18T12:00:00Z" runended="2026-02-18T15:35:36Z" />
   </meta>
   <product class="pointData">
      <time datatype="forecast" from="2026-02-18T22:00:00Z" to="2026-02-18T22:00:00Z">
         <location altitude="32" latitude="53.3806" longitude="-6.1750">
            <temperature id="TTT" unit="celsius" value="14.3"/>
            <windSpeed id="ff" mps="5.0" beaufort="3" name="Gentle breeze"/>
            <humidity value="82.4" unit="percent"/>
         </location>
      </time>
      <time datatype="forecast" from="2026-02-18T21:00:00Z" to="2026-02-18T22:00:00Z">
         <location altitude="32" latitude="53.3806" longitude="-6.1750">
            <precipitation unit="mm" value="0.2" minvalue="0.1" maxvalue="0.3" probability="21.2"/>
         </location>
      </time>
      <time datatype="forecast" from="2026-02-18T23:00:00Z" to="2026-02-18T23:00:00Z">
         <location altitude="32" latitude="53.3806" longitude="-6.1750">
            <temperature id="TTT" unit="celsius" value="14.2"/>
            <windSpeed id="ff" mps="3.9" beaufort="3" name="Gentle breeze"/>
            <humidity value="85.1" unit="percent"/>
         </location>
      </time>
      <time datatype="forecast" from="2026-02-19T00:00:00Z" to="2026-02-19T00:00:00Z">
         <location altitude="32" latitude="53.3806" longitude="-6.1750">
            <temperature id="TTT" unit="celsius" value="12.0"/>
            <windSpeed id="ff" mps="8.5" beaufort="3" name="Gentle breeze"/>
            <humidity value="90.0" unit="percent"/>
         </location>
      </time>
      <time datatype="forecast" from="2026-02-18T23:00:00Z" to="2026-02-19T00:00:00Z">
         <location altitude="32" latitude="53.3806" longitude="-6.1750">
            <precipitation unit="mm" value="0.3" minvalue="0.1" maxvalue="0.4" probability="22.1"/>
         </location>
      </time>
   </product>
</weatherdata>
"""


def test_parses_real_shape_into_one_entry_per_local_calendar_day():
    days = _parse_forecast_xml(_SAMPLE_XML, business_timezone="Europe/Dublin")
    assert [d.day for d in days] == [date(2026, 2, 18), date(2026, 2, 19)]


def test_temperature_mean_min_max_are_hand_computable_from_the_instant_blocks():
    days = _parse_forecast_xml(_SAMPLE_XML, business_timezone="Europe/Dublin")
    day_18 = next(d for d in days if d.day == date(2026, 2, 18))
    # Two instant readings on this local day: 14.3 and 14.2.
    assert day_18.temp_mean_c == Decimal("14.25")
    assert day_18.temp_min_c == Decimal("14.20")
    assert day_18.temp_max_c == Decimal("14.30")

    day_19 = next(d for d in days if d.day == date(2026, 2, 19))
    assert day_19.temp_mean_c == Decimal("12.00")


def test_wind_speed_is_converted_from_mps_to_kph_and_takes_the_days_max():
    days = _parse_forecast_xml(_SAMPLE_XML, business_timezone="Europe/Dublin")
    day_18 = next(d for d in days if d.day == date(2026, 2, 18))
    # max(5.0, 3.9) mps * 3.6 = 18.00 kph
    assert day_18.wind_speed_kph == Decimal("18.00")


def test_precipitation_sums_across_interval_blocks_for_the_same_day():
    days = _parse_forecast_xml(_SAMPLE_XML, business_timezone="Europe/Dublin")
    # Attributed by each interval block's own `from` timestamp — both
    # sample blocks (21:00-22:00 and 23:00-00:00) start on 2026-02-18, so
    # both accumulate onto that day (0.2 + 0.3 = 0.5), even though the
    # second one's `to` rolls into the next calendar day.
    day_18 = next(d for d in days if d.day == date(2026, 2, 18))
    assert day_18.rain_mm == Decimal("0.50")

    day_19 = next(d for d in days if d.day == date(2026, 2, 19))
    assert day_19.rain_mm == Decimal("0.00")


def test_a_day_with_only_precipitation_and_no_instant_reading_is_not_reported():
    # A day must have at least one real temperature reading to be
    # reported at all -- a rain-only tail day (a real possibility at the
    # far edge of the forecast window) has no mean/min/max to compute and
    # must not silently default to a fabricated 0.
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<weatherdata>
   <product class="pointData">
      <time datatype="forecast" from="2026-08-20T23:00:00Z" to="2026-08-21T00:00:00Z">
         <location altitude="32" latitude="53.3806" longitude="-6.1750">
            <precipitation unit="mm" value="1.0"/>
         </location>
      </time>
   </product>
</weatherdata>
"""
    days = _parse_forecast_xml(xml, business_timezone="Europe/Dublin")
    assert days == []


def test_local_timezone_bucketing_shifts_the_day_boundary_for_a_non_utc_business():
    # A single instant just after UTC midnight buckets into the previous
    # local day for a negative-offset timezone -- proves this parses per
    # business_timezone, not a hardcoded UTC/Dublin assumption.
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<weatherdata>
   <product class="pointData">
      <time datatype="forecast" from="2026-08-19T01:00:00Z" to="2026-08-19T01:00:00Z">
         <location altitude="32" latitude="40.7" longitude="-74.0">
            <temperature id="TTT" unit="celsius" value="20.0"/>
         </location>
      </time>
   </product>
</weatherdata>
"""
    days = _parse_forecast_xml(xml, business_timezone="America/New_York")
    assert days[0].day == date(2026, 8, 18)
