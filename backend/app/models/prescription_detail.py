from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantScopedMixin, TimestampMixin


class PrescriptionDetail(Base, PKMixin, TenantScopedMixin, TimestampMixin):
    """Pharmacy business-template extension (ADR-023, PD-010) — a thin table
    hanging off sale_items, per 06_Database_Design.md's three-layer model.
    Not bolted onto sale_items itself; not a canonical table. One row per
    sale_item: a multi-drug prescription is represented as several
    sale_items sharing the same prescription_number, not one row covering
    several lines.

    PRIVACY / GDPR NOTE: prescription data is health data, a GDPR Article 9
    special category. This table is deliberately minimal — no patient name,
    date of birth, or health-condition/diagnosis fields — per Company
    Constitution Principle 7 ("Customer Data Is Sacred"). Minimality alone
    does not resolve GDPR compliance: linking this table to
    sale_items -> sales -> customers can still make a customer identifiable
    as a prescription holder. Full legal basis, DPIA, and retention/deletion
    policy are OPEN — tracked as Q-053 in 17_Open_Questions.md, not decided
    by this schema.
    """

    __tablename__ = "prescription_details"

    sale_item_id: Mapped[object] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sale_items.id"), nullable=False, unique=True, index=True
    )
    prescription_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prescribing_doctor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    controlled_substance_schedule: Mapped[str | None] = mapped_column(String(32), nullable=True)
