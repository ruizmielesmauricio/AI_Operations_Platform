from fastapi import APIRouter
from sqlalchemy import text

from app.models.base import SessionLocal

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness check — the API process is up. Proves nothing about the database."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> dict:
    """Readiness check — proves the API can actually reach Postgres (Neon in prod,
    the local container in the prototype). This is the first end-to-end proof
    that the free-tier stack is wired together correctly."""
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
