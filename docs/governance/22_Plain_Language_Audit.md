# 22_Plain_Language_Audit.md

**Status:** Living document — the testers' term list is added to it as it arrives
**Created:** 06/10/2026
**Related:** `21_Pilot_Launch_Plan.md` (item A4), `frontend/lib/terms.ts`, `frontend/components/HelpHint.tsx`

---

# Purpose

The two pilot testers are shop owners, not analysts. Every word on every screen must make sense to someone who has never used analytics software. Decision (founder, 06/10/2026): audit all screens and menus, replace jargon with plain English, and let the testers add the terms *they* find confusing.

# How it works (so a wording fix is a one-line change)

1. **One glossary** — `frontend/lib/terms.ts`. Each business term has a `label` (what's shown) and a `hint` (the "what's this?" explanation). Screens reference a term by key; they don't write definitions inline.
2. **One hint component** — `HelpHint` (a small "?" that opens the explanation on tap or keyboard focus). It replaces the old hover-only `title=` tooltips, which don't exist on a phone and can't be reached by keyboard. `TermLabel` = label + hint; `Stat term="..."` and `Section hint="..."` use it automatically.
3. **Raw codes never reach the screen.** Internal status/type codes (`needs_review`, `bicycle_shop`, `owner`, `no_extractable_text`) are mapped to plain sentences next to the screen that shows them.
4. **Industry-neutral.** Nothing in the glossary assumes a bike shop (CLAUDE.md core rule); the shop type is the only place a trade is named.
5. **Backend-written text** (findings, recommendations, report summary sentences) follows the same rules: say what it is in everyday words, then what to do.

# Wording rules

- Say what it *is* in everyday words, then what to *do* with it.
- "Sales", not "revenue"; "profit margin", not "gross margin"; "days of stock left", not "stock cover"; "delivery time", not "lead time"; "product code (SKU)", not bare "SKU"; "reorder level", not "threshold" or "reorder point".
- No unexplained abbreviations ("Qty", "PO", "ref", "d").
- Prefer "your shop" to "your business" and "plan" to "subscription" in owner-facing screens.
- Buttons say what happens ("Add to ORLA"), not what the system does ("Run import").

# What changed (06/10/2026)

| Where | Was | Now |
|---|---|---|
| Top menu | Thresholds / Transactions / Company Profile | Reorder levels / Activity / Company profile; "Upload data (subscribe first)" → "(plan not active)" |
| Dashboard sections | Financial Performance, Retail Operations, Workshop Performance, Forecast, Findings & Recommendations, Active Alerts | Money, Stock & shop floor, Repairs & workshop, What to expect, Things to look at, Warnings right now — each with a "?" |
| Dashboard figures | Revenue, Gross margin, Inventory value, Sell-through rate, Stock cover, Dead stock | Sales, Profit margin, Stock value (at cost), Share of stock sold, Days of stock left, Stock that isn't selling — each with a "?" |
| Dashboard text | "excluded from ranking — no recorded cost price", "netted out of the revenue" | Plain sentences saying what is missing and how to fix it |
| Forecast | "Forecast demand / Cover left / Suggested reorder" | "Expected to sell (range) / Days of stock left / Suggested order" |
| Reports | Executive Summary, Revenue Performance, Category Breakdown, Inventory Health, Purchasing Recommendations, Action Plan, "Expenses" | Summary, Sales and profit, By category, Stock health, What to order, What to do next, "Bought in (cost)"; turnover, fast/slow sellers explained |
| Reorder levels page (was "Product Reorder Rules") | Reorder point, Stock cover, ORLA recommends, Setting, "supplier lead time + safety buffer" | Reorder level, Days of stock left, ORLA suggests, Where this number comes from, "your supplier takes about N days to deliver, plus M extra days as a safety cushion"; explanations built from the glossary |
| Upload screens | "Sales transactions / Inventory / Purchases", "Map columns", "Run import", "Remap", raw statuses (`uploaded`, `mapped`) | "Sales / Stock count / Deliveries from suppliers / Repairs", "Match columns", "Add to ORLA", "Change matching", plain statuses |
| Invoice review | Supplier SKU, Qty, Match, Issue, "Create new product", "purchase movements" | Supplier's product code, Quantity, Which of your products?, Needs a look, "It's a new product — add it", "delivery lines recorded as stock received"; clearer failure messages (scans/photos) |
| Activity (was Transactions) | Qty, Order ref, PO/reference, Job/reference; "Purchases" tab | Quantity, Receipt / order no., Order / invoice no., Job no.; "Deliveries from suppliers" |
| Shops page | "Your businesses", raw `bicycle_shop`/`owner`, "Pending Payment", "Subscribed" | "Your shops", "Bicycle shop (Owner)", "Plan not started / Plan active / Plan cancelled", timezone explained |
| Ask ORLA | Long paragraph describing scope | Short intro with three example questions |
| Findings / recommendations (backend text) | "net loss", "gross revenue", "watch line", "minority of sales", "cash tied up" | "sold at a loss", "your sales", "level ORLA watches for", "only part of what you sold", "money tied up" |
| Weekly/monthly report summary sentences | "Revenue increased by…", "stock on hand", "dead-stock issues" | "Sales were up…", "in stock", "nothing is sitting unsold" |

Reviewed and left as is (already plain): notification titles/bodies, billing success/cancel pages, login/sign-up/password pages.

# Still to review (next pass)

- Company profile detail page (`/onboarding/[id]`) field labels.
- Account page.
- Emails (report-ready, invites) — wording check once real emails are viewed.
- Chart axis titles and legends.
- The Ask ORLA *answers*: the model's own phrasing follows the question bank work (item A5), not this audit.

# Testers' term list

Collected from the pilot testers; each row gets a glossary entry or a rewording, and is closed when the tester confirms it now makes sense.

| # | Term / screen | Who | What they thought it meant | Fix | Status |
|---|---|---|---|---|---|
| — | *(none yet — to be filled in once testers start)* | | | | |

# Revision History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 06/10/2026 | Initial audit, glossary, hint component, first pass over every main screen. |
