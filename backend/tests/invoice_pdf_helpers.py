"""Generates realistic (synthetic, non-sensitive) supplier-invoice PDF
fixtures for app/invoices/ tests, using reportlab (already a real
dependency of this backend) — no external/real invoice documents
involved anywhere. Kept as one shared helper module (mirrors tests/
auth_helpers.py's role) rather than duplicated per test file.
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_invoice_pdf(
    *,
    supplier_name: str = "Acme Bike Parts Ltd",
    invoice_reference: str = "INV-2024-0456",
    invoice_date: str = "15/03/2026",
    due_date: str = "14/04/2026",
    lines: list[tuple[str, str, str, str, str]] | None = None,  # (sku, description, qty, unit_price, amount)
    subtotal: str = "220.00",
    tax_total: str = "50.60",
    grand_total: str = "270.60",
    header_row: tuple[str, ...] = ("SKU", "Description", "Qty", "Unit Price", "Amount"),
) -> bytes:
    """A clean, text-native, single-table invoice — the common case."""
    lines = lines or [
        ("TYR-001", "Road Tyre 700x25c", "10", "15.00", "150.00"),
        ("TUB-002", "Inner Tube 700c", "20", "3.50", "70.00"),
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(supplier_name, styles["Title"]),
        Paragraph(f"Invoice Number: {invoice_reference}", styles["Normal"]),
        Paragraph(f"Invoice Date: {invoice_date}", styles["Normal"]),
        Paragraph(f"Due Date: {due_date}", styles["Normal"]),
        Spacer(1, 12),
    ]
    data = [list(header_row), *[list(row) for row in lines]]
    table = Table(data)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    elements.append(table)
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Subtotal: {subtotal}", styles["Normal"]))
    elements.append(Paragraph(f"VAT: {tax_total}", styles["Normal"]))
    elements.append(Paragraph(f"Grand Total: {grand_total}", styles["Normal"]))
    doc.build(elements)
    return buf.getvalue()


def build_no_table_pdf() -> bytes:
    """Text-native but with no ruled table at all — the "line items not
    detected" honest-limitation path (module docstring, app/invoices/
    extraction.py)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 750, "Acme Bike Parts Ltd")
    c.drawString(72, 730, "Invoice Number: INV-9001")
    c.drawString(72, 710, "Invoice Date: 01/02/2026")
    c.drawString(72, 690, "1 x Road Tyre 700x25c - 15.00 each")
    c.drawString(72, 670, "Grand Total: 15.00")
    c.save()
    return buf.getvalue()


def build_encrypted_pdf(password: str = "secret123") -> bytes:
    buf = io.BytesIO()
    enc = StandardEncryption(password, ownerPassword="owner-secret", canPrint=1)
    c = canvas.Canvas(buf, pagesize=A4, encrypt=enc)
    c.drawString(72, 750, "Invoice INV-0001")
    c.save()
    return buf.getvalue()


def build_corrupt_pdf() -> bytes:
    full = build_invoice_pdf()
    return full[: len(full) // 2]


def build_image_only_pdf() -> bytes:
    """No text operators at all — a real scanned/image-only PDF stand-in
    (no OCR exists in v1 — this must be rejected honestly, never
    guessed). A filled rectangle has no extractable text whatsoever."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.rect(50 * mm, 50 * mm, 100 * mm, 200 * mm, fill=1, stroke=0)
    c.save()
    return buf.getvalue()


def build_many_pages_pdf(page_count: int) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i in range(page_count):
        c.drawString(72, 750, f"Page {i + 1} of {page_count} -- Acme Bike Parts Ltd supplier invoice continuation sheet")
        c.showPage()
    c.save()
    return buf.getvalue()


def not_a_pdf_bytes() -> bytes:
    return b"this is definitely not a pdf file, just plain text bytes"
