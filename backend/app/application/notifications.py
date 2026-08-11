"""Deterministic notification generation for the ORLA Notification Centre.
Every notify_* function below is called from an already-existing,
already-tested trigger point elsewhere in this codebase (refresh_low_stock_
alerts, run_import, the report scheduler, employee_seats.py, the Stripe
webhook) — this module never computes a number itself, only formats one a
call site already has, the same relationship app/application/alerts.py has
to app/analytics/findings.py. AI never touches any of this (CLAUDE.md's
Core Rule): a notification's title/body is plain Python string formatting
over deterministic inputs.

Uses "flush only, caller commits" (every repository/application function
in this codebase) — notify() itself never calls db.commit().
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.business import Business
from app.repositories.import_record import ImportRecordRepository
from app.repositories.notification import NotificationRepository

CATEGORY_STOCK = "stock"
CATEGORY_DATA_UPLOADS = "data_uploads"
CATEGORY_REPORTS = "reports"
CATEGORY_ORLA_INSIGHTS = "orla_insights"
CATEGORY_TEAM = "team"
CATEGORY_BILLING = "billing"
CATEGORY_BRANCHES = "branches"
CATEGORY_SECURITY_ACCOUNT = "security_account"

SEVERITY_INFO = "info"
SEVERITY_SUCCESS = "success"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


def notify(
    db: Session,
    *,
    business_id: uuid.UUID,
    category: str,
    type_key: str,
    severity: str,
    title: str,
    body: str,
    action_label: str | None = None,
    action_url: str | None = None,
    related_entity_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    visible_to_role: str | None = None,
    dedup_key: str | None = None,
):
    """Idempotent when dedup_key is given: updates the existing open
    (non-dismissed) row for that key in place instead of creating a
    duplicate — the ORLA Notification Centre's grouping/spam-control
    requirement. Leave dedup_key None for a genuinely one-off event
    (an employee was added, a specific import ran) that should never
    collapse into an earlier row."""
    repo = NotificationRepository(db)
    if dedup_key is not None:
        existing = repo.get_open_by_dedup_key(business_id, dedup_key)
        if existing is not None:
            return repo.update_and_reopen(existing, type_key=type_key, severity=severity, title=title, body=body)
    return repo.create(
        business_id=business_id,
        category=category,
        type_key=type_key,
        severity=severity,
        title=title,
        body=body,
        action_label=action_label,
        action_url=action_url,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        visible_to_role=visible_to_role,
        dedup_key=dedup_key,
    )


def _clear_dedup(db: Session, business_id: uuid.UUID, dedup_key: str) -> None:
    """Dismisses an existing open notification whose triggering condition
    has resolved (e.g. no products are below reorder point anymore) —
    mirrors AlertRepository's own create/update/resolve cycle."""
    repo = NotificationRepository(db)
    existing = repo.get_open_by_dedup_key(business_id, dedup_key)
    if existing is not None:
        repo.dismiss(existing)


# --- Stock -----------------------------------------------------------------


def notify_low_stock_summary(db: Session, *, business_id: uuid.UUID, low_stock_count: int) -> None:
    """low_stock_count must be the whole-business active count (e.g.
    AlertRepository.list_active_for_business), not just the products one
    import touched — a grouped summary has to reflect the real total or
    it misleads. Reuses the same source of truth app/application/report.py
    already reads for its own "N products low on stock" figure."""
    dedup_key = f"low_stock_summary:{business_id}"
    if low_stock_count <= 0:
        _clear_dedup(db, business_id, dedup_key)
        return
    plural = "s" if low_stock_count != 1 else ""
    verb = "are" if low_stock_count != 1 else "is"
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_STOCK,
        type_key="low_stock_summary",
        severity=SEVERITY_WARNING,
        title=f"{low_stock_count} product{plural} below reorder point",
        body=(
            f"{low_stock_count} product{plural} {verb} below their reorder point. "
            "Review Product Reorder Rules to see which ones and how much to order."
        ),
        action_label="Review Product Reorder Rules",
        action_url="/products",
        dedup_key=dedup_key,
    )


# --- Data & Uploads ----------------------------------------------------------

_ENTITY_LABELS = {
    "sales": "Sales data",
    "purchases": "Purchases data",
    "inventory": "Inventory data",
    "repairs": "Repairs data",
}


def notify_import_completed(
    db: Session,
    *,
    business_id: uuid.UUID,
    import_record_id: uuid.UUID,
    entity_type: str,
    rows_imported: int,
    rows_rejected: int,
) -> None:
    label = _ENTITY_LABELS.get(entity_type, entity_type.capitalize())
    if rows_imported == 0 and rows_rejected > 0:
        notify(
            db,
            business_id=business_id,
            category=CATEGORY_DATA_UPLOADS,
            type_key="import_failed",
            severity=SEVERITY_CRITICAL,
            title=f"We could not process this {label.lower()} upload",
            body=(
                f"We could not process this {label.lower()} upload — all {rows_rejected:,} row"
                f"{'s' if rows_rejected != 1 else ''} were rejected. Review the upload to see what needs fixing."
            ),
            action_label="Review Upload",
            action_url="/uploads",
            related_entity_type="import_record",
            related_entity_id=import_record_id,
        )
    elif rows_rejected > 0:
        notify(
            db,
            business_id=business_id,
            category=CATEGORY_DATA_UPLOADS,
            type_key="import_partial",
            severity=SEVERITY_WARNING,
            title=f"{label}: some rows need attention",
            body=(
                f"{rows_imported:,} record{'s' if rows_imported != 1 else ''} were imported, but "
                f"{rows_rejected:,} need your attention. Review the upload to see what needs fixing."
            ),
            action_label="Review Upload",
            action_url="/uploads",
            related_entity_type="import_record",
            related_entity_id=import_record_id,
        )
    else:
        notify(
            db,
            business_id=business_id,
            category=CATEGORY_DATA_UPLOADS,
            type_key="import_completed",
            severity=SEVERITY_SUCCESS,
            title=f"{label} updated successfully",
            body=f"{label} updated successfully: {rows_imported:,} record{'s' if rows_imported != 1 else ''} processed.",
            action_label="View Transactions",
            action_url="/transactions",
            related_entity_type="import_record",
            related_entity_id=import_record_id,
        )


# --- Data freshness -----------------------------------------------------------

# Scoped to "sales" only — the one entity type every business template
# actually has (bicycle-shop-specific "repairs" doesn't apply everywhere;
# CLAUDE.md's "no industry-specific assumptions in core services" holds:
# this isn't a bicycle-shop rule, "sales" is the generic revenue entity
# every vertical will have). Matches the ORLA Notification Centre prompt's
# own suggested copy, which is entirely about "sales data."
_FRESHNESS_ENTITY_TYPE = "sales"
# Past this many days with no completed sales import, the nudge escalates
# from an info-level daily reminder to a warning that insights may be
# stale. Deliberately stricter than the Uploads page's own passive
# STALE_AFTER_DAYS=7 indicator (frontend/app/uploads/page.tsx) — a
# notification is a more proactive nudge than a page you have to go look
# at, so it fires sooner.
_DATA_OUTDATED_AFTER_DAYS = 3


def _freshness_dedup_key(business_id: uuid.UUID) -> str:
    return f"data_freshness:{business_id}:{_FRESHNESS_ENTITY_TYPE}"


def check_data_freshness(db: Session, *, business: Business, now: datetime) -> None:
    """Called once per business per scheduler tick (app/scheduler/tick.py)
    — idempotent by dedup_key, so a re-run within the same day just
    updates the same open row (or is a genuine no-op once the wording
    already matches) rather than spamming. Uses only the already-existing,
    already-tested ImportRecordRepository.latest_completed_by_entity_type
    — no new calculation, purely a date comparison in the business's own
    timezone (CLAUDE.md: "UTC internally, business timezone in settings").
    """
    dedup_key = _freshness_dedup_key(business.id)
    latest = ImportRecordRepository(db).latest_completed_by_entity_type(business.id)
    last_completed_at = latest.get(_FRESHNESS_ENTITY_TYPE)

    days_since: int | None = None
    if last_completed_at is not None:
        tz = ZoneInfo(business.timezone)
        days_since = (now.astimezone(tz).date() - last_completed_at.astimezone(tz).date()).days

    if days_since is not None and days_since <= 0:
        # Uploaded today — resolve any open freshness notification rather
        # than waiting for the next tick to notice (this also happens
        # immediately on import, see resolve_data_freshness below; this
        # branch is what catches it on the next tick regardless).
        _clear_dedup(db, business.id, dedup_key)
        return

    is_branch = business.parent_business_id is not None

    if days_since is not None and days_since >= _DATA_OUTDATED_AFTER_DAYS:
        if is_branch:
            notify(
                db, business_id=business.id, category=CATEGORY_DATA_UPLOADS, type_key="branch_data_missing",
                severity=SEVERITY_WARNING, title=f"{business.name}: sales data is outdated",
                body=(
                    f"{business.name}'s sales data has not been updated for {days_since} days. "
                    "Some insights for this branch may no longer reflect its current business."
                ),
                action_label="Upload sales data", action_url="/uploads", dedup_key=dedup_key,
            )
        else:
            notify(
                db, business_id=business.id, category=CATEGORY_DATA_UPLOADS, type_key="data_outdated",
                severity=SEVERITY_WARNING, title="Sales data is outdated",
                body=(
                    f"Your sales data has not been updated for {days_since} days. "
                    "Some insights may no longer reflect your current business."
                ),
                action_label="Upload sales data", action_url="/uploads", dedup_key=dedup_key,
            )
        return

    # Never uploaded, or uploaded 1-2 days ago — the daily "please upload
    # today" nudge, not yet the more urgent "outdated" escalation.
    if is_branch:
        notify(
            db, business_id=business.id, category=CATEGORY_DATA_UPLOADS, type_key="branch_data_missing",
            severity=SEVERITY_INFO, title=f"No new sales data from {business.name}",
            body=f"No new sales data has been received from {business.name} today.",
            action_label="Upload sales data", action_url="/uploads", dedup_key=dedup_key,
        )
    else:
        notify(
            db, business_id=business.id, category=CATEGORY_DATA_UPLOADS, type_key="no_new_data_detected",
            severity=SEVERITY_INFO, title="No new sales data today",
            body="We have not received new sales data today. Update your data so ORLA can keep your insights current.",
            action_label="Upload sales data", action_url="/uploads", dedup_key=dedup_key,
        )


def resolve_data_freshness(db: Session, *, business_id: uuid.UUID, entity_type: str) -> None:
    """Called right after a successful import (app/imports/importer.py) so
    an open freshness notification clears the moment fresh data actually
    lands, rather than waiting for the next scheduler tick (up to 15
    minutes — app/scheduler/__main__.py's TICK_INTERVAL_SECONDS)."""
    if entity_type != _FRESHNESS_ENTITY_TYPE:
        return
    _clear_dedup(db, business_id, _freshness_dedup_key(business_id))


# --- Reports & ORLA Insights -------------------------------------------------


def notify_report_ready(
    db: Session, *, business_id: uuid.UUID, report_id: uuid.UUID, report_type: str, period_start: date, period_end: date
) -> None:
    label = "weekly" if report_type == "weekly" else "monthly"
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_REPORTS,
        type_key="report_ready",
        severity=SEVERITY_SUCCESS,
        title=f"Your {label} report is ready",
        body=f"Your {label} report for {period_start.isoformat()} to {period_end.isoformat()} is ready to view.",
        action_label="View Report",
        action_url=f"/reports/{report_id}",
        related_entity_type="report",
        related_entity_id=report_id,
        dedup_key=f"report:{report_id}",
    )


def notify_report_failed(db: Session, *, business_id: uuid.UUID, report_type: str, period_start: date) -> None:
    """Only called once a report is permanently failed (attempts exhausted
    — see app/scheduler/tick.py), never on a retry still under the cap,
    so a transient failure that resolves on its own next tick never
    notifies at all."""
    label = "weekly" if report_type == "weekly" else "monthly"
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_REPORTS,
        type_key="report_failed",
        severity=SEVERITY_CRITICAL,
        title=f"We could not complete your {label} report",
        body=(
            f"We could not complete your {label} report for the period starting {period_start.isoformat()} "
            "because of a data or processing problem. Your business data is safe."
        ),
        action_label="View Reports",
        action_url="/reports",
        dedup_key=f"report_failed:{business_id}:{report_type}:{period_start.isoformat()}",
    )


def notify_orla_insights(db: Session, *, business_id: uuid.UUID, report_id: uuid.UUID, recommendation_count: int) -> None:
    """Reuses the count of recommendations the report itself already
    computed (app/application/findings.py, via app/application/report.py's
    own payload) — no new calculation, purely a second, insights-framed
    notification pointing at the same already-generated report."""
    if recommendation_count <= 0:
        return
    plural = "ies" if recommendation_count != 1 else "y"
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_ORLA_INSIGHTS,
        type_key="new_recommendations",
        severity=SEVERITY_INFO,
        title=f"ORLA found {recommendation_count} opportunit{plural}",
        body=f"ORLA found {recommendation_count} opportunit{plural} that may improve your business, based on your latest report.",
        action_label="View Report",
        action_url=f"/reports/{report_id}",
        related_entity_type="report",
        related_entity_id=report_id,
        dedup_key=f"orla_insights:{report_id}",
    )


# --- Team --------------------------------------------------------------------

# Owner-only (Notification Centre permissions batch): who's on the team,
# whether their access/payment succeeded, and role changes are an
# owner/admin management concern, not something operational staff need
# surfaced — mirrors the same "staff seeing owner-only billing
# notifications" restriction already applied to CATEGORY_BILLING/
# CATEGORY_BRANCHES below. Stock/data_uploads/reports/orla_insights stay
# unrestricted (None) — those are the operational notifications staff
# need for daily work.


def notify_employee_added(db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID, full_name: str) -> None:
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_TEAM,
        type_key="employee_added",
        severity=SEVERITY_INFO,
        title=f"{full_name} has been added to your team",
        body=f"{full_name} has been added to your team. They'll get ORLA access once payment and registration are complete.",
        action_label="View Team",
        action_url="/onboarding",
        related_entity_type="employee_seat",
        related_entity_id=seat_id,
        visible_to_role="owner",
    )


def notify_employee_activated(db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID, full_name: str) -> None:
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_TEAM,
        type_key="employee_activated",
        severity=SEVERITY_SUCCESS,
        title=f"{full_name} now has access to ORLA",
        body=f"{full_name} now has access to ORLA.",
        action_label="View Team",
        action_url="/onboarding",
        related_entity_type="employee_seat",
        related_entity_id=seat_id,
        visible_to_role="owner",
        dedup_key=f"employee_activated:{seat_id}",
    )


def notify_employee_payment_failed(db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID, full_name: str) -> None:
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_TEAM,
        type_key="employee_payment_failed",
        severity=SEVERITY_WARNING,
        title=f"Payment for {full_name} could not be completed",
        body=f"Payment for {full_name} could not be completed. Their ORLA access has not been activated.",
        action_label="View Team",
        action_url="/onboarding",
        related_entity_type="employee_seat",
        related_entity_id=seat_id,
        visible_to_role="owner",
        dedup_key=f"employee_payment_failed:{seat_id}",
    )


def notify_employee_removed(db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID, full_name: str) -> None:
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_TEAM,
        type_key="employee_removed",
        severity=SEVERITY_INFO,
        title=f"{full_name}'s access has been removed",
        body=f"{full_name}'s access to ORLA has been removed.",
        related_entity_type="employee_seat",
        related_entity_id=seat_id,
        visible_to_role="owner",
    )


def notify_employee_role_changed(
    db: Session, *, business_id: uuid.UUID, seat_id: uuid.UUID, full_name: str, new_role: str
) -> None:
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_SECURITY_ACCOUNT,
        type_key="employee_role_changed",
        severity=SEVERITY_INFO,
        title=f"{full_name}'s role was changed",
        body=f"{full_name}'s role was changed to {new_role.capitalize()}.",
        action_label="View Team",
        action_url="/onboarding",
        related_entity_type="employee_seat",
        related_entity_id=seat_id,
        visible_to_role="owner",
    )


# --- Billing & Branches --------------------------------------------------------

# Only these three Stripe subscription statuses are worth a customer-facing
# notification — "incomplete"/"unpaid"/other transient in-between states
# aren't a clear enough signal to word a message around without guessing,
# so they deliberately notify nothing (never a fabricated status message).
_SUBSCRIPTION_STATUS_MESSAGES = {
    "active": (SEVERITY_SUCCESS, "renewed", "Your subscription has been successfully renewed."),
    "past_due": (
        SEVERITY_WARNING,
        "payment issue",
        "We could not process your latest payment. Update your payment method to avoid interruption.",
    ),
    "canceled": (SEVERITY_CRITICAL, "canceled", "Your subscription has been canceled."),
}


def notify_subscription_status_change(
    db: Session, *, business_id: uuid.UUID, business_name: str, is_branch: bool, new_status: str
) -> None:
    entry = _SUBSCRIPTION_STATUS_MESSAGES.get(new_status)
    if entry is None:
        return
    severity, short_label, message = entry
    category = CATEGORY_BRANCHES if is_branch else CATEGORY_BILLING
    subject = f"{business_name} branch" if is_branch else "Your ORLA subscription"
    notify(
        db,
        business_id=business_id,
        category=category,
        type_key="subscription_status_change",
        severity=severity,
        title=f"{subject}: {short_label}",
        body=message,
        action_label="Manage Billing",
        action_url="/onboarding",
        # Owner-only — the account's billing status is the owner's
        # concern, not every staff member's (ORLA Notification Centre
        # prompt's own "staff seeing owner-only billing notifications"
        # security requirement).
        visible_to_role="owner",
        dedup_key=f"subscription_status:{business_id}",
    )
