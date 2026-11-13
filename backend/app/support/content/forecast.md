---
slug: forecast
title: The forecast
category: Dashboard and insights
order: 23
summary: How ORLA projects your revenue and product demand for the next 7, 14 or 30 days, how much history it needs, and how to read the suggested reorder.
keywords: [forecast, forecasting, projection, predict, prediction, expected revenue, demand, next week, next month, products to watch, suggested reorder, reorder quantity, how much to order, not enough history, confidence range, shaded range, weather]
version: 1
updated: 2026-11-13
---

## What the forecast shows

The Forecast section of the Dashboard has two parts:

- Revenue: "Expected revenue, next N days", with a line chart. The shaded range shows how much your sales have typically varied.
- Products to watch: for each product, its current stock, forecast demand, the cover left and a suggested reorder.

Choose 7 days, 14 days or 30 days at the top of the section. Reports include the same forecast under "Forecast & Future Outlook" and "Purchasing Recommendations".

## How it is calculated

The forecast is not AI. It is a plain projection from your own sales history:

- With 21 days of history or more, ORLA uses your average for each day of the week, so a busy Saturday is forecast as a Saturday.
- With 14 to 20 days of history, it uses a plain recent daily average.
- It looks back at most 90 days, so the forecast reflects recent trading.

The note under the figure says how many days of history were used and which method.

## Not enough history

With less than 14 days of sales, ORLA does not forecast at all, rather than showing an unreliable number. You see "Not enough sales history yet to forecast revenue — check back once you have at least two weeks of data." Products without enough history are left out of "Products to watch" and counted in a note under the table.

## The suggested reorder

Suggested reorder is the upper estimate of forecast demand minus the stock you have now. Treat it as a number to sanity-check, not a purchase order: it does not know your supplier's delivery time or how much safety stock you want to keep.

## Asking ORLA about the forecast

You can ask, for example, "What should I reorder for the next two weeks?" or "What will my revenue be next month?". ORLA answers from the same forecast and can list products in order of priority. You can also ask "Will the weather affect sales this week?" for weather-linked patterns from your own history.
