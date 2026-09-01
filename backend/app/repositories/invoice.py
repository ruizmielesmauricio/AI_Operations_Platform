import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.invoice import InvoiceDraft, InvoiceDraftLine


class InvoiceDraftRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        business_id: uuid.UUID,
        storage_key: str,
        original_filename: str,
        uploaded_by: str,
        source_file_hash: str,
    ) -> InvoiceDraft:
        draft = InvoiceDraft(
            business_id=business_id,
            storage_key=storage_key,
            original_filename=original_filename,
            uploaded_by=uploaded_by,
            source_file_hash=source_file_hash,
            status="processing",
        )
        self.session.add(draft)
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def get_for_business(self, draft_id: uuid.UUID, business_id: uuid.UUID) -> InvoiceDraft | None:
        return self.session.scalar(
            select(InvoiceDraft).where(InvoiceDraft.id == draft_id, InvoiceDraft.business_id == business_id)
        )

    def list_for_business(self, business_id: uuid.UUID) -> list[InvoiceDraft]:
        return list(
            self.session.scalars(
                select(InvoiceDraft)
                .where(InvoiceDraft.business_id == business_id)
                .order_by(InvoiceDraft.created_at.desc())
            )
        )

    def find_by_source_file_hash(
        self, business_id: uuid.UUID, source_file_hash: str, *, exclude_id: uuid.UUID | None = None
    ) -> InvoiceDraft | None:
        """Exact-duplicate signal (spec §4a) — same PDF bytes re-uploaded.
        Matches any prior draft regardless of its own status (a failed or
        still-under-review draft's hash still counts — re-uploading the
        identical file while the first attempt is still sitting there is
        exactly the "retry must not create a duplicate draft" case).
        exclude_id matters here specifically (unlike the other duplicate
        signals below): a draft always trivially matches its OWN hash, so
        every caller checking an already-persisted draft against this
        signal must exclude itself, or every draft would appear to be its
        own "exact duplicate."
        """
        conditions = [InvoiceDraft.business_id == business_id, InvoiceDraft.source_file_hash == source_file_hash]
        if exclude_id is not None:
            conditions.append(InvoiceDraft.id != exclude_id)
        return self.session.scalar(select(InvoiceDraft).where(*conditions).order_by(InvoiceDraft.created_at.desc()))

    def find_confirmed_by_reference(
        self, business_id: uuid.UUID, *, supplier_id: uuid.UUID | None, invoice_reference: str
    ) -> InvoiceDraft | None:
        """Exact-duplicate signal (spec §4a) — same normalised supplier +
        invoice reference, already confirmed. Only ever checked against
        confirmed drafts: two independent, still-unconfirmed reviews of
        genuinely different invoices that happen to share a typo'd
        reference shouldn't block each other before either is real yet.
        """
        return self.session.scalar(
            select(InvoiceDraft).where(
                InvoiceDraft.business_id == business_id,
                InvoiceDraft.status == "confirmed",
                InvoiceDraft.supplier_id == supplier_id,
                InvoiceDraft.invoice_reference == invoice_reference,
            )
        )

    def find_plausible_duplicates(
        self, business_id: uuid.UUID, *, invoice_date, currency: str | None, grand_total
    ) -> list[InvoiceDraft]:
        """Looser duplicate signal (spec §4b) — same date + currency +
        grand total among confirmed drafts. A warning, never an auto-
        block (see app/invoices/duplicates.py)."""
        return list(
            self.session.scalars(
                select(InvoiceDraft).where(
                    InvoiceDraft.business_id == business_id,
                    InvoiceDraft.status == "confirmed",
                    InvoiceDraft.invoice_date == invoice_date,
                    InvoiceDraft.currency == currency,
                    InvoiceDraft.grand_total == grand_total,
                )
            )
        )

    def update_extraction(
        self,
        draft: InvoiceDraft,
        *,
        status: str,
        failure_reason: str | None,
        extracted_at: datetime | None,
        extracted_header: dict | None,
        header_issue_codes: list | None,
        supplier_id: uuid.UUID | None,
        supplier_name_input: str | None,
        invoice_reference: str | None,
        invoice_date,
        due_date,
        currency: str | None,
        subtotal,
        tax_total,
        discount_total,
        shipping_total,
        grand_total,
        duplicate_status: str,
        duplicate_of_draft_id: uuid.UUID | None,
    ) -> InvoiceDraft:
        draft.status = status
        draft.failure_reason = failure_reason
        draft.extracted_at = extracted_at
        draft.extracted_header = extracted_header
        draft.header_issue_codes = header_issue_codes
        draft.supplier_id = supplier_id
        draft.supplier_name_input = supplier_name_input
        draft.invoice_reference = invoice_reference
        draft.invoice_date = invoice_date
        draft.due_date = due_date
        draft.currency = currency
        draft.subtotal = subtotal
        draft.tax_total = tax_total
        draft.discount_total = discount_total
        draft.shipping_total = shipping_total
        draft.grand_total = grand_total
        draft.duplicate_status = duplicate_status
        draft.duplicate_of_draft_id = duplicate_of_draft_id
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def update_header_fields(self, draft: InvoiceDraft, **fields) -> InvoiceDraft:
        """Applies a review-screen correction to whichever header columns
        are passed — same "only touch what's given" convention as every
        other partial-update repository method in this codebase (e.g.
        UploadRepository doesn't exist for this shape, but see
        SupplierRepository.update)."""
        for key, value in fields.items():
            setattr(draft, key, value)
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def mark_confirmed(self, draft: InvoiceDraft, *, import_record_id: uuid.UUID) -> InvoiceDraft:
        draft.status = "confirmed"
        draft.import_record_id = import_record_id
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def mark_reversed(self, draft: InvoiceDraft, *, reversed_at: datetime) -> InvoiceDraft:
        draft.status = "reversed"
        draft.reversed_at = reversed_at
        self.session.commit()
        self.session.refresh(draft)
        return draft

    def delete(self, draft: InvoiceDraft) -> None:
        self.session.delete(draft)
        self.session.commit()

    def count_created_since(self, business_id: uuid.UUID, since: datetime) -> int:
        """Backs the per-business rate limit on invoice uploads (spec
        §5.5 — parsing runs inline in the request, so this is the only
        throttle point) — same "count rows since a cutoff" shape as
        AIRequestRepository's daily-cap check."""
        return len(
            list(
                self.session.scalars(
                    select(InvoiceDraft.id).where(
                        InvoiceDraft.business_id == business_id, InvoiceDraft.created_at >= since
                    )
                )
            )
        )


class InvoiceDraftLineRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, business_id: uuid.UUID, invoice_draft_id: uuid.UUID, **fields) -> InvoiceDraftLine:
        line = InvoiceDraftLine(business_id=business_id, invoice_draft_id=invoice_draft_id, **fields)
        self.session.add(line)
        self.session.flush()
        return line

    def list_for_draft(self, business_id: uuid.UUID, invoice_draft_id: uuid.UUID) -> list[InvoiceDraftLine]:
        return list(
            self.session.scalars(
                select(InvoiceDraftLine)
                .where(InvoiceDraftLine.business_id == business_id, InvoiceDraftLine.invoice_draft_id == invoice_draft_id)
                .order_by(InvoiceDraftLine.line_number)
            )
        )

    def get_for_draft(
        self, business_id: uuid.UUID, invoice_draft_id: uuid.UUID, line_id: uuid.UUID
    ) -> InvoiceDraftLine | None:
        return self.session.scalar(
            select(InvoiceDraftLine).where(
                InvoiceDraftLine.business_id == business_id,
                InvoiceDraftLine.invoice_draft_id == invoice_draft_id,
                InvoiceDraftLine.id == line_id,
            )
        )

    def update_fields(self, line: InvoiceDraftLine, **fields) -> InvoiceDraftLine:
        for key, value in fields.items():
            setattr(line, key, value)
        self.session.commit()
        self.session.refresh(line)
        return line

    def delete_for_draft(self, business_id: uuid.UUID, invoice_draft_id: uuid.UUID) -> None:
        """Used only when re-running extraction is ever needed — not
        called by the v1 flow (extraction runs exactly once per draft),
        kept for symmetry with ImportRecordRepository.delete_for_upload
        and as the natural hook if reprocessing is added later."""
        for line in self.list_for_draft(business_id, invoice_draft_id):
            self.session.delete(line)
        self.session.flush()
