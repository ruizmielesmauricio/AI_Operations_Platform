---
slug: upload-repairs
title: Upload your repairs
category: Uploading data
order: 14
summary: How shops with a repair or service workshop upload jobs, which columns ORLA needs, and where repair figures appear.
keywords: [repairs, repair, service, servicing, workshop, jobs, job sheet, labour, labour cost, price charged, job number, ticket, upload repairs, workshop performance, repairs option missing]
version: 1
updated: 2026-11-13
---

## Who can upload repairs

The "Repairs" upload type is available for business types that include repairs and servicing: Bike shop, Electronics & phone shop, Outdoor & sports shop, Jewellery & watches, and Other shop with a repair or service workshop. If you do not see "Repairs" under "What does this file contain?", your business type does not include a workshop. See "Create your business and choose your business type".

## How to upload repairs

1. Export your completed jobs from your workshop or job-card system.
2. Open Upload data and choose "Repairs".
3. Select your file and select "Upload".
4. Check the column matches and select "Confirm mapping".
5. Under "Past uploads", select "Run import".

## What a repairs file needs

ORLA needs:

- the repair date, and
- at least one of: a description of the work, the price charged to the customer, or your labour cost.

Optional columns:

- Price charged to the customer.
- Your labour cost for the job: what the job cost you, not what you charged.
- Tax/VAT amount: lets margin be calculated net of VAT.
- Job or invoice number: stops the same repair being imported twice.
- Store, branch or location: only if your export has it.

## Where repair figures appear

- The Workshop Performance section of the Dashboard and of your reports: repairs completed, revenue, average ticket and gross margin (labour only).
- The Repairs tab in Transactions, and the search box.
- Ask ORLA, for example "How did the workshop do last month?" or "How much did repair JOB-364 cost?".

Parts used on a repair are not tracked yet, so workshop margin is price charged minus labour cost and understates the true cost of a job.

## Why repair rows get skipped

- "no date found"
- "no description, price, or labour cost found"
- "this reference was already used in an earlier import"
