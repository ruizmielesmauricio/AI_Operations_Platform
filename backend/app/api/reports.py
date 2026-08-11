import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.exports.docx import render_report_docx
from app.exports.pdf import render_report_pdf
from app.models.membership import Membership
from app.models.report import Report
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


def _get_available_report_or_404(db: Session, *, report_id: uuid.UUID, business_id: uuid.UUID) -> Report:
    """Shared availability check for get_report and both download routes
    below — a report that's pending/failed/expired reads as not found
    everywhere, never as a different, more informative error (same
    "don't leak existence" posture as the rest of this customer-facing
    API). The download routes enforce this exactly the same way as the
    JSON route does — membership/branch permission is never just "the UI
    hid the button" (this prompt's own explicit "never rely on a hidden
    button alone" requirement)."""
    report = ReportRepository(db).get_for_business(report_id, business_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    expired = report.expires_at is not None and _as_aware_utc(report.expires_at) <= datetime.now(timezone.utc)
    if report.status != "completed" or expired:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_filename_component(value: str) -> str:
    """Strips anything that isn't alphanumeric/underscore/hyphen — a
    business name is free-text a user chose, never trusted directly into
    a Content-Disposition header (header-injection risk) or a filesystem-
    adjacent string. Collapses to a short, still-recognisable slug."""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("-", value).strip("-")
    return cleaned[:60] or "report"


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
    report = _get_available_report_or_404(db, report_id=report_id, business_id=membership.business_id)
    return ReportDetailOut.model_validate(report)


@router.get("/{report_id}/download.pdf")
def download_report_pdf(
    report_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Response:
    """Real, server-generated PDF (ORLA Notifications/Security/Retention
    prompt, section 7) — permission enforcement happens here, at the
    route, exactly the same way get_report's JSON already does (get_
    current_membership + _get_available_report_or_404's own business_id/
    status/expiry checks) — never only a frontend button being hidden.
    """
    report = _get_available_report_or_404(db, report_id=report_id, business_id=membership.business_id)
    pdf_bytes = render_report_pdf(report.payload or {})
    business_slug = _safe_filename_component(report.payload.get("business_name", "report") if report.payload else "report")
    filename = f"{business_slug}-{report.report_type}-{report.period_start.date().isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{report_id}/download.docx")
def download_report_docx(
    report_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Response:
    """DOCX counterpart to download_report_pdf above — same permission
    enforcement, same source data, same filename convention."""
    report = _get_available_report_or_404(db, report_id=report_id, business_id=membership.business_id)
    docx_bytes = render_report_docx(report.payload or {})
    business_slug = _safe_filename_component(report.payload.get("business_name", "report") if report.payload else "report")
    filename = f"{business_slug}-{report.report_type}-{report.period_start.date().isoformat()}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
