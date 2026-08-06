"""Shared dataclasses passed between the repository layer and the pure
formulas in app/analytics/financial.py, app/analytics/retail.py, and
app/analytics/workshop.py.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ProductPeriodAggregate:
    """One product's activity within a MetricPeriod, as summed from
    sale_items. Both financial.py (margin) and retail.py (stock cover,
    dead stock) read from this same shape rather than issuing separate
    aggregate queries over the same rows.

    revenue is every line item's quantity * unit_price, regardless of
    whether cost is known. revenue_with_known_cost and cogs only include
    line items where cost_price_at_sale was captured — per PR-3.6, revenue
    must never be understated just because cost data is missing, and
    margin must never be computed against revenue it can't be matched to
    a cost for.

    revenue_with_known_cost_and_tax/tax_amount_known/cogs_for_known_tax
    are a strict subset of the above — cost known AND tax_amount known —
    used to compute margin net of tax (app/analytics/financial.py's
    net_gross_margin_pct) without ever blending a tax-unknown line (which
    may still include tax in its revenue) into a "confirmed net" figure.
    """

    product_id: uuid.UUID
    units_sold: int
    revenue: Decimal
    revenue_with_known_cost: Decimal
    cogs: Decimal
    revenue_with_known_cost_and_tax: Decimal = Decimal("0")
    tax_amount_known: Decimal = Decimal("0")
    cogs_for_known_tax: Decimal = Decimal("0")


@dataclass(frozen=True)
class RepairPeriodTotals:
    """Business-wide totals for completed repairs in a period, as summed
    from production_events — no per-product breakdown (a repair isn't tied
    to one product the way a sale_item is), so this is a single row, not a
    group_by result.

    price_charged and labour_cost are both nullable on ProductionEvent (a
    repairs-file row is accepted with only one of description/price/labour
    present — see validate_and_parse_repair_row), so revenue and margin
    need the same known/unknown split as ProductPeriodAggregate:
    - revenue counts every repair with a known price_charged, regardless
      of whether labour_cost is also known.
    - labour_cost_known_revenue/labour_cost only count repairs where BOTH
      are known — margin is never computed against a price that has no
      matching labour cost to net against, or vice versa.
    """

    repair_count: int
    repairs_with_known_price: int
    revenue: Decimal
    repairs_with_known_price_and_labour: int
    labour_cost_known_revenue: Decimal
    labour_cost: Decimal
