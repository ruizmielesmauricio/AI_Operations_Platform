import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.membership import Membership
from app.repositories.report import ReportRepository
from app.schemas.report import ReportDetailOut, ReportSummaryOut
from app.security.tenant import get_current_membership

router = APIRouter(prefix="/businesses/{business_id}/reports", tags=["reports"])


def _as_aware_utc(value: datetime) -> datetime:
    # SQLite (used in tests) round-trips DateTime(timezone=True) columns
    # as naive Python datetimes, even though every value written here is
    # already UTC — normalize before comparing against an aware "now" so
    # this doesn't crash under SQLite while staying a no-op under Postgres
    # (which returns genuinely aware values for timestamptz columns).
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@router.get("", response_model=list[ReportSummaryOut])
def list_reports(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[ReportSummaryOut]:
    # Completed, not-yet-expired only (PR-8.5's seven-day customer-facing
    # availability) — an expired or still-pending/failed report simply
    # doesn't appear here, though its row persists as an operational audit
    # record (PR-8.12), unreachable through this customer-facing route.
    reports = ReportRepository(db).list_active_for_business(membership.business_id, now=datetime.now(timezone.utc))
    return [ReportSummaryOut.model_validate(r) for r in reports]


@router.get("/{report_id}", response_model=ReportDetailOut)
def get_report(
    report_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> ReportDetailOut:
    report = ReportRepository(db).get_for_business(report_id, membership.business_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    expired = report.expires_at is not None and _as_aware_utc(report.expires_at) <= datetime.now(timezone.utc)
    if report.status != "completed" or expired:
        # Same "don't leak a pending/failed/expired report's existence
        # via a 200" posture as everything else customer-facing in this
        # API — a report not currently available reads as not found, not
        # as a different, more informative error.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return ReportDetailOut.model_validate(report)
