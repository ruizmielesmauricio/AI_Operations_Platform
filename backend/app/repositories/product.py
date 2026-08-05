import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductCategory


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

    def update_cost_price(
        self, *, business_id: uuid.UUID, product_id: uuid.UUID, cost_price: Decimal
    ) -> Product | None:
        """First update path on Product ever — written by the "purchases"
        entity type (app/imports/importer.py::_write_purchases), which is
        explicitly the natural place to learn/refresh a product's current
        cost. Unconditionally overwrites (cost_price has no other refresh
        path, and the latest purchase price should win). Flush only —
        app/imports/importer.py owns the single commit.
        """
        product = self.session.scalar(
            select(Product).where(Product.id == product_id, Product.business_id == business_id)
        )
        if product is None:
            return None
        product.cost_price = cost_price
        self.session.flush()
        return product


class ProductCategoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_business(self, business_id: uuid.UUID) -> list[ProductCategory]:
        # One query for the whole catalogue's categories, same reasoning as
        # ProductRepository.list_for_business — Stage C12's threshold
        # resolution needs every category's low_stock_threshold_days at
        # once, not per-product.
        return list(
            self.session.scalars(select(ProductCategory).where(ProductCategory.business_id == business_id))
        )
