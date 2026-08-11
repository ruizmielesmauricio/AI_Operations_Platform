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
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.analytics.period import resolve_period
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


# --- Date-range filtering (ORLA Notifications/Security/Retention prompt's
# "Today, Last 7 days, Last 30 days and a custom inclusive date range")
# ------------------------------------------------------------------------

NOTIFICATION_DATE_FILTERS = ("today", "7d", "30d", "custom")
_DATE_FILTER_WINDOW_DAYS = {"today": 1, "7d": 7, "30d": 30}
# An inclusive custom range beyond this is rejected outright ("excessive
# ranges" — a notification history filter, not an unbounded export tool).
MAX_CUSTOM_RANGE_DAYS = 366


class InvalidNotificationDateFilter(ValueError):
    """Raised for a bad Today/7d/30d/custom combination — the API route
    (app/api/notifications.py) catches this and turns it into a 422 with
    the message below, rather than a route handler re-deriving the same
    validation itself (CLAUDE.md: thin route handlers, logic in
    domain/analytics)."""


def resolve_notification_date_range(
    business_timezone: str,
    *,
    date_filter: str | None,
    start_date: date | None,
    end_date: date | None,
    now: datetime,
) -> tuple[datetime, datetime] | None:
    """Turns the Notification Centre's Today/Last 7 days/Last 30 days/
    custom filter into a half-open UTC [start, end) range for
    NotificationRepository.list_for_business — reusing app/analytics/
    period.py's own local-calendar-day-to-UTC conversion (CLAUDE.md: "UTC
    internally, business timezone in settings") rather than a second,
    subtly different implementation. Returns None for "no date filter at
    all" (date_filter not given).
    """
    if date_filter is None:
        if start_date is not None or end_date is not None:
            raise InvalidNotificationDateFilter("start_date/end_date are only valid together with date_filter=custom")
        return None

    if date_filter == "custom":
        if start_date is None or end_date is None:
            raise InvalidNotificationDateFilter("date_filter=custom requires both start_date and end_date")
        if end_date < start_date:
            raise InvalidNotificationDateFilter("start_date must not be after end_date")
        if (end_date - start_date).days + 1 > MAX_CUSTOM_RANGE_DAYS:
            raise InvalidNotificationDateFilter(f"Custom date range cannot exceed {MAX_CUSTOM_RANGE_DAYS} days")
        period = resolve_period(business_timezone, start_date, end_date, now=now)
        return period.start, period.end

    if date_filter not in _DATE_FILTER_WINDOW_DAYS:
        raise InvalidNotificationDateFilter(f"Unsupported date_filter: {date_filter!r}")
    if start_date is not None or end_date is not None:
        raise InvalidNotificationDateFilter("start_date/end_date are only valid together with date_filter=custom")
    period = resolve_period(business_timezone, None, None, default_window_days=_DATE_FILTER_WINDOW_DAYS[date_filter], now=now)
    return period.start, period.end


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


def notify_stock_review(
    db: Session, *, business_id: uuid.UUID, week_start: date, out_of_stock_count: int, stale_count: int, excess_count: int
) -> None:
    """Weekly consolidated stock review — at most one notification per
    business/branch, no per-product lists (ORLA Notifications/Security/
    Retention prompt, section 2). Reprocessing the same week is idempotent
    via dedup_key, exactly like every other grouped notification here.

    `action_url` links to whichever non-zero count is most urgent to act
    on (out of stock, then stale, then excess) via a `?stock_filter=`
    query param on the Product Reorder Rules page — a single, honest
    simplification given `Notification` carries exactly one action link,
    not three; every count is still independently reachable by switching
    that page's own filter once there, just not as three separate deep
    links from this one notification.
    """
    dedup_key = f"stock_review:{business_id}:{week_start.isoformat()}"
    if out_of_stock_count <= 0 and stale_count <= 0 and excess_count <= 0:
        notify(
            db, business_id=business_id, category=CATEGORY_STOCK, type_key="stock_review_complete",
            severity=SEVERITY_SUCCESS, title="Weekly stock review complete",
            body="Weekly stock review: no out-of-stock, stale, or overstocked products to flag this week.",
            action_label="View Product Reorder Rules", action_url="/products", dedup_key=dedup_key,
        )
        return

    parts = []
    if out_of_stock_count > 0:
        parts.append(f"{out_of_stock_count} product{'s' if out_of_stock_count != 1 else ''} out of stock")
    if stale_count > 0:
        parts.append(f"{stale_count} may be stale")
    if excess_count > 0:
        parts.append(f"{excess_count} may be overstocked")
    summary = ", ".join(parts[:-1]) + (f" and {parts[-1]}" if len(parts) > 1 else parts[0])

    most_urgent_filter = "out_of_stock" if out_of_stock_count > 0 else "stale" if stale_count > 0 else "excess"

    notify(
        db, business_id=business_id, category=CATEGORY_STOCK, type_key="stock_review",
        severity=SEVERITY_WARNING, title="Weekly stock review",
        body=f"Weekly stock review: {summary}. Review recommendations.",
        action_label="Review Product Reorder Rules", action_url=f"/products?stock_filter={most_urgent_filter}",
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
#
# Every entity type this platform actually ingests today
# (app/imports/aliases.py's own SUPPORTED_ENTITY_TYPES). "sales" is the one
# generic revenue entity every vertical will have (CLAUDE.md: "no
# industry-specific assumptions in core services") so it's always checked,
# even for a business that's never uploaded anything yet. The other three
# are only ever checked once a business has completed at least one import
# of that type — that *is* "the business uses this dataset" (ORLA
# Notifications/Security/Retention prompt's "apply freshness checks only
# to dataset types the business uses or has configured as expected"), with
# no new schema needed: ImportRecordRepository.latest_completed_by_entity_
# type already only returns entries for types a business has actually
# imported at least once.

_FRESHNESS_ENTITY_TYPES = ("sales", "purchases", "inventory", "repairs")

_FRESHNESS_ENTITY_LABEL = {
    "sales": "Sales",
    "purchases": "Purchases",
    "inventory": "Inventory",
    "repairs": "Repairs",
}

# Sales: past this many days with no completed import, the nudge escalates
# from an info-level daily reminder to a warning that insights may be
# stale — unchanged from the original sales-only design (deliberately
# stricter than the Uploads page's own passive STALE_AFTER_DAYS=7
# indicator; a notification is a more proactive nudge than a page you
# have to go look at).
_SALES_OUTDATED_AFTER_DAYS = 3
# Purchases/inventory/repairs are naturally sparser than sales — a shop
# doesn't take a delivery or do a stock count every day the way it makes a
# sale, so nagging on the same near-daily cadence would be noise, not
# signal ("respect the expected upload cadence... do not assume every
# dataset must arrive daily"). No per-business cadence configuration
# exists in the product yet, so this is a deliberate, stated default (14
# days, warning-only — no separate daily info tier for these) rather than
# a learned one; a future per-business override is a reasonable
# refinement, not a gap in this pass.
_SPARSE_OUTDATED_AFTER_DAYS = 14


def _freshness_dedup_key(business_id: uuid.UUID) -> str:
    # One key per business, not per entity type — every currently-stale
    # dataset for a business consolidates into this single notification
    # ("consolidate multiple missing types into one notification").
    return f"data_freshness:{business_id}"


def _legacy_sales_only_freshness_dedup_key(business_id: uuid.UUID) -> str:
    # The dedup_key format used before this module's multi-dataset
    # redesign (a per-entity-type key, back when "sales" was the only
    # tracked type). Live-found real bug, not theoretical: a business
    # with an already-open freshness notification under this old key
    # never matched the new, renamed key above, so the next tick created
    # a *second*, duplicate notification instead of updating the
    # existing one in place — exactly the daily-duplicate spam this
    # whole feature exists to prevent. _reconcile_freshness folds any
    # open row under this legacy key into the new one on its very next
    # run, a one-time, idempotent migration baked into the code itself
    # rather than a separate backfill script.
    return f"data_freshness:{business_id}:sales"


@dataclass(frozen=True)
class _FreshnessFlag:
    entity_type: str
    severity: str  # info | warning
    days_since: int | None  # None only ever for sales, never uploaded at all


def _compute_freshness_flags(db: Session, business: Business, now: datetime) -> list[_FreshnessFlag]:
    latest = ImportRecordRepository(db).latest_completed_by_entity_type(business.id)
    tz = ZoneInfo(business.timezone)
    flags: list[_FreshnessFlag] = []

    for entity_type in _FRESHNESS_ENTITY_TYPES:
        last_completed_at = latest.get(entity_type)
        if entity_type != "sales" and last_completed_at is None:
            continue  # never used by this business — not an expected dataset

        days_since: int | None = None
        if last_completed_at is not None:
            days_since = (now.astimezone(tz).date() - last_completed_at.astimezone(tz).date()).days
            if days_since <= 0:
                continue  # fresh as of today

        if entity_type == "sales":
            if days_since is not None and days_since >= _SALES_OUTDATED_AFTER_DAYS:
                flags.append(_FreshnessFlag(entity_type, SEVERITY_WARNING, days_since))
            else:
                # Never uploaded, or uploaded 1-2 days ago — the daily
                # "please upload today" nudge, not yet the more urgent
                # "outdated" escalation.
                flags.append(_FreshnessFlag(entity_type, SEVERITY_INFO, days_since))
        else:
            if days_since is not None and days_since >= _SPARSE_OUTDATED_AFTER_DAYS:
                flags.append(_FreshnessFlag(entity_type, SEVERITY_WARNING, days_since))
            # else: within the sparser acceptable cadence — not flagged at all.

    return flags


def _build_freshness_message(business: Business, flags: list[_FreshnessFlag]) -> tuple[str, str, str, str]:
    """Returns (type_key, severity, title, body). When only "sales" is
    flagged, this reproduces the original sales-only wording byte-for-byte
    (same type_key/severity/title/body) — the multi-dataset behaviour is
    purely additive, appended as one extra sentence naming whichever other
    datasets are also overdue, never a rewrite of the sales-specific
    copy."""
    is_branch = business.parent_business_id is not None
    sales_flag = next((f for f in flags if f.entity_type == "sales"), None)
    other_flags = [f for f in flags if f.entity_type != "sales"]
    other_names = ", ".join(_FRESHNESS_ENTITY_LABEL[f.entity_type] for f in other_flags)

    if sales_flag is not None:
        if is_branch:
            type_key = "branch_data_missing"
            if sales_flag.severity == SEVERITY_WARNING:
                severity = SEVERITY_WARNING
                title = f"{business.name}: sales data is outdated"
                body = (
                    f"{business.name}'s sales data has not been updated for {sales_flag.days_since} days. "
                    "Some insights for this branch may no longer reflect its current business."
                )
            else:
                severity = SEVERITY_INFO
                title = f"No new sales data from {business.name}"
                body = f"No new sales data has been received from {business.name} today."
        else:
            if sales_flag.severity == SEVERITY_WARNING:
                type_key = "data_outdated"
                severity = SEVERITY_WARNING
                title = "Sales data is outdated"
                body = (
                    f"Your sales data has not been updated for {sales_flag.days_since} days. "
                    "Some insights may no longer reflect your current business."
                )
            else:
                type_key = "no_new_data_detected"
                severity = SEVERITY_INFO
                title = "No new sales data today"
                body = "We have not received new sales data today. Update your data so ORLA can keep your insights current."
        if other_flags:
            # A second, always-warning-tier dataset overdue outranks a
            # merely-info-tier sales nudge — the notification as a whole
            # should read as the more urgent of the two.
            severity = SEVERITY_WARNING
            plural = "s are" if len(other_flags) != 1 else " is"
            body += f" {other_names} data{plural} also overdue and hasn't been updated recently."
        return type_key, severity, title, body

    # Sales itself is fine — only purchases/inventory/repairs are flagged.
    # No precedent to reuse here (freshness was sales-only before this),
    # so this is a new, deliberately generic type_key.
    type_key = "datasets_outdated"
    severity = SEVERITY_WARNING
    if is_branch:
        title = f"{business.name}: {other_names} data needs updating"
        body = f"{other_names} data from {business.name} hasn't been updated in a while. Review and upload fresh data."
    else:
        title = f"{other_names} data needs updating"
        body = f"Your {other_names} data hasn't been updated in a while. Review and upload fresh data to keep ORLA's insights accurate."
    return type_key, severity, title, body


def _reconcile_freshness(db: Session, *, business: Business, now: datetime) -> None:
    dedup_key = _freshness_dedup_key(business.id)
    # One-time migration cleanup — see _legacy_sales_only_freshness_dedup_
    # key's own docstring. A no-op once no business has an open row left
    # under the old key.
    _clear_dedup(db, business.id, _legacy_sales_only_freshness_dedup_key(business.id))

    flags = _compute_freshness_flags(db, business, now)
    if not flags:
        _clear_dedup(db, business.id, dedup_key)
        return
    type_key, severity, title, body = _build_freshness_message(business, flags)
    notify(
        db, business_id=business.id, category=CATEGORY_DATA_UPLOADS, type_key=type_key,
        severity=severity, title=title, body=body,
        action_label="Upload data", action_url="/uploads", dedup_key=dedup_key,
    )


def check_data_freshness(db: Session, *, business: Business, now: datetime) -> None:
    """Called once per business per scheduler tick (app/scheduler/tick.py)
    — idempotent by dedup_key, so a re-run within the same day just
    updates the same open row (or is a genuine no-op once the wording
    already matches) rather than spamming. Uses only the already-existing,
    already-tested ImportRecordRepository.latest_completed_by_entity_type
    — no new calculation, purely a date comparison in the business's own
    timezone (CLAUDE.md: "UTC internally, business timezone in settings").
    Covers every dataset type the business actually uses (see
    _compute_freshness_flags), consolidated into at most one open
    notification per business.
    """
    _reconcile_freshness(db, business=business, now=now)


def resolve_data_freshness(db: Session, *, business_id: uuid.UUID, entity_type: str) -> None:
    """Called right after a successful import (app/imports/importer.py) so
    an open freshness notification updates the moment fresh data actually
    lands, rather than waiting for the next scheduler tick (up to 15
    minutes — app/scheduler/__main__.py's TICK_INTERVAL_SECONDS).
    `entity_type` is accepted for the call site's own clarity/logging —
    the reconciliation below recomputes every dataset's freshness from
    scratch regardless, since the consolidated message may still need to
    mention other, still-stale datasets even after this one just cleared."""
    business = db.get(Business, business_id)
    if business is None:
        return
    _reconcile_freshness(db, business=business, now=datetime.now(timezone.utc))


# --- Weekly Business Performance ----------------------------------------

# "Require at least four complete weeks unless the analytics layer has a
# stronger confidence rule" (the prompt's own wording) — no such stronger
# rule exists yet, so this is the floor: a business younger than this
# never gets a trend claim, no matter how big last week's swing looks.
_MIN_WEEKS_OF_HISTORY = 4
# Below this, a week-over-week change reads as ordinary noise, not a real
# trend worth a notification — "apply meaningful materiality thresholds
# so tiny changes do not become alerts."
_MATERIALITY_THRESHOLD_PCT = Decimal("5")


def notify_weekly_business_performance(
    db: Session,
    *,
    business_id: uuid.UUID,
    report_id: uuid.UUID,
    period_start: date,
    revenue_current: Decimal,
    revenue_previous: Decimal,
    revenue_change_pct: Decimal | None,
    earliest_sale_date: date | None,
) -> None:
    """Called at most once per business/branch, immediately after that
    business's Monday weekly report completes (app/scheduler/tick.py) —
    reuses the exact revenue/previous-revenue/change_pct the report
    itself already computed (app/analytics/financial.py::compute_revenue_
    change, via app/application/financial_performance.py), no second
    calculation. Idempotent per reporting week via dedup_key, so a rerun
    for the same business/week updates the existing row rather than
    duplicating it.

    Silently creates nothing (`_clear_dedup` only) whenever the change
    isn't reliable enough to name a trend from: fewer than
    _MIN_WEEKS_OF_HISTORY complete weeks of real sales history behind it,
    an unknown previous-period revenue (division-by-zero case — compute_
    revenue_change already returns change_pct=None for that), or a change
    smaller than the materiality threshold. This is deliberately not a
    second "report ready" message — notify_report_ready already fires,
    unconditionally, for every completed weekly report; this function
    only ever adds a *second*, performance-specific notification on top
    of that when there's a real, evidenced trend to report.
    """
    dedup_key = f"weekly_performance:{business_id}:{period_start.isoformat()}"

    sufficient_history = (
        earliest_sale_date is not None and (period_start - earliest_sale_date).days >= _MIN_WEEKS_OF_HISTORY * 7
    )
    if not sufficient_history or revenue_change_pct is None:
        _clear_dedup(db, business_id, dedup_key)
        return

    abs_change = abs(revenue_change_pct)
    if abs_change < _MATERIALITY_THRESHOLD_PCT:
        _clear_dedup(db, business_id, dedup_key)
        return

    verb = "increased" if revenue_change_pct > 0 else "declined"
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_REPORTS,
        type_key="weekly_performance",
        severity=SEVERITY_SUCCESS if revenue_change_pct > 0 else SEVERITY_WARNING,
        title=f"Weekly revenue {verb} {abs_change}%",
        body=(
            f"Revenue for the week of {period_start.isoformat()} {verb} {abs_change}% compared to the previous "
            f"week (from €{revenue_previous} to €{revenue_current}). See the full report for details."
        ),
        action_label="View Report",
        action_url=f"/reports/{report_id}",
        related_entity_type="report",
        related_entity_id=report_id,
        dedup_key=dedup_key,
    )


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


# --- ORLA System status (section 3) --------------------------------------
#
# No separate incident-tracking table/migration — Notification's own
# dedup_key + status (unread/read/dismissed) + update_and_reopen already
# is a lightweight incident tracker: create on first occurrence, update
# the same row in place on a repeat (never a duplicate), dismiss on
# resolve. Every function below just reuses that, exactly like every
# other grouped notification in this module. "Upload processing failed"
# and "upload completed with rejected rows" already exist
# (notify_import_completed's import_failed/import_partial branches,
# above); "a scheduled report failed" already exists (notify_report_
# failed, above) — only the two genuinely new signals are here.

# How far past its own due generation moment (app/analytics/period.py::
# report_generation_moment) a still-incomplete, still-retrying report has
# to be before it's "materially delayed," not just running a routine
# retry cycle. Also stands in for "a processing job is stuck beyond a
# defined timeout" — report generation is the one real tick-based,
# retryable job in this codebase; treating "delayed" and "stuck" as two
# separate checks against the exact same underlying data would just be
# the same signal under two names.
REPORT_DELAYED_AFTER_HOURS = 4


def notify_report_delayed(db: Session, *, business_id: uuid.UUID, report_type: str, period_start: date) -> None:
    label = "weekly" if report_type == "weekly" else "monthly"
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_REPORTS,
        type_key="report_delayed",
        severity=SEVERITY_WARNING,
        title=f"Your {label} report is taking longer than expected",
        body=(
            f"Your {label} report for the period starting {period_start.isoformat()} is taking longer than "
            "usual to generate. We'll notify you as soon as it's ready."
        ),
        action_label="View Reports",
        action_url="/reports",
        dedup_key=f"report_delayed:{business_id}:{report_type}:{period_start.isoformat()}",
    )


def resolve_report_delayed(db: Session, *, business_id: uuid.UUID, report_type: str, period_start: date) -> None:
    """Called the moment a delayed report either completes or permanently
    fails (app/scheduler/tick.py) — silently clears rather than sending a
    separate "resolved" message, since notify_report_ready/notify_report_
    failed already tell the real story at that point ("never send routine
    everything-is-working notifications")."""
    _clear_dedup(db, business_id, f"report_delayed:{business_id}:{report_type}:{period_start.isoformat()}")


# A single business's own failed AI call could be many things (a
# malformed question, that business's own rate limit) — only a run of
# failures *across every business* in a row looks like the provider
# itself being down, not one customer's bad luck.
AI_HEALTH_LOOKBACK_MINUTES = 30
AI_HEALTH_MIN_SAMPLE = 5


def is_ai_provider_likely_down(success_flags: list[bool]) -> bool:
    """Pure decision over AIRequestRepository.recent_platform_wide_
    success_flags's own output — too few recent calls to judge (a quiet
    period, not an outage) never counts as "down," and a single stray
    failure among otherwise-successful calls never does either."""
    return len(success_flags) >= AI_HEALTH_MIN_SAMPLE and not any(success_flags)


def notify_ai_insights_unavailable(db: Session, *, business_id: uuid.UUID, is_down: bool) -> None:
    """Called once per business per scheduler tick, driven by a single
    platform-wide health check the caller runs once per tick (app/
    scheduler/tick.py) — never technical exception text, only the plain
    customer-facing fact (CLAUDE.md/this prompt's own "never expose
    technical exception text to users" rule). Silently clears (no
    separate "recovered" notification) the moment the platform-wide
    signal recovers."""
    dedup_key = f"ai_insights_unavailable:{business_id}"
    if not is_down:
        _clear_dedup(db, business_id, dedup_key)
        return
    notify(
        db,
        business_id=business_id,
        category=CATEGORY_ORLA_INSIGHTS,
        type_key="ai_insights_unavailable",
        severity=SEVERITY_WARNING,
        title="ORLA insights are temporarily unavailable",
        body=(
            "ORLA's AI assistant is temporarily unavailable. Your dashboard, reports, and data are "
            "unaffected — try Ask ORLA again shortly."
        ),
        action_label="View Dashboard",
        action_url="/dashboard",
        dedup_key=dedup_key,
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
