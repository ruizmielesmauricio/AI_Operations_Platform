import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product


class ProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_business(self, business_id: uuid.UUID) -> list[Product]:
        # Loaded once per import (app/imports/importer.py builds an
        # in-memory sku/name index from this) rather than queried per row —
        # avoids N+1 queries across a file that can have thousands of rows.
        return list(self.session.scalars(select(Product).where(Product.business_id == business_id)))

    def create(
        self,
        *,
        business_id: uuid.UUID,
        sku: str | None,
        name: str,
        cost_price: Decimal | None,
        sell_price: Decimal | None,
    ) -> Product:
        # Flush only — app/imports/importer.py owns the single commit for
        # the whole import write path (billing-style transaction convention).
        product = Product(
            business_id=business_id,
            sku=sku,
            name=name,
            cost_price=cost_price,
            sell_price=sell_price,
        )
        self.session.add(product)
        self.session.flush()
        return product
