"""Shared dataclasses passed between the repository layer and the pure
formulas in app/analytics/financial.py and app/analytics/retail.py.
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
    """

    product_id: uuid.UUID
    units_sold: int
    revenue: Decimal
    revenue_with_known_cost: Decimal
    cogs: Decimal
