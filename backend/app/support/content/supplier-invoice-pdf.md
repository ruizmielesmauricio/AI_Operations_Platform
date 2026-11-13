---
slug: supplier-invoice-pdf
title: Upload a supplier invoice PDF
category: Uploading data
order: 17
summary: Turn a supplier's PDF invoice into purchase records by reviewing what ORLA read, matching each line to a product, and confirming.
keywords: [invoice, invoices, pdf, supplier invoice, pdf invoice, scan, scanned, review invoice, needs review, line items, match product, create product, exclude line, duplicate invoice, password protected, could not be read, confirm import, discard invoice]
version: 1
updated: 2026-11-13
---

## When to use it

Use this when you do not have a CSV or Excel purchases export, only the invoice your supplier sent as a PDF. Nothing is added to your stock or purchase records until you review the invoice and confirm it.

## Upload an invoice

1. Open Upload data and go to the "Invoice PDF" section.
2. Under "Supplier invoice (PDF)" select the file, then select "Upload invoice".
3. ORLA reads the invoice and opens the review page.

PDFs must be under 20 MB and at most 30 pages. You can upload up to 20 invoices per hour for each business. Uploaded invoices are listed in the "Invoice PDF" section with their status: Needs review, Confirmed, Could not be read or Undone. Select "Review", "View" or "Details" to open one.

## Review the invoice details

The review page shows the original PDF next to what ORLA read. Under "Invoice details" check the Supplier, Invoice reference, Invoice date, Due date, Currency and the totals, correct anything that is wrong and select "Save changes". The invoice date is required before you can confirm.

For the supplier, pick an existing supplier, type a new supplier name, or leave it blank to record "Unknown supplier".

## Review the line items

Each line under "Line items" needs a decision:

- Match existing product: select "Choose product" and search by name or SKU.
- Create new product: type the new product's name.
- Exclude this line: for lines that are not stock, such as delivery charges.

Lines marked "Not resolved yet" or "No product selected" must be fixed before you can confirm. A warning in the last column tells you if something on that line needs checking.

## Confirm the import

Under "Confirm import" ORLA shows what will happen: how many products will be matched, how many new products created and how many lines skipped. Select "Confirm import" and confirm. You then see "Imported successfully." with a link to the Purchases tab of Transactions.

## Duplicates

- If the invoice is an exact copy of one already imported, ORLA blocks it: "This looks like an exact duplicate of an invoice already imported."
- If it only looks similar (same date, currency and total), ORLA warns you. If it really is a different invoice, tick "I've checked — this is a genuinely different invoice, import it anyway".

## Undo or discard

- Before confirming, you can discard the invoice. The uploaded file and everything read from it are deleted.
- After confirming, select "Undo import" on the invoice page to reverse the purchase records and stock changes. Products or suppliers it created are kept.

## Invoices ORLA cannot read

- "This PDF is password-protected. Remove the password and re-upload it."
- "This looks like a scanned or image-only PDF — we can't read text from it yet." ORLA reads text-based PDFs only. Use a CSV or Excel export instead.
- "This file couldn't be read as a PDF — it may be damaged or incomplete."
- "This PDF has too many pages to process."

If ORLA cannot find a line-item table in the PDF, the invoice cannot be imported through this screen yet; use a CSV or Excel export, or contact ORLA support.
