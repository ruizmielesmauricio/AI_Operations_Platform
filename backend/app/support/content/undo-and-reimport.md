---
slug: undo-and-reimport
title: Undo an import and re-import a file
category: Uploading data
order: 16
summary: How to reverse an import you made by mistake, what undo changes, and how to import the file again correctly.
keywords: [undo, undo import, reverse, reversed, wrong file, mistake, delete import, remove upload, re-import, reimport, import again, upload again, duplicate data, imported twice, skipped rows, rows skipped]
version: 1
updated: 2026-11-13
---

## Undo an import

1. Open Upload data and find the file under "Past uploads".
2. Select "Undo import" under its result line.
3. Read the message "Undo this import?" and select "Undo import" to confirm.

Undo removes the sales, purchases, repairs or stock changes that this import created, and updates stock levels and low-stock alerts. The file then shows "Reversed" with the date and time. Undo cannot be undone itself: to get the data back, import the file again.

Undo works per import. If you imported several files, undo each one you want to remove.

## Re-import a file

1. Undo the import if the data is already in ORLA, so nothing is counted twice.
2. Upload the same file again with the right type under "What does this file contain?".
3. Confirm the column matches, correcting anything that was wrong, and select "Run import".

ORLA deletes an uploaded file once it has been imported, so you need to upload it again rather than re-running the old upload.

## Uploading a file that overlaps an earlier one

You do not need to undo anything to add newer data. If you upload a sales, purchases or repairs file that overlaps one you imported before, rows whose order, PO or job number was already imported are skipped with the reason "this reference was already used in an earlier import". This only works when the file has those reference numbers mapped.

Uploading the same stock count twice changes nothing: the stock is set to the counted quantities again.

## Skipped rows

After every import, ORLA shows "X of Y rows imported" and, if any were skipped, a list of plain reasons such as "no date found". Nothing is dropped silently. If many rows were skipped for the same reason, check the column mapping, then undo, re-upload and remap the file.

## Undo a PDF invoice import

A confirmed supplier invoice has its own "Undo import" button on the invoice page. See "Upload a supplier invoice PDF".
