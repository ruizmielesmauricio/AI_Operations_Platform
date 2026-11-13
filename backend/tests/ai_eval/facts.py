"""Expected facts for the Ask ORLA eval, computed deterministically from the
database at run time — never hand-typed numbers that drift when the data
changes.

Two sources, on purpose:

- Independent SQL (`_sql_*`) for every figure simple enough to restate from
  the raw tables: revenue, returns, units/revenue per product, stock on hand,
  prices, purchase lines, repairs, purchase spend. These do NOT go through the
  app's own calculation code, so a wrong number in the calc layer would show
  up as a disagreement instead of being echoed into the expected answer.
  Where the app computes the same figure, both are compared and every
  mismatch is recorded in `FactEnv.integrity_issues` (printed in the report).
- The app's own deterministic calc layer (`app.application.*`) for figures
  that are formulas rather than sums — margin %, change %, forecast totals,
  reorder quantities, findings, stored report fields. Those formulas already
  have their own unit tests (CLAUDE.md: "tests required for every business
  formula"); the eval's job there is checking ORLA repeats them faithfully.

A case names a fact by key plus parameters (see cases.json); `resolve_fact`
turns that into one or more `Fact`s for scoring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.period import DEFAULT_WINDOW_DAYS, compute_report_period
from app.application.category_breakdown import get_category_breakdown
from app.application.financial_performance import get_financial_performance
from app.application.findings import get_findings
from app.application.forecast import get_forecast
from app.application.retail_operations import get_retail_operations
from app.application.workshop_performance import get_workshop_performance
from app.models.business import Business
from app.repositories.report import ReportRepository


@dataclass(frozen=True)
class Fact:
    """One thing a correct answer must contain.

    - `number` only: that number must appear among the answer's numeric
      claims (Decimal equality, so "€1,234.50" matches 1234.5).
    - `text` only: that text must appear (case-insensitive).
    - both: attribution — the number must appear in the same line or
      sentence as the text (catches "right number, wrong product").
    - `zero_ok`: a zero figure may instead be stated in words ("no sales").
    """

    label: str
    number: Decimal | None = None
    text: str | None = None
    zero_ok: bool = False
    # Other exact figures that state the same fact (e.g. a 0-1 rate and
    # the same rate as a percentage).
    alternatives: tuple[Decimal, ...] = ()
    # Text-only fact satisfied by any one of these (e.g. the latest order's
    # reference or any product on it).
    any_text: tuple[str, ...] = ()


@dataclass
class FactEnv:
    db: Session
    business: Business
    group: list[Business]
    now: datetime
    integrity_issues: list[str] = field(default_factory=list)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.business.timezone)

    @property
    def today(self) -> date:
        return self.now.astimezone(self.tz).date()


# --- periods ---------------------------------------------------------------


def local_dates(env: FactEnv, period: Any) -> tuple[date, date]:
    """Inclusive business-local (start, end) for a case's period spec:
    "recent" (the app's trailing default window), "last_week",
    "last_month", or {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}."""
    if period in (None, "recent"):
        return env.today - timedelta(days=DEFAULT_WINDOW_DAYS - 1), env.today
    if period == "last_week":
        return compute_report_period(env.business.timezone, "weekly", now=env.now)
    if period == "last_month":
        return compute_report_period(env.business.timezone, "monthly", now=env.now)
    if isinstance(period, dict):
        start = date.fromisoformat(period["start"])
        return start, date.fromisoformat(period.get("end", period["start"]))
    raise ValueError(f"Unknown period spec {period!r}")


def previous_dates(start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)


def _utc_bounds(env: FactEnv, start: date, end: date) -> tuple[datetime, datetime]:
    lo = datetime.combine(start, time.min, tzinfo=env.tz)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=env.tz)
    return lo, hi


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _business_ids(env: FactEnv, scope: str | None) -> list[uuid.UUID]:
    return [b.id for b in env.group] if scope == "all_branches" else [_scoped_business(env, scope).id]


def _scoped_business(env: FactEnv, scope: str | None) -> Business:
    if scope in (None, "self", "all_branches"):
        return env.business
    for b in env.group:
        if b.name == scope:
            return b
    raise ValueError(f"No business named {scope!r} in the eval group")


def _check(env: FactEnv, label: str, sql_value: Any, app_value: Any) -> None:
    if Decimal(str(sql_value)) != Decimal(str(app_value)):
        env.integrity_issues.append(f"{label}: independent SQL={sql_value} vs app calc={app_value}")


# --- independent SQL --------------------------------------------------------


def _sql_revenue(env: FactEnv, ids: list[uuid.UUID], start: date, end: date) -> Decimal:
    lo, hi = _utc_bounds(env, start, end)
    value = env.db.execute(
        text(
            "select coalesce(sum(total_amount), 0) from sales "
            "where business_id = any(:ids) and sold_at >= :lo and sold_at < :hi"
        ),
        {"ids": ids, "lo": lo, "hi": hi},
    ).scalar()
    return _money(value)


def _sql_returns(env: FactEnv, business_id: uuid.UUID, start: date, end: date) -> tuple[int, Decimal]:
    lo, hi = _utc_bounds(env, start, end)
    count, amount = env.db.execute(
        text(
            "select count(r.id), coalesce(sum(r.refund_amount), 0) from returns r "
            "join sale_items si on si.id = r.sale_item_id join sales s on s.id = si.sale_id "
            "where r.business_id = :b and s.sold_at >= :lo and s.sold_at < :hi"
        ),
        {"b": business_id, "lo": lo, "hi": hi},
    ).one()
    return int(count), _money(amount)


def _sql_product_sales(env: FactEnv, business_id: uuid.UUID, start: date, end: date) -> list[tuple[str, int, Decimal]]:
    """(name, units, revenue) per product, units desc then revenue desc."""
    lo, hi = _utc_bounds(env, start, end)
    rows = env.db.execute(
        text(
            "select p.name, sum(si.quantity), sum(si.quantity * si.unit_price) from sale_items si "
            "join sales s on s.id = si.sale_id join products p on p.id = si.product_id "
            "where si.business_id = :b and s.sold_at >= :lo and s.sold_at < :hi group by p.name"
        ),
        {"b": business_id, "lo": lo, "hi": hi},
    ).all()
    return [(name, int(units), _money(rev)) for name, units, rev in rows]


def _sql_stock(env: FactEnv, product_name: str) -> int:
    value = env.db.execute(
        text(
            "select coalesce(sum(m.quantity_delta), 0) from inventory_movements m join products p on p.id = m.product_id "
            "where m.business_id = :b and p.name = :n"
        ),
        {"b": env.business.id, "n": product_name},
    ).scalar()
    return int(value)


def _sql_product(env: FactEnv, product_name: str) -> dict:
    row = env.db.execute(
        text("select name, sku, cost_price, sell_price from products where business_id = :b and name = :n"),
        {"b": env.business.id, "n": product_name},
    ).one()
    return {"name": row[0], "sku": row[1], "cost_price": row[2], "sell_price": row[3]}


def _sql_repairs(env: FactEnv, ids: list[uuid.UUID], start: date, end: date) -> tuple[int, Decimal, Decimal]:
    lo, hi = _utc_bounds(env, start, end)
    count, revenue, labour = env.db.execute(
        text(
            "select count(*), coalesce(sum(price_charged), 0), coalesce(sum(labour_cost), 0) from production_events "
            "where business_id = any(:ids) and status = 'completed' and completed_at >= :lo and completed_at < :hi"
        ),
        {"ids": ids, "lo": lo, "hi": hi},
    ).one()
    return int(count), _money(revenue), _money(labour)


def _sql_category_sales(env: FactEnv, start: date, end: date) -> dict[str, Decimal]:
    lo, hi = _utc_bounds(env, start, end)
    rows = env.db.execute(
        text(
            "select c.name, sum(si.quantity * si.unit_price) from sale_items si join sales s on s.id = si.sale_id "
            "join products p on p.id = si.product_id join product_categories c on c.id = p.category_id "
            "where si.business_id = :b and s.sold_at >= :lo and s.sold_at < :hi group by c.name"
        ),
        {"b": env.business.id, "lo": lo, "hi": hi},
    ).all()
    return {name: _money(v) for name, v in rows}


def _sql_category_spend(env: FactEnv, start: date, end: date) -> dict[str, Decimal]:
    rows = env.db.execute(
        text(
            "select c.name, sum(m.quantity_delta * m.unit_cost) from inventory_movements m "
            "join products p on p.id = m.product_id join product_categories c on c.id = p.category_id "
            "where m.business_id = :b and m.reason = 'purchase' and m.unit_cost is not null "
            "and m.event_date >= :s and m.event_date <= :e group by c.name"
        ),
        {"b": env.business.id, "s": start, "e": end},
    ).all()
    return {name: _money(v) for name, v in rows}


# --- fact resolvers ----------------------------------------------------------

Resolver = Callable[..., list[Fact]]
_RESOLVERS: dict[str, Resolver] = {}


def _resolver(name: str) -> Callable[[Resolver], Resolver]:
    def register(fn: Resolver) -> Resolver:
        _RESOLVERS[name] = fn
        return fn

    return register


def _financial_app(env: FactEnv, scope: str | None, start: date, end: date):
    return get_financial_performance(env.db, business_id=_scoped_business(env, scope).id, start_date=start, end_date=end)


@_resolver("revenue")
def _revenue(env: FactEnv, period: Any = "recent", scope: str | None = None) -> list[Fact]:
    start, end = local_dates(env, period)
    value = _sql_revenue(env, _business_ids(env, scope), start, end)
    if scope != "all_branches":
        _check(env, f"revenue {period} {scope or ''}".strip(), value, _financial_app(env, scope, start, end).revenue.current)
    return [Fact(label=f"revenue {start}..{end}", number=value, zero_ok=True)]


@_resolver("revenue_previous")
def _revenue_previous(env: FactEnv, period: Any = "recent", also_calendar_month: bool = False) -> list[Fact]:
    """The app's previous period is the same number of days immediately
    before (for October: 31 Aug-30 Sep). "The month before" can also
    fairly mean the calendar month, so `also_calendar_month` accepts that
    figure too — either is a correct, grounded answer."""
    start, end = local_dates(env, period)
    p_start, p_end = previous_dates(start, end)
    value = _sql_revenue(env, [env.business.id], p_start, p_end)
    _check(env, f"previous revenue {period}", value, _financial_app(env, None, start, end).revenue.previous)
    alternatives: tuple[Decimal, ...] = ()
    if also_calendar_month:
        month_end = start - timedelta(days=1)
        alternatives = (_sql_revenue(env, [env.business.id], month_end.replace(day=1), month_end),)
    return [Fact(label=f"previous-period revenue {p_start}..{p_end}", number=value, zero_ok=True, alternatives=alternatives)]


@_resolver("revenue_change_pct")
def _revenue_change_pct(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    change = _financial_app(env, None, start, end).revenue.change_pct
    return [Fact(label="revenue change %", number=abs(change))]


@_resolver("gross_margin_pct")
def _gross_margin_pct(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    pct = _financial_app(env, None, start, end).gross_margin.gross_margin_pct
    return [Fact(label="gross margin %", number=pct)]


@_resolver("gross_profit")
def _gross_profit(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    return [Fact(label="gross profit", number=_financial_app(env, None, start, end).gross_margin.gross_profit)]


@_resolver("returns")
def _returns(env: FactEnv, period: Any = "recent", what: str = "amount") -> list[Fact]:
    start, end = local_dates(env, period)
    count, amount = _sql_returns(env, env.business.id, start, end)
    app = _financial_app(env, None, start, end).returns
    _check(env, f"returns count {period}", count, app.return_count)
    _check(env, f"returns amount {period}", amount, app.returns_amount)
    if what == "count":
        return [Fact(label="return count", number=Decimal(count), zero_ok=True)]
    return [Fact(label="refunded amount", number=amount, zero_ok=True)]


@_resolver("lowest_margin_product")
def _lowest_margin_product(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    rows = _financial_app(env, None, start, end).bottom_margin_products
    worst = min(rows, key=lambda r: r.gross_margin_pct)
    return [Fact(label="lowest-margin product", text=worst.name, number=abs(worst.gross_margin_pct))]


@_resolver("top_gross_profit_product")
def _top_gross_profit_product(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    best = _financial_app(env, None, start, end).top_margin_products[0]
    return [Fact(label="product with the most gross profit", text=best.name, number=best.gross_profit)]


@_resolver("top_sellers_units")
def _top_sellers_units(env: FactEnv, period: Any = "recent", n: int = 1) -> list[Fact]:
    start, end = local_dates(env, period)
    rows = sorted(_sql_product_sales(env, env.business.id, start, end), key=lambda r: (-r[1], -r[2]))
    app = get_retail_operations(env.db, business_id=env.business.id, start_date=start, end_date=end)
    for i, row in enumerate(app.top_sellers_by_units[:n]):
        _check(env, f"top seller by units #{i + 1} ({row.name})", rows[i][1] if rows[i][0] == row.name else -1, row.units_sold)
    return [Fact(label=f"#{i + 1} by units", text=name, number=Decimal(units)) for i, (name, units, _r) in enumerate(rows[:n])]


@_resolver("top_sellers_revenue")
def _top_sellers_revenue(env: FactEnv, period: Any = "recent", n: int = 1) -> list[Fact]:
    start, end = local_dates(env, period)
    rows = sorted(_sql_product_sales(env, env.business.id, start, end), key=lambda r: (-r[2], -r[1]))
    return [Fact(label=f"#{i + 1} by revenue", text=name, number=rev) for i, (name, _u, rev) in enumerate(rows[:n])]


@_resolver("product_units")
def _product_units(env: FactEnv, product: str, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    units = {name: u for name, u, _r in _sql_product_sales(env, env.business.id, start, end)}.get(product, 0)
    return [Fact(label=f"units of {product}", number=Decimal(units), zero_ok=True)]


@_resolver("stock_on_hand")
def _stock_on_hand(env: FactEnv, product: str) -> list[Fact]:
    return [Fact(label=f"stock of {product}", number=Decimal(_sql_stock(env, product)))]


@_resolver("product_price")
def _product_price(env: FactEnv, product: str, which: str = "sell_price") -> list[Fact]:
    return [Fact(label=f"{which} of {product}", number=_money(_sql_product(env, product)[which]))]


@_resolver("dead_stock")
def _dead_stock(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    rows = get_retail_operations(env.db, business_id=env.business.id, start_date=start, end_date=end).dead_stock
    return [Fact(label="dead stock product", text=r.name) for r in rows[:3]]


@_resolver("most_urgent_stock")
def _most_urgent_stock(env: FactEnv) -> list[Fact]:
    rows = get_retail_operations(env.db, business_id=env.business.id).stock_cover
    return [Fact(label="product with the least stock cover", text=rows[0].name)]


@_resolver("sell_through")
def _sell_through(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    rate = get_retail_operations(env.db, business_id=env.business.id, start_date=start, end_date=end).sell_through_rate
    if rate is None:
        return []  # not computable for this data — the case then only checks ORLA doesn't invent one
    return [Fact(label="sell-through rate", number=rate, alternatives=((rate * 100).quantize(Decimal("0.1")), rate * 100))]


@_resolver("inventory_value")
def _inventory_value(env: FactEnv) -> list[Fact]:
    retail = get_retail_operations(env.db, business_id=env.business.id)
    return [Fact(label="inventory value at cost", number=retail.inventory_value.value_at_cost)]


@_resolver("workshop")
def _workshop(env: FactEnv, period: Any = "recent", what: str = "revenue", scope: str | None = None) -> list[Fact]:
    start, end = local_dates(env, period)
    count, revenue, labour = _sql_repairs(env, _business_ids(env, scope), start, end)
    app = get_workshop_performance(env.db, business_id=_scoped_business(env, scope).id, start_date=start, end_date=end)
    if scope != "all_branches":
        _check(env, f"repair count {period}", count, app.margin.repair_count)
        _check(env, f"repair revenue {period}", revenue, app.revenue.current)
    if what == "count":
        return [Fact(label="repair count", number=Decimal(count), zero_ok=True)]
    if what == "previous_revenue":
        p_start, p_end = previous_dates(start, end)
        _c, prev, _l = _sql_repairs(env, [env.business.id], p_start, p_end)
        _check(env, f"previous repair revenue {period}", prev, app.revenue.previous)
        return [Fact(label="previous-period repair revenue", number=prev, zero_ok=True)]
    if what == "margin_pct":
        return [Fact(label="workshop margin %", number=app.margin.gross_margin_pct)]
    if what == "average_ticket":
        return [Fact(label="average repair ticket", number=app.margin.average_ticket)]
    return [Fact(label="repair revenue", number=revenue, zero_ok=True)]


def _forecast_app(env: FactEnv, horizon_days: int = 7):
    return get_forecast(env.db, business_id=env.business.id, now=env.now, horizon_days=horizon_days)


@_resolver("forecast_revenue")
def _forecast_revenue(env: FactEnv, horizon_days: int = 7) -> list[Fact]:
    return [Fact(label=f"{horizon_days}-day revenue forecast", number=_forecast_app(env, horizon_days).revenue.result.total_point)]


@_resolver("reorder_top")
def _reorder_top(env: FactEnv, n: int = 1, horizon_days: int = 7, name_only: bool = False) -> list[Fact]:
    """The n most urgent products to reorder, each with its own suggested
    quantity (attribution — catches a garbled priority list)."""
    products = [p for p in _forecast_app(env, horizon_days).products if p.suggested_reorder_quantity > 0]
    return [
        Fact(label=f"reorder #{i + 1}", text=p.name, number=None if name_only else Decimal(p.suggested_reorder_quantity))
        for i, p in enumerate(products[:n])
    ]


@_resolver("top_recommendation")
def _top_recommendation(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    recs = get_findings(env.db, business_id=env.business.id, start_date=start, end_date=end).recommendations
    name = (recs[0].evidence or {}).get("name") if recs else None
    return [Fact(label="top recommendation's product", text=name)] if name else []


@_resolver("loss_making_product")
def _loss_making_product(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    findings = get_findings(env.db, business_id=env.business.id, start_date=start, end_date=end).findings
    losses = [f for f in findings if f.type == "product_selling_at_loss"]
    return [Fact(label="product selling at a loss", text=f.evidence["name"]) for f in losses[:1]]


def _latest_report(env: FactEnv) -> dict:
    reports = ReportRepository(env.db).list_active_for_business(env.business.id, now=env.now)
    if not reports:
        raise ValueError("No report available for the eval business")
    return reports[0].payload


@_resolver("latest_report")
def _latest_report_fact(env: FactEnv, what: str = "transactions") -> list[Fact]:
    payload = _latest_report(env)
    summary = payload.get("executive_summary") or {}
    if what == "revenue":
        revenue = (payload.get("financial_performance") or {}).get("revenue") or {}
        return [Fact(label="report revenue", number=Decimal(str(revenue["current"])))]
    if what == "average_sale":
        return [Fact(label="report average sale", number=Decimal(str(summary["average_sale"])))]
    if what == "low_stock_count":
        return [Fact(label="report low-stock count", number=Decimal(summary["low_stock_count"]))]
    return [Fact(label="report transactions", number=Decimal(summary["transactions"]))]


@_resolver("category_revenue")
def _category_revenue(env: FactEnv, period: Any = "recent", rank: int = 1, category: str | None = None) -> list[Fact]:
    start, end = local_dates(env, period)
    sales = _sql_category_sales(env, start, end)
    app = {r.category_name: r.revenue for r in get_category_breakdown(env.db, business_id=env.business.id, start_date=start, end_date=end).rows}
    for name, value in sales.items():
        _check(env, f"category revenue {name} {period}", value, app.get(name, 0))
    if category is not None:
        return [Fact(label=f"revenue of {category}", text=category, number=sales.get(category, Decimal("0.00")), zero_ok=True)]
    name, value = sorted(sales.items(), key=lambda kv: -kv[1])[rank - 1]
    return [Fact(label=f"category #{rank} by revenue", text=name, number=value)]


@_resolver("category_spend")
def _category_spend(env: FactEnv, period: Any = "recent", rank: int = 1, category: str | None = None) -> list[Fact]:
    start, end = local_dates(env, period)
    spend = _sql_category_spend(env, start, end)
    app = {r.category_name: r.expenses for r in get_category_breakdown(env.db, business_id=env.business.id, start_date=start, end_date=end).rows}
    for name, value in spend.items():
        _check(env, f"category spend {name} {period}", value, app.get(name, 0))
    if category is not None:
        return [Fact(label=f"spend on {category}", text=category, number=spend.get(category, Decimal("0.00")), zero_ok=True)]
    name, value = sorted(spend.items(), key=lambda kv: -kv[1])[rank - 1]
    return [Fact(label=f"category #{rank} by spend", text=name, number=value)]


@_resolver("category_spend_total")
def _category_spend_total(env: FactEnv, period: Any = "recent") -> list[Fact]:
    start, end = local_dates(env, period)
    total = sum(_sql_category_spend(env, start, end).values(), Decimal("0.00"))
    return [Fact(label="total spend on stock", number=total, zero_ok=True)]


@_resolver("purchase_order")
def _purchase_order(env: FactEnv, reference: str, n: int = 2) -> list[Fact]:
    rows = env.db.execute(
        text(
            "select p.name, m.quantity_delta from inventory_movements m join products p on p.id = m.product_id "
            "where m.business_id = :b and m.reason = 'purchase' and m.purchase_reference = :r "
            "order by m.quantity_delta desc, p.name"
        ),
        {"b": env.business.id, "r": reference},
    ).all()
    return [Fact(label=f"{reference} line", text=name, number=Decimal(qty)) for name, qty in rows[:n]]


@_resolver("last_purchase")
def _last_purchase(env: FactEnv, product: str) -> list[Fact]:
    row = env.db.execute(
        text(
            "select m.quantity_delta, m.event_date from inventory_movements m join products p on p.id = m.product_id "
            "where m.business_id = :b and m.reason = 'purchase' and p.name = :n order by m.event_date desc limit 1"
        ),
        {"b": env.business.id, "n": product},
    ).one()
    return [Fact(label=f"last delivery qty of {product}", number=Decimal(row[0]))]


@_resolver("most_recent_purchase")
def _most_recent_purchase(env: FactEnv) -> list[Fact]:
    """The latest delivery, named either by its reference or by any product
    on it — both identify it."""
    rows = env.db.execute(
        text(
            "select m.purchase_reference, p.name from inventory_movements m join products p on p.id = m.product_id "
            "where m.business_id = :b and m.reason = 'purchase' and m.event_date = ("
            "select max(event_date) from inventory_movements where business_id = :b and reason = 'purchase')"
        ),
        {"b": env.business.id},
    ).all()
    options = tuple(dict.fromkeys([r[0] for r in rows if r[0]] + [r[1] for r in rows]))
    return [Fact(label="most recent purchase", any_text=options)]


@_resolver("most_expensive_unit_purchase")
def _most_expensive_unit_purchase(env: FactEnv) -> list[Fact]:
    name, cost = env.db.execute(
        text(
            "select p.name, m.unit_cost from inventory_movements m join products p on p.id = m.product_id "
            "where m.business_id = :b and m.reason = 'purchase' and m.unit_cost is not null "
            "order by m.unit_cost desc limit 1"
        ),
        {"b": env.business.id},
    ).one()
    return [Fact(label="most expensive unit purchase", text=name, number=_money(cost))]


@_resolver("repair")
def _repair(env: FactEnv, reference: str, what: str = "price_charged") -> list[Fact]:
    row = env.db.execute(
        text(
            "select price_charged, labour_cost, description from production_events "
            "where business_id = :b and repair_reference = :r"
        ),
        {"b": env.business.id, "r": reference},
    ).one()
    if what == "description":
        return [Fact(label=f"{reference} description", text=row[2])]
    return [Fact(label=f"{reference} {what}", number=_money(row[0] if what == "price_charged" else row[1]))]


def resolve_fact(env: FactEnv, spec: dict) -> list[Fact]:
    params = {k: v for k, v in spec.items() if k not in ("fact", "times")}
    try:
        resolver = _RESOLVERS[spec["fact"]]
    except KeyError as exc:
        raise ValueError(f"Unknown fact {spec['fact']!r}") from exc
    facts = resolver(env, **params)
    if spec.get("times") is not None:
        # Only used for traps ("say revenue was double") — the scaled
        # figure is a number the answer must NOT state.
        multiplier = Decimal(str(spec["times"]))
        facts = [Fact(label=f"{f.label} x{spec['times']}", number=f.number * multiplier) for f in facts if f.number is not None]
    return facts


def known_fact_names() -> set[str]:
    return set(_RESOLVERS)
