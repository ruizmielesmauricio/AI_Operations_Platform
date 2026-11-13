---
slug: reorder-rules
title: Reorder rules and low-stock alerts
category: Stock and suppliers
order: 40
summary: Use the Reorder rules page to see stock cover, set each product's reorder point, apply ORLA's recommendation and see what to restock.
keywords: [reorder rules, reorder point, threshold, low stock, low stock threshold, restock, recommended restock, stock cover, days of cover, orla recommends, set reorder point, change threshold, out of stock, stale, overstocked, products page, alert settings, lead time, safety buffer]
version: 1
updated: 2026-11-13
---

## What the page shows

Open Reorder rules from the top menu (the page is titled "Product Reorder Rules"). For each product you see:

- In stock: units available now.
- Sold last 30 days: how quickly it is moving.
- Stock cover: roughly how many days the current stock will last.
- Reorder point: when ORLA should warn you, in days of cover.
- ORLA recommends: a suggested reorder point.
- Setting: where the current value comes from: "Product custom" (you set it), "ORLA recommended" (you applied ORLA's recommendation), "Category default" (inherited from the product's category) or "System default".

Filter the list with "Category" and "Stock status" (Out of stock, Stale, Overstocked).

## Reorder points are in days

A reorder point is measured in days of stock cover, not units. With a reorder point of 7 days, ORLA warns you when a product has less than 7 days of stock left at its recent sales rate. Products without a custom value use 7 days.

## Change a reorder point

1. Select "Edit" on the product's row.
2. Type the number of days.
3. Select "Save reorder point".

If ORLA's recommendation differs from the current value, you can select "Use ORLA's Nd recommendation" instead. Only the owner or a manager can change reorder points; staff can view the page.

## How ORLA's recommendation is worked out

- If a supplier lead time is known for the product, the recommendation is that lead time plus a 3-day safety buffer.
- Otherwise it shows the general default of 7 days, marked "default".

Hover over the recommendation to see which applied. Supplier lead times cannot be entered on screen yet, so most products currently show the default.

## Recommended Restock

The "Recommended Restock" box lists products already below their reorder point, for example "Order 12 more units of Chain Lube." with the current stock and cover. If nothing is low it says "No products are below their reorder point."

## Low-stock alerts

Whenever stock data changes (after a sales, stock count or purchases import, or an undo), ORLA re-checks every affected product against its reorder point. Products below it appear under Active Alerts on the Dashboard and in a Stock notification. Alerts are only shown in ORLA, never emailed. See "Findings, recommendations and alerts".
