from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class WeatherObservation(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """ORLA's own accumulating daily weather record for a business's
    location — one row per (business_id, observed_date), built forward
    from whenever this feature ships (never backfilled synthetically,
    same "don't fabricate history" posture as app/analytics/forecasting.py's
    MIN_HISTORY_DAYS gate).

    Written once per business per local calendar day by
    app/application/weather_ingestion.py::snapshot_daily_weather, using
    Met Éireann's forecast API's near-term nowcast late in the local day
    as a stand-in for that day's actual conditions — Met Éireann's own
    separate historical-observation archive is unavailable at the time
    this was built (see docs/governance/11_Development_Roadmap.md), and
    this snapshot approach can be swapped for a real observation source
    later without touching app/analytics/weather_patterns.py at all,
    since it only ever consumes these stored rows, never how they got here.

    Read only by app/application/weather_insights.py — never exposed
    directly on any API route or response; only the derived comparison
    (bucket label + the business's own real sales numbers) is meant to
    ever reach a user-facing surface, per the compliance decision behind
    this feature (never republish Met Éireann's own figures).
    """

    __tablename__ = "weather_observations"
    __table_args__ = (UniqueConstraint("business_id", "observed_date", name="uq_weather_observations_business_date"),)

    observed_date: Mapped[date] = mapped_column(Date, nullable=False)
    rain_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    temp_mean_c: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    temp_min_c: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    temp_max_c: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    wind_speed_kph: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
