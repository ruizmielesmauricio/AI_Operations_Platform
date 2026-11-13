---
slug: upload-stock-count
title: Upload your stock count
category: Uploading data
order: 12
summary: How to upload a stock count or stock-on-hand file, which columns ORLA needs, and how the count updates your stock levels.
keywords: [stock count, stock take, stocktake, inventory, inventory count, stock on hand, stock level, quantity on hand, upload stock, update stock, current stock, unit cost, count date, as of date]
version: 1
updated: 2026-11-13
---

## How to upload a stock count

1. Export your current stock list or stock-take from your till, POS or spreadsheet.
2. Open Upload data and choose "Inventory / stock count" under "What does this file contain?".
3. Select your file and select "Upload".
4. Check the column matches under "Confirm what each column means" and select "Confirm mapping".
5. Under "Past uploads", select "Run import".

## What a stock count file needs

ORLA needs:

- the product name or the SKU / product code (at least one of them), and
- the current quantity in stock.

Optional columns:

- Unit cost: sets or updates the product's recorded cost. This is how a shop that never uploads purchases can still get margin figures.
- Product category or department.
- Store, branch or location: only if your export has it.
- The date the count was taken: most exports do not have this. Leave it as "Not present in this file" and ORLA uses today's date. Only map it if your file states when the count was actually taken, for example an overnight export dated for the day before.

## What happens to your stock levels

A stock count is a snapshot. For each product in the file, ORLA sets the stock on hand to the counted quantity as of the count date, and records the difference as a stock adjustment. Products not in the file are left as they were. Sales and purchases dated after the count keep moving the stock level from there.

If the same product appears on more than one row, ORLA uses the last row and tells you so in the import summary.

## Why stock rows get skipped

- "no product name or SKU found"
- "no stock count found"
- "stock count can't be negative"

## After the import

Reorder rules, low-stock alerts and the stock sections of the dashboard update straight away. If products drop below their reorder point, you get a Stock notification. See "Reorder rules and low-stock alerts".
