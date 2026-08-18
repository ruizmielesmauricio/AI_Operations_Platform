import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.weather_observation import WeatherObservation


class WeatherObservationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, *, business_id: uuid.UUID, observed_date: date) -> WeatherObservation | None:
        return self.session.scalar(
            select(WeatherObservation).where(
                WeatherObservation.business_id == business_id,
                WeatherObservation.observed_date == observed_date,
            )
        )

    def upsert(
        self,
        *,
        business_id: uuid.UUID,
        observed_date: date,
        rain_mm: Decimal,
        temp_mean_c: Decimal,
        temp_min_c: Decimal,
        temp_max_c: Decimal,
        wind_speed_kph: Decimal,
    ) -> WeatherObservation:
        """Insert today's snapshot, or overwrite it if the scheduler's
        late-local-time gate (app/application/weather_ingestion.py)
        somehow runs twice for the same business/day — idempotent by
        design, never a duplicate row (the unique constraint on
        (business_id, observed_date) backs this at the DB level too).
        Flush only, no commit — matches this codebase's own convention
        (the caller owns the transaction boundary).
        """
        existing = self.get(business_id=business_id, observed_date=observed_date)
        if existing is not None:
            existing.rain_mm = rain_mm
            existing.temp_mean_c = temp_mean_c
            existing.temp_min_c = temp_min_c
            existing.temp_max_c = temp_max_c
            existing.wind_speed_kph = wind_speed_kph
            self.session.flush()
            return existing

        observation = WeatherObservation(
            business_id=business_id,
            observed_date=observed_date,
            rain_mm=rain_mm,
            temp_mean_c=temp_mean_c,
            temp_min_c=temp_min_c,
            temp_max_c=temp_max_c,
            wind_speed_kph=wind_speed_kph,
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def list_in_range(
        self, *, business_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[WeatherObservation]:
        """Inclusive of both ends — every stored day in [start_date,
        end_date], never zero-filled (app/analytics/weather_patterns.py
        only ever compares real, known days on both the weather and sales
        sides — see compute_weather_pattern_comparison's own docstring)."""
        return list(
            self.session.scalars(
                select(WeatherObservation)
                .where(
                    WeatherObservation.business_id == business_id,
                    WeatherObservation.observed_date >= start_date,
                    WeatherObservation.observed_date <= end_date,
                )
                .order_by(WeatherObservation.observed_date)
            )
        )
