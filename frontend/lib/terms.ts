// The one place every plain-English label and "What's this?" explanation
// lives. Screens never hand-write a definition for a business term: they
// reference it by key here, so a wording fix (e.g. after a tester says
// "I don't know what X means") is a one-line change that updates every
// screen at once.
//
// Rules for wording:
//  - Say what it IS in everyday words, then what to DO with it.
//  - No unexplained jargon inside an explanation (no "COGS", "SKU" without
//    "product code", "lead time" without "delivery time").
//  - `label` is the short name shown on screen; `hint` is the explanation
//    shown when the owner taps the "?" beside it.
//  - Industry-neutral: nothing here may assume a bike shop (CLAUDE.md).

export type Term = { label: string; hint: string };

export const TERMS = {
  // --- Navigation ---------------------------------------------------------
  reorderLevels: {
    label: "Reorder levels",
    hint: "For each product, how low its stock can get before ORLA tells you to order more. Set once per product or category; ORLA suggests sensible values.",
  },
  transactions: {
    label: "Activity",
    hint: "Every individual sale, delivery received and repair job you've loaded into ORLA, newest first.",
  },
  uploadData: {
    label: "Upload data",
    hint: "Add your sales, stock counts, deliveries and repairs by uploading a spreadsheet (CSV or Excel) or a supplier invoice PDF.",
  },
  companyProfile: {
    label: "Company profile",
    hint: "Your shop's details, your team, extra branches and your plan.",
  },

  // --- Money & profit -----------------------------------------------------
  revenue: {
    label: "Sales",
    hint: "The total you took from customers in the selected dates, after returns and refunds are taken off.",
  },
  returns: {
    label: "Returns & refunds",
    hint: "Items customers brought back. They are already taken off your sales total, so you don't need to subtract them.",
  },
  grossProfit: {
    label: "Profit on sales",
    hint: "What's left from your sales after paying for the stock you sold. It does not include rent, wages or other running costs.",
  },
  grossMargin: {
    label: "Profit margin",
    hint: "Out of every €100 you sell, how many euro are left after paying for the stock itself. For example 40% means €40 of every €100 is yours before running costs.",
  },
  costCoverage: {
    label: "Sales with a known cost",
    hint: "The share of your sales where ORLA knows what the item cost you. The lower this is, the less you should trust the profit margin. Fix it by adding cost prices to your products.",
  },
  taxCoverage: {
    label: "Sales with VAT recorded",
    hint: "The share of sales where the VAT amount is known. Where it's missing, ORLA can't separate VAT from your profit, so margins may look a bit higher than they are.",
  },
  workshopMargin: {
    label: "Repair profit (labour only)",
    hint: "What you charged for repairs minus what the labour cost you. The cost of parts isn't tracked yet, so the real profit is a little lower.",
  },
  valueAtCost: {
    label: "Stock value (at cost)",
    hint: "What the stock on your shelves cost you to buy, not what you'll sell it for.",
  },

  // --- Stock --------------------------------------------------------------
  sku: {
    label: "Product code (SKU)",
    hint: "The code that identifies a product — on your price label, till or supplier invoice. If you don't use codes, ORLA matches on the product name instead.",
  },
  stockOnHand: {
    label: "In stock",
    hint: "How many you have right now, according to your latest stock count and the sales and deliveries since.",
  },
  soldLast30: {
    label: "Sold in last 30 days",
    hint: "How many you sold recently. It shows how fast a product moves.",
  },
  stockCover: {
    label: "Days of stock left",
    hint: "How many days your current stock should last if you keep selling at the recent pace. Blank means there haven't been enough recent sales to tell.",
  },
  reorderPoint: {
    label: "Reorder level",
    hint: "The number of days of stock left at which ORLA warns you to order more. For example 14 days means: warn me when I have about two weeks of stock left.",
  },
  orlaRecommends: {
    label: "ORLA suggests",
    hint: "A reorder level worked out from how fast the product sells and how long your supplier takes to deliver. It's a suggestion only — you decide.",
  },
  setting: {
    label: "Where this number comes from",
    hint: "Shows whether you set this level yourself for the product, it follows the whole category, you accepted ORLA's suggestion, or nobody has set one yet (so a standard default is used).",
  },
  deadStock: {
    label: "Stock that isn't selling",
    hint: "Products on your shelves that haven't sold at all in the selected dates. Money is tied up in them — think twice before ordering more.",
  },
  sellThrough: {
    label: "Share of stock sold",
    hint: "Of everything you had to sell (sold + still on the shelf), the share that actually sold. Higher usually means you're buying the right things.",
  },
  suggestedReorder: {
    label: "Suggested order",
    hint: "A starting point for how many to order, based on expected sales minus what you already have. Check it against your supplier's delivery time and your gut feel.",
  },
  leadTime: {
    label: "Delivery time",
    hint: "How many days a supplier usually takes from you ordering to the stock arriving.",
  },
  overstocked: {
    label: "Overstocked",
    hint: "You have far more than you're likely to sell soon (several times your reorder level).",
  },
  stale: {
    label: "Slow or not selling",
    hint: "Products that have not sold at all recently, or would take a very long time to sell through at the current pace.",
  },

  inventoryTurnover: {
    label: "Stock turnover",
    hint: "How many times over you sold through the stock on your shelves in this period. A higher number means your money isn't sitting idle in stock.",
  },
  fastMovers: {
    label: "Fast sellers",
    hint: "Products that will sell out quickly — 14 days of stock left or less at the recent pace.",
  },
  slowMovers: {
    label: "Slow sellers",
    hint: "Products with 60 or more days of stock left at the recent pace. Consider a discount, a bundle, or returning some to the supplier.",
  },

  // --- Dashboard sections -------------------------------------------------
  financialPerformance: {
    label: "Money",
    hint: "How much you sold, what you kept after paying for stock, and how that compares with the period just before.",
  },
  retailOperations: {
    label: "Stock & shop floor",
    hint: "What's selling, what's sitting, and how long your stock will last.",
  },
  workshopPerformance: {
    label: "Repairs & workshop",
    hint: "Money from repairs and servicing, and how much of it you kept after labour.",
  },
  forecast: {
    label: "What to expect",
    hint: "A simple estimate of your next sales based on your recent history (same-weekday pattern, or a plain average when there's little history). It isn't a guarantee. The shaded band shows a normal range.",
  },
  findings: {
    label: "Things to look at",
    hint: "Problems and opportunities ORLA spotted by checking your numbers against fixed rules — for example falling sales, thin margins, or stock about to run out. Each one says what to do next.",
  },
  alerts: {
    label: "Warnings right now",
    hint: "Things that need attention today, such as products that are about to run out.",
  },

  // --- Uploads ------------------------------------------------------------
  mapping: {
    label: "Match your columns",
    hint: "Tell ORLA which column in your spreadsheet is which (date, product, quantity…). ORLA guesses; check the guesses, fix any that are wrong, and it remembers for next time.",
  },
  importRecord: {
    label: "Upload history",
    hint: "Everything you've uploaded. You can undo an upload and ORLA will take back what it added, and restore prices it changed.",
  },
  undoImport: {
    label: "Undo this upload",
    hint: "Removes the sales, stock or deliveries this file added. If the file also changed product prices or categories, ORLA puts them back to what they were before.",
  },
  duplicateInvoice: {
    label: "Looks like one you've already added",
    hint: "An invoice with the same supplier, number and total was uploaded before. Adding it twice would count the stock and cost twice.",
  },

  // --- Account & plan -----------------------------------------------------
  branch: {
    label: "Branch",
    hint: "A second (or third) shop location. Each branch has its own data and its own reports, and you can view them all together on the dashboard.",
  },
  seat: {
    label: "Team member",
    hint: "Someone you invite to use ORLA for your shop. Each extra team member adds €5 a month to your plan.",
  },
  complimentary: {
    label: "Complimentary (pilot)",
    hint: "Free access during the pilot. You won't be asked for a card, and nothing here is billed.",
  },
  timezone: {
    label: "Timezone",
    hint: "Used to decide where one day ends and the next begins, so a sale at 11:30pm counts on the right day. For Ireland this is Europe/Dublin.",
  },
} as const satisfies Record<string, Term>;

export type TermKey = keyof typeof TERMS;
