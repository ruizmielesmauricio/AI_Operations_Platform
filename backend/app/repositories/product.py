import re
import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductCategory
from app.text_normalize import normalize_dashes, normalize_dashes_column

_SEARCH_LIMIT = 5
# Matches a trailing "(...)" annotation on an otherwise plain string, e.g.
# "WorkshopPro Lubricant Plus (SKU-00175)" -> ("WorkshopPro Lubricant
# Plus", "SKU-00175"). This is exactly the label format ORLA's own
# many-match disambiguation messages use (app/application/lookups.py's
# match_labels: f"{name} ({sku})") — a real bug, found live: a user
# copying one of those labels back verbatim got zero matches, since the
# literal "(SKU-00175)" text is never part of the stored product name.
_TRAILING_PAREN_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")


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
        category_id: uuid.UUID | None = None,
    ) -> Product:
        # Flush only — app/imports/importer.py owns the single commit for
        # the whole import write path (billing-style transaction convention).
        product = Product(
            business_id=business_id,
            sku=sku,
            name=name,
            cost_price=cost_price,
            sell_price=sell_price,
            category_id=category_id,
        )
        self.session.add(product)
        self.session.flush()
        return product

    def search_by_name_or_sku(self, business_id: uuid.UUID, query: str, *, limit: int = _SEARCH_LIMIT) -> list[Product]:
        """Backs ORLA's product_lookup chat intent (app/ai/service.py) —
        the free-text search term is only ever used here, as a
        parameterized ILIKE/exact-match value, never as raw SQL,
        regardless of what a model extracted it as. Case-insensitive
        substring match on name; exact, normalized match on sku (mirrors
        app/imports/importer.py::normalize_sku's case/whitespace
        handling, not a substring match — a SKU is an identifier, a
        partial match on one is usually noise, not a real hit). Capped at
        `limit` so a broad query (e.g. a single common word) can't blow
        up the chat context — the caller (app/ai/service.py) treats
        "more results than fit" the same as any other multi-match case,
        asking the user to narrow down rather than silently picking one.

        Also tries a trailing "(SKU)" annotation split from the rest of
        the query (see _TRAILING_PAREN_RE) — a query like "WorkshopPro
        Lubricant Plus (SKU-00175)" is neither a substring of the stored
        name nor an exact match on the sku as one whole string, so
        without this it silently returns zero matches for exactly the
        label format this repository's own caller hands back to a user.

        The name comparison also normalizes dash/hyphen-like Unicode
        variants on both sides (see app/text_normalize.py) — live-
        reproduced real bug: "E‑Motion Trail 500" (a non-breaking hyphen
        from a real customer's own input) found zero matches against the
        stored "E-Motion Trail 500" (a plain ASCII hyphen), even though
        it's the same product.
        """
        query = normalize_dashes(query.strip())
        normalized_sku = query.upper()
        normalized_name = normalize_dashes_column(Product.name)
        conditions = [
            func.lower(normalized_name).like(f"%{query.lower()}%"),
            func.upper(Product.sku) == normalized_sku,
        ]
        paren_match = _TRAILING_PAREN_RE.match(query)
        if paren_match:
            name_part, sku_part = paren_match.group(1).strip(), paren_match.group(2).strip()
            if name_part:
                conditions.append(func.lower(normalized_name).like(f"%{name_part.lower()}%"))
            if sku_part:
                conditions.append(func.upper(Product.sku) == sku_part.upper())

        return list(
            self.session.scalars(
                select(Product)
                .where(Product.business_id == business_id, or_(*conditions))
                .limit(limit)
            )
        )

    def update_cost_price(
        self, *, business_id: uuid.UUID, product_id: uuid.UUID, cost_price: Decimal
    ) -> Product | None:
        """First update path on Product ever — originally written by the
        "purchases" entity type (app/imports/importer.py::write_purchases_batch),
        the natural place to learn/refresh a product's current cost; also
        used by "inventory" (::_write_inventory) for shops that only ever
        do stock counts and never a separate purchases export. Unconditionally
        overwrites (cost_price has no snapshot history, so the latest
        recorded price wins regardless of which entity type supplied it).
        Flush only — app/imports/importer.py owns the single commit.
        """
        product = self.session.scalar(
            select(Product).where(Product.id == product_id, Product.business_id == business_id)
        )
        if product is None:
            return None
        product.cost_price = cost_price
        self.session.flush()
        return product

    def update_sell_price(
        self, *, business_id: uuid.UUID, product_id: uuid.UUID, sell_price: Decimal
    ) -> Product | None:
        """Real bug, found live via the category-breakdown feature's
        "stock value at sell price" figure against a real business: every
        one of 180 real products had sell_price=NULL, because it was only
        ever set once, at product-creation time in _write_sales (mirrors
        update_cost_price's own history — cost_price had the identical
        gap until v1.11 gave it this same kind of update path). A product
        first created via "purchases"/"inventory" (sell_price=None, no
        price concept in those rows) never gets a sell_price at all once
        it's later actually sold, and even a sales-created product's
        price never reflects a later real price change. Unconditionally
        overwrites, same "latest wins" semantics as update_cost_price —
        called from _write_sales on every existing-product sighting.
        Flush only — app/imports/importer.py owns the single commit.
        """
        product = self.session.scalar(
            select(Product).where(Product.id == product_id, Product.business_id == business_id)
        )
        if product is None:
            return None
        product.sell_price = sell_price
        self.session.flush()
        return product

    def update_category(
        self, *, business_id: uuid.UUID, product_id: uuid.UUID, category_id: uuid.UUID | None
    ) -> Product | None:
        """Mirrors update_cost_price's exact "latest wins" semantics:
        unconditionally overwrites whenever a later row for an existing
        product carries a mapped category — a category has no snapshot
        history any more than cost_price does, so the most recently
        imported value is treated as current truth. Flush only —
        app/imports/importer.py owns the single commit."""
        product = self.session.scalar(
            select(Product).where(Product.id == product_id, Product.business_id == business_id)
        )
        if product is None:
            return None
        product.category_id = category_id
        self.session.flush()
        return product

    def get_for_business(self, business_id: uuid.UUID, product_id: uuid.UUID) -> Product | None:
        return self.session.scalar(
            select(Product).where(Product.id == product_id, Product.business_id == business_id)
        )

    def update_low_stock_threshold_days(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        threshold_days: Decimal | None,
        source: str | None = None,
    ) -> Product | None:
        """The first write path for this column since it was added at
        Stage C12 (PR-9.3) — everything before this round could only read
        it. None clears the override back to "inherit from category/
        default", same "absent means fall through" semantics
        resolve_low_stock_threshold already has — `source` is always
        cleared to None alongside it (the caller isn't required to pass
        one explicitly when clearing; a non-None `threshold_days` with no
        `source` would be a caller bug, not a state this method invents
        a default for)."""
        product = self.get_for_business(business_id, product_id)
        if product is None:
            return None
        product.low_stock_threshold_days = threshold_days
        product.low_stock_threshold_source = source if threshold_days is not None else None
        self.session.flush()
        return product


class ProductCategoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_business(self, business_id: uuid.UUID) -> list[ProductCategory]:
        # One query for the whole catalogue's categories, same reasoning as
        # ProductRepository.list_for_business — Stage C12's threshold
        # resolution needs every category's low_stock_threshold_days at
        # once, not per-product. Also backs GET /businesses/{id}/
        # product-categories (dashboard filter dropdown population) and
        # app/imports/importer.py's per-import CategoryMatcher.
        return list(
            self.session.scalars(select(ProductCategory).where(ProductCategory.business_id == business_id))
        )

    def create(self, *, business_id: uuid.UUID, name: str) -> ProductCategory:
        # Flush only — app/imports/importer.py owns the single commit.
        # No create/edit UI exists for categories yet (same "no product-
        # management UI" gap already flagged as of Stage C12) — every
        # category today is created organically via the importer's
        # CategoryMatcher resolving an imported "category" column's text,
        # match-or-create by normalized name.
        category = ProductCategory(business_id=business_id, name=name)
        self.session.add(category)
        self.session.flush()
        return category

    def get_for_business(self, business_id: uuid.UUID, category_id: uuid.UUID) -> ProductCategory | None:
        return self.session.scalar(
            select(ProductCategory).where(ProductCategory.id == category_id, ProductCategory.business_id == business_id)
        )

    def update_low_stock_threshold_days(
        self, *, business_id: uuid.UUID, category_id: uuid.UUID, threshold_days: Decimal | None
    ) -> ProductCategory | None:
        category = self.get_for_business(business_id, category_id)
        if category is None:
            return None
        category.low_stock_threshold_days = threshold_days
        self.session.flush()
        return category
