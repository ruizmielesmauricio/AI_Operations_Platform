---
slug: uploading-your-data
title: Uploading your data
category: Uploading data
order: 10
summary: Which files ORLA accepts, the four upload types, what to upload first, and how an upload goes from file to imported data.
keywords: [upload, uploads, import, file, export, csv, xls, xlsx, excel, spreadsheet, pos export, till export, what to upload, first upload, file format, template, file size, past uploads, upload status, last uploaded]
version: 1
updated: 2026-11-13
---

## Which files you can upload

Upload the export your till, POS, accounting system or spreadsheet already produces. ORLA accepts CSV, XLS and XLSX files, with the columns in any order and with any column names. There is no ORLA template to fill in. Title rows, blank rows and notes above the column names are fine. Files must be under 20 MB.

Supplier invoices in PDF are uploaded separately. See "Upload a supplier invoice PDF".

## The four upload types

When you upload a file, choose what it contains under "What does this file contain?":

- Sales transactions: what you sold. See "Upload your sales".
- Inventory / stock count: how many of each product you have now. See "Upload your stock count".
- Purchases / restocking: stock you bought in from suppliers. See "Upload your purchases".
- Repairs: repair and service jobs. Only shown for business types that include repairs. See "Upload your repairs".

## What to upload first

For the most accurate results, start with a full year of demand data and then add stock and replenishment history:

- Sales: the last 12 months.
- Service or workshop activity: the last 12 months, if you do repairs or servicing.
- Current stock: your latest stock-on-hand file.
- Purchases, orders or restocks: ideally the last 3 to 12 months.

## How an upload works

1. Open Upload data from the top menu. If you have more than one shop or branch, pick the right one under "Business".
2. Choose the upload type, select your file and select "Upload".
3. ORLA reads the file and matches its columns. Check the matches under "Confirm what each column means" and select "Confirm mapping". See "Match your columns".
4. Under "Past uploads", select "Run import" on the file.
5. ORLA shows how many rows were imported and, if any were skipped, why. Your dashboard, Reorder rules and alerts update straight away.

If ORLA recognises a file layout you have mapped before, it applies the saved mapping automatically and shows "Recognized this file from a previous upload — mapping applied automatically.", so you only need to select "Run import".

## Upload statuses

Under "Past uploads" each file shows a status:

- uploaded: the file is stored but its columns have not been confirmed yet. Select "Map columns".
- mapped: the columns are confirmed. Select "Run import", or "Remap" to change the mapping first.
- imported: the rows are in ORLA. The result line shows how many rows were imported and skipped, with an "Undo import" button.
- Reversed: the import was undone. See "Undo an import and re-import a file".

After a successful import ORLA deletes the uploaded file from storage and keeps only the imported data.

## How fresh is your data

At the top of Upload data, ORLA shows when each type was last uploaded, for example "Sales transactions: last uploaded 3 days ago". A line is highlighted when that type has never been uploaded or was last uploaded more than 7 days ago. ORLA also sends a Data & Uploads notification when your data starts going stale.

## Who can upload

Owners, managers and staff can all upload and import files. Uploads need an active subscription or free pilot access. If neither is active, ORLA shows "This shop's subscription isn't active, so uploads and imports are paused." See "Billing and your subscription".
