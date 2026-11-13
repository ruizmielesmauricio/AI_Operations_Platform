---
slug: upload-purchases
title: Upload your purchases
category: Uploading data
order: 13
summary: How to upload stock you bought in, which columns ORLA needs, and how purchases update stock, costs and suppliers.
keywords: [purchases, purchase orders, po, restock, restocking, replenishment, deliveries, goods received, buying, supplier, supplier invoice, unit cost, cost price, upload purchases, orders from suppliers]
version: 1
updated: 2026-11-13
---

## How to upload purchases

1. Export the stock you received from your POS, accounting system or spreadsheet.
2. Open Upload data and choose "Purchases / restocking" under "What does this file contain?".
3. Select your file and select "Upload".
4. Check the column matches and select "Confirm mapping".
5. Under "Past uploads", select "Run import".

If you only have a supplier invoice as a PDF, see "Upload a supplier invoice PDF".

## What a purchases file needs

ORLA needs:

- the date the stock was received,
- the product name or the SKU / product code (at least one of them), and
- the quantity received.

Optional columns:

- Unit cost: updates the product's recorded cost price, which improves margin figures.
- PO or invoice number: stops the same purchase being imported twice if you upload a file that overlaps an earlier one.
- Product category or department.
- Supplier or vendor name: matched to your existing suppliers by name, or created if new. This powers the spend breakdown on the Suppliers page.
- Store, branch or location: only if your export has it.

## What happens after the import

- Each purchase line adds the quantity received to the product's stock from its purchase date.
- If a unit cost is given, it becomes the product's recorded cost. If the same product appears at different costs in one file, the last cost is kept and every line's quantity is still added.
- Purchases appear on the Purchases tab of Transactions and in the Suppliers spend breakdown.

## Why purchase rows get skipped

- "no date found"
- "no product name or SKU found"
- "quantity must be greater than zero"
- "this reference was already used in an earlier import": the PO or invoice number was already imported.
