---
slug: upload-sales
title: Upload your sales
category: Uploading data
order: 11
summary: The columns ORLA looks for in a sales export, how returns, VAT and order numbers are handled, and why rows get skipped.
keywords: [sales, sales export, sales file, transactions, till, pos, receipts, orders, revenue, returns, refunds, negative quantity, vat, tax, order number, receipt number, cost price, duplicate sales, upload sales]
version: 1
updated: 2026-11-13
---

## What a sales file needs

Choose "Sales transactions" under "What does this file contain?". ORLA needs at least:

- the sale date, and
- a price: either the price per unit or the final total for the line.

The product name and quantity sold are also matched when your file has them. Everything else is optional.

## Optional sales columns

- SKU or product code: matches sales to the right product even if names differ slightly.
- Price per unit: what the customer paid for one item, before tax if your file has a separate tax column.
- Final total for the line: the amount actually charged, for example €36.90 for 3 items at €10 plus €6.90 VAT. If you leave it out, ORLA works it out as price × quantity.
- Your cost for this item: what you paid your supplier, not the price you charged. This is what makes gross margin possible.
- Tax/VAT amount: lets ORLA calculate margin net of VAT.
- Order or receipt number: groups several rows into one sale and stops the same order being imported twice.
- Product category or department: matched to your existing categories by name, or created if new.
- Store, branch or location: only map this if your export has it. See "Match your columns".

## Returns and refunds

A row with a negative quantity is imported as a return. Returns are taken off revenue, so the dashboard shows revenue after returns and tells you how much was returned. A row with a quantity of exactly zero is skipped.

## Dates and money formats

ORLA reads common date formats, including 31/12/2026, 2026-12-31, 31-12-2026, 31.12.2026 and 31 December 2026. Where a date could be read either way, the day-first (Irish and European) reading is used. Currency symbols, thousand separators and decimal commas are handled for you.

## Why sales rows get skipped

After an import, ORLA lists every skipped row with a plain reason, for example:

- "no date found"
- "no price found"
- "quantity couldn't be read"
- "quantity can't be zero"
- "this reference was already used in an earlier import": the order number was already imported, so the row was skipped rather than counting the sale twice.

You may also see notes that are not errors, such as a line total that did not match price × quantity. ORLA uses the file's own total in that case (for example when it includes VAT or a discount); no action is needed.

## No cost prices in your sales file

If your sales export has no cost column, ORLA uses the product's cost from your stock count or purchases uploads instead. Until a cost is known, margin is shown as an estimate and products without a cost are left out of margin rankings.
