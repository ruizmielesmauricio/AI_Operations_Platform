"""PDF supplier-invoice ingestion: invoice_drafts + invoice_draft_lines

Revision ID: c8f2a5e1b9d3
Revises: b3e6f9c1d5a2
Create Date: 2026-09-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f2a5e1b9d3'
down_revision: Union[str, None] = 'b3e6f9c1d5a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A durable draft/review record for one uploaded supplier-invoice PDF
    # -- see app/models/invoice.py::InvoiceDraft for the full design
    # rationale. Self-referencing FK (duplicate_of_draft_id) is declared
    # nullable with no ondelete cascade, matching this schema's existing
    # convention (no business_id FK anywhere cascades either).
    op.create_table(
        'invoice_drafts',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('business_id', sa.Uuid(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False, index=True),
        sa.Column('storage_key', sa.String(length=512), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('uploaded_by', sa.String(length=64), nullable=False),
        sa.Column('source_file_hash', sa.String(length=64), nullable=False, index=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='processing'),
        sa.Column('failure_reason', sa.String(length=64), nullable=True),
        sa.Column('parser_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('extracted_header', sa.JSON(), nullable=True),
        sa.Column('header_issue_codes', sa.JSON(), nullable=True),
        sa.Column('supplier_id', sa.Uuid(as_uuid=True), sa.ForeignKey('suppliers.id'), nullable=True),
        sa.Column('supplier_name_input', sa.String(length=255), nullable=True),
        sa.Column('invoice_reference', sa.String(length=128), nullable=True),
        sa.Column('invoice_date', sa.Date(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('tax_total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('discount_total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('shipping_total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('grand_total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('duplicate_status', sa.String(length=16), nullable=False, server_default='none'),
        sa.Column('duplicate_of_draft_id', sa.Uuid(as_uuid=True), sa.ForeignKey('invoice_drafts.id'), nullable=True),
        sa.Column('import_record_id', sa.Uuid(as_uuid=True), sa.ForeignKey('import_records.id'), nullable=True),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'invoice_draft_lines',
        sa.Column('id', sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column('business_id', sa.Uuid(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False, index=True),
        sa.Column('invoice_draft_id', sa.Uuid(as_uuid=True), sa.ForeignKey('invoice_drafts.id'), nullable=False, index=True),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('extracted_fields', sa.JSON(), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('supplier_sku', sa.String(length=128), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('unit', sa.String(length=32), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column('line_total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('tax_rate', sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column('tax_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('discount_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('resolution_action', sa.String(length=16), nullable=False, server_default='unresolved'),
        sa.Column('matched_product_id', sa.Uuid(as_uuid=True), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('proposed_name', sa.String(length=255), nullable=True),
        sa.Column('proposed_sku', sa.String(length=128), nullable=True),
        sa.Column('issue_code', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('invoice_draft_lines')
    op.drop_table('invoice_drafts')
