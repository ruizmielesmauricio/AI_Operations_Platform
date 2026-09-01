"""Product/supplier/category candidate resolution for one invoice draft's
lines — reuses app/imports/importer.py's ProductMatcher/SupplierMatcher/
CategoryMatcher UNCHANGED (already exactly "strong identifier first,
never guess on a weak match," spec §3.4's requirement verbatim, and
already covered by that module's own tests). The only new logic here is
layering a supplier-SKU lookup in front of ProductMatcher, since a
supplier's own per-product code (spec: "exact supplier SKU/product SKU")
is a stronger identifier than our own Product.sku for a document THAT
supplier issued.
"""

import uuid

from app.imports.importer import CategoryMatcher, ProductMatch, ProductMatcher, SupplierMatcher
from app.repositories.supplier import SupplierRepository


def resolve_product_for_line(
    *,
    supplier_repo: SupplierRepository,
    business_id: uuid.UUID,
    supplier_id: uuid.UUID | None,
    supplier_sku: str | None,
    description: str | None,
    product_matcher: ProductMatcher,
) -> ProductMatch:
    """Resolution order: (1) this supplier's own recorded SKU for a
    product (ProductSupplier.supplier_sku — the strongest signal, since
    it's specific to this exact supplier relationship), (2) our own
    Product.sku (in case the printed code happens to match it), (3) a
    normalised name match. Never falls back further than that — an
    unmatched line proposes "create" (never auto-applied; the review
    screen requires explicit confirmation, spec §3.5) rather than
    guessing at a weak candidate.
    """
    if supplier_id is not None and supplier_sku:
        product_id = supplier_repo.find_product_id_by_supplier_sku(
            business_id, supplier_id=supplier_id, supplier_sku=supplier_sku
        )
        if product_id is not None:
            return ProductMatch(action="existing", product_id=product_id)
    return product_matcher.resolve(sku=supplier_sku, product_name=description)


def default_resolution_action(match: ProductMatch) -> str:
    """The review screen's starting proposal, not a final decision (the
    user always sees and can change it before confirm — spec §3.5). Only
    ever defaults to "match_existing" for a genuinely unambiguous
    identifier match with no name conflict; every weaker outcome starts
    "unresolved" so a human consciously picks match/create/exclude,
    matching the spec's "never silently choose a weak/ambiguous match."
    """
    if match.action == "existing" and not match.name_mismatch:
        return "match_existing"
    return "unresolved"


__all__ = ["CategoryMatcher", "ProductMatch", "ProductMatcher", "SupplierMatcher", "resolve_product_for_line", "default_resolution_action"]
