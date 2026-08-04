from sqlalchemy import DECIMAL, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class ProductCategory(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "product_categories"

    name: Mapped[str] = mapped_column(String(255), nullable=False)


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
