from sqlalchemy import DECIMAL, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class Return(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Feeds the Financial Performance domain's Returns & Warranty
    treatment (02_Operational_Domains.md).
    """

    __tablename__ = "returns"

    sale_item_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sale_items.id"), nullable=False, index=True
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    refund_amount: Mapped[object | None] = mapped_column(DECIMAL(12, 2), nullable=True)
