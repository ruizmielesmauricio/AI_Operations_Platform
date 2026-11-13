---
slug: column-mapping
title: Match your columns (column mapping and remap)
category: Uploading data
order: 15
summary: How ORLA matches your file's columns, how to fix a wrong match, pick the header row, use Remap, and handle the more-than-one-location warning.
keywords: [mapping, map columns, column mapping, match columns, confirm mapping, remap, wrong column, header row, which row is the header, not present in this file, double check, saved mapping, location warning, more than one location, multiple locations, unused columns]
version: 1
updated: 2026-11-13
---

## How matching works

After you upload a file, ORLA reads the column names and some example values and suggests which column means what. You see the screen "Confirm what each column means". Each question, such as "Which column is the sale date?", has a drop-down list of your file's columns with a few example values beside the one chosen.

- If a match looks wrong, pick the right column from the list.
- If your file does not have that information, choose "Not present in this file".
- "Double check this one — we're not fully confident in this match." means ORLA is less sure; check the example values.
- Columns ORLA does not need are listed under "Not used".

When everything looks right, select "Confirm mapping". ORLA saves the mapping and shows "Mapping saved." Then select "Run import" under "Past uploads".

For sales and repairs, the screen reminds you that prices split into two sides: what the customer paid (price, total, VAT) and what you paid (cost price or labour cost). Make sure they are not swapped.

## If ORLA asks which row is the header

If ORLA cannot find the row with your column names, it shows "Which row is the header?" with the first rows of your file. Select "Use this row" next to the row that contains the column names, for example "Date", "Item", "Price".

## Saved mappings

Your confirmed mapping is saved for that file layout. The next time you upload a file from the same system with the same columns, ORLA applies it automatically and shows "Recognized this file from a previous upload — mapping applied automatically." You only need to select "Run import".

## Fix a mapping before importing (Remap)

If you confirmed a mapping but have not run the import yet, select "Remap" next to the file under "Past uploads". This reopens the matching screen so you can change it.

You cannot remap a file that has already been imported, because ORLA deletes the uploaded file after a successful import. Instead, undo the import, upload the same file again and map it correctly. See "Undo an import and re-import a file".

## The more-than-one-location warning

If you map a store, branch or location column and it contains more than one value, ORLA stops before saving and says the file looks like it has data from more than one location. Each location should be its own branch in ORLA. You can:

- add a branch for the other location on Company Profile and upload that location's data there, or
- if the file really is all one location (for example the column just repeats your shop's own name or code), select "Yes, this is genuinely one location".

Only map the location column if your export has one.

## The required fields

- Sales: the sale date and a price (price per unit or line total).
- Stock count: the product name or SKU, and the quantity in stock.
- Purchases: the date received, the product name or SKU, and the quantity received.
- Repairs: the repair date and at least one of description, price charged or labour cost.

If a required field is not mapped, ORLA cannot save the mapping and asks you to check the required fields.
