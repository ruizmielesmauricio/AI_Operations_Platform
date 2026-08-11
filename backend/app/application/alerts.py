"""Orchestrates real-time low-stock alerting (Stage C12, PD-009/PR-9):
resolves each touched product's threshold, computes stock cover for just
those products, calls the existing C10 rule (app/analytics/findings.py::
evaluate_low_stock, unmodified), and reconciles the result against
persisted Alert rows. Called from app/imports/importer.py right after
run_import's/undo_import's own commit — see those call sites for why this
is a separate, try/except-wrapped step rather than part of the same
transaction.
"""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from app.analytics.findings import evaluate_low_stock, resolve_low_stock_threshold
from app.analytics.period import resolve_period
from app.analytics.retail import StockCoverRow, build_stock_cover_report
from app.application.notifications import notify_low_stock_summary
from app.models.business import Business
from app.repositories.alert import AlertRepository
from app.repositories.inventory_movement import InventoryMovementRepository
from app.repositories.product import ProductCategoryRepository, ProductRepository
from app.repositories.sale_item import SaleItemRepository

_ALERT_TYPE = "low_stock"


def _jsonable_evidence(evidence: dict) -> dict:
    """Finding.evidence carries Decimal values; Alert.payload is a generic
    JSON column (plain json.dumps under the hood, per app/models/alert.py),
    which doesn't know how to serialize Decimal. Converts to str, which
    round-trips exactly (unlike float) and is how money/rates are already
    rendered everywhere else in this codebase's API responses."""
    return {key: (str(value) if isinstance(value, Decimal) else value) for key, value in evidence.items()}


def refresh_low_stock_alerts(db: Session, *, business_id: uuid.UUID, product_ids: set[uuid.UUID]) -> None:
    if not product_ids:
        return

    business = db.get(Business, business_id)
    if business is None:
        return

    products_by_id = {p.id: p for p in ProductRepository(db).list_for_business(business_id)}
    category_threshold_by_id = {
        c.id: c.low_stock_threshold_days for c in ProductCategoryRepository(db).list_for_business(business_id)
    }
    # Ignore ids for products that no longer exist (e.g. deleted between the
    # write and this call) — nothing to alert on.
    relevant_ids = [pid for pid in product_ids if pid in products_by_id]
    if not relevant_ids:
        return

    period = resolve_period(business.timezone, None, None)  # trailing 30 days, same default as C9/C10's dashboards

    stock_by_product = InventoryMovementRepository(db).sum_by_product_ids(business_id, relevant_ids)
    aggregates_by_product = {
        a.product_id: a
        for a in SaleItemRepository(db).aggregate_by_product_in_range(business_id, period.start, period.end)
    }
    name_by_id = {pid: p.name for pid, p in products_by_id.items()}

    # build_stock_cover_report only produces rows for keys present in
    # stock_by_product, which InventoryMovementRepository.sum_by_product_ids
    # scoped to relevant_ids — so this is already limited to the touched
    # products, not the whole catalogue.
    stock_cover_rows: list[StockCoverRow] = build_stock_cover_report(
        aggregates_by_product, stock_by_product, name_by_id, period.days
    )

    rows_by_threshold: dict[Decimal, list[StockCoverRow]] = defaultdict(list)
    for row in stock_cover_rows:
        product = products_by_id[row.product_id]
        category_threshold = category_threshold_by_id.get(product.category_id) if product.category_id else None
        threshold = resolve_low_stock_threshold(product.low_stock_threshold_days, category_threshold)
        rows_by_threshold[threshold].append(row)

    low_stock_by_product = {}
    for threshold, rows in rows_by_threshold.items():
        for finding in evaluate_low_stock(rows, threshold_days=threshold):
            low_stock_by_product[uuid.UUID(finding.evidence["product_id"])] = finding

    alert_repo = AlertRepository(db)
    existing_by_product = alert_repo.get_active_by_type_and_product_ids(business_id, _ALERT_TYPE, relevant_ids)

    for product_id in relevant_ids:
        finding = low_stock_by_product.get(product_id)
        existing = existing_by_product.get(product_id)
        if finding is not None:
            payload = {
                "severity": finding.severity,
                "message": finding.message,
                "evidence": _jsonable_evidence(finding.evidence),
            }
            if existing is None:
                alert_repo.create(business_id=business_id, alert_type=_ALERT_TYPE, product_id=product_id, payload=payload)
            else:
                alert_repo.update_payload(existing, payload)
        elif existing is not None:
            alert_repo.resolve(existing)

    # A grouped, whole-business notification, not one per product (ORLA
    # Notification Centre's own spam-control requirement) — reuses the
    # exact same active-alert count app/application/report.py already
    # reads for its own "N products low on stock" figure, not just the
    # touched-product subset above, so the summary is always the real
    # total regardless of how many products this particular import
    # happened to touch.
    active_low_stock_count = len(
        [a for a in alert_repo.list_active_for_business(business_id) if a.alert_type == _ALERT_TYPE]
    )
    notify_low_stock_summary(db, business_id=business_id, low_stock_count=active_low_stock_count)

    db.commit()
