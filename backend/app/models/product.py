from sqlalchemy import DECIMAL, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class ProductCategory(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "product_categories"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Falls back to DEFAULT_LOW_STOCK_THRESHOLD_DAYS (app/analytics/findings.py)
    # when unset, and to a product-level override when that's set instead —
    # see resolve_low_stock_threshold. Stage C12, PR-9.3.
    low_stock_threshold_days: Mapped[object | None] = mapped_column(DECIMAL(6, 2), nullable=True)


class Product(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """The canonical sellable item. cost_price/sell_price are the current
    values; historical cost at time of sale is captured on SaleItem, not
    here, so margin on a past sale never drifts when a price changes.
    """

    __tablename__ = "products"

    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[object | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("product_categories.id"), nullable=True
    )
    cost_price: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    sell_price: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
    # Overrides the category-level threshold (and the global default) when
    # set. Stage C12, PR-9.3 — see resolve_low_stock_threshold.
    low_stock_threshold_days: Mapped[object | None] = mapped_column(DECIMAL(6, 2), nullable=True)
    # "manual" | "orla_recommended" | None — where the value above came
    # from, always set/cleared together with it (see
    # ProductRepository.update_low_stock_threshold_days). Powers the
    # Product Reorder Rules table's "Setting" column, distinguishing an
    # owner's own choice from an applied ORLA recommendation.
    low_stock_threshold_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
