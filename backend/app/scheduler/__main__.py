"""Entrypoint for the dedicated `scheduler` service (docker-compose.yml)
— a plain polling loop over app/scheduler/tick.py::run_tick, not a job
queue. No Redis, no Dramatiq/RQ/Celery: this project has no infrastructure
for any of that yet, and a fixed, coarse (weekly/monthly) cadence doesn't
need it — a periodic reconciliation check making ordinary DB calls through
the same repositories/application layer everything else uses is enough.

Run via: python -m app.scheduler
"""

import logging
import time

from app.models.base import SessionLocal
from app.scheduler.tick import run_tick

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Coarse enough for a once-a-week/once-a-month cadence — no need to poll
# more tightly than this, and it keeps the "how late can a report be"
# window small without hammering the database.
TICK_INTERVAL_SECONDS = 15 * 60


def main() -> None:
    logger.info("Report scheduler starting, tick interval=%ss", TICK_INTERVAL_SECONDS)
    while True:
        try:
            with SessionLocal() as db:
                summary = run_tick(db)
                logger.info("Tick complete: %s", summary)
        except Exception:
            # A failure in the tick loop itself (e.g. a transient DB
            # connection issue) must not kill the scheduler process —
            # it just tries again next interval.
            logger.exception("Scheduler tick failed unexpectedly")
        time.sleep(TICK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
