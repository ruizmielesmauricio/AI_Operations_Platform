# Internal One-Pager — Founder Reference

**Confidential — internal use only. Not for customers or investors.**
**Version:** 0.1 | **Based on:** `08_Cost_Analysis.md`, `09_Business_Model.md`

---

## What We're Building

A decision-support platform that sits **on top of** a small business's existing POS/accounting system and answers what that system can't: why margin changed, what to reorder, how the workshop is really performing, and what's likely to happen next.

**Motto:** Business Logic First. AI Second.
Deterministic code calculates. AI only explains. This is the whole defensibility argument.

---

## Why This Wins (Internal Case)

| Strength | Why It Matters Commercially |
|---|---|
| We complement the POS, we don't replace it | Removes the biggest adoption barrier — no migration, no retraining, no risk to their till |
| Deterministic calculation engine | Numbers are reproducible and testable. Competitors using LLMs to calculate can't promise this |
| Industry-flexible core | One codebase serves bike shops, garages, cafés, pet shops. Each new vertical is config, not a rebuild |
| AI cost is small and controlled | Routed via OpenRouter with a quality floor. AI stays ~1-4% of revenue, not 30% |
| Very low fixed cost base | Founder-operable. Break-even is a handful of customers, not hundreds |
| Real gap in the market | Nobody combines retail+workshop domain logic with explainable analytics at SMB price |

---

## Unit Economics — Per Customer, Per Month

| Line | Amount (EUR) |
|---|---|
| Subscription revenue | **€80.00** |
| Stripe fee (card or SEPA) | −€1.50 to −€2.50 |
| AI usage (OpenRouter-routed) | −€0.50 to −€3.00 |
| Storage + database (allocated) | −€1.00 |
| **Variable cost per customer** | **−€3.00 to −€6.50** |
| **Contribution per customer** | **≈ €73.50 to €77.00** |

**Contribution margin: roughly 92–96% per customer.** This is the number that makes the business work.

---

## Full-Year Model at a 50-Customer Base

### Revenue

| Metric | Amount |
|---|---|
| Price per customer/month | €80 |
| Customers | 50 |
| **MRR** | **€4,000** |
| **ARR / Annual revenue** | **€48,000** |

### Costs — Variable (scales with customers)

| Scenario | Per customer/mo | Annual total (50 customers) |
|---|---|---|
| Low AI usage | €3.00 | €1,800 |
| **Expected** | **€4.50** | **€2,700** |
| High AI usage | €6.50 | €3,900 |

### Costs — Fixed (mostly flat at this scale)

At 50 customers we're off most free tiers. Estimated monthly:

| Item | Monthly |
|---|---|
| VPS (upgraded) | €25–50 |
| Neon PostgreSQL | €25–70 |
| Cloudflare R2 | €5–10 |
| Resend (email) | €20 |
| Sentry | €26 |
| Plausible | €9 |
| Domain/DNS | €1 |
| **Fixed total** | **€120–190/mo → €1,440–2,280/yr** |

### Bottom Line — Year at 50 Customers

| Line | Amount |
|---|---|
| Annual revenue | **€48,000** |
| Variable costs (expected) | −€2,700 |
| Fixed costs (expected) | −€1,800 |
| **Total operating cost** | **−€4,500** |
| **Gross profit** | **≈ €43,500** |
| **Gross margin** | **≈ 90%** |

**Sensitivity:** even at worst-case AI usage and highest fixed costs (€3,900 + €2,280 = €6,180), gross profit is still ~€41,800 (87%). The model is not fragile to infrastructure cost — it's fragile to *getting 50 customers*.

---

## Break-Even Math

| Customers | MRR | Covers fixed cost (~€150/mo)? |
|---|---|---|
| 2 | €160 | Yes — fixed costs covered from customer 2 |
| 10 | €800 | ~€750/mo contribution |
| 25 | €2,000 | ~€1,700/mo contribution |
| 50 | €4,000 | ~€3,625/mo contribution |

**Infrastructure break-even is ~2 customers.** The real break-even is founder time — this doesn't pay a salary until roughly 20–30 customers, and doesn't fund a hire until well past 50.

---

## What This Model Assumes (And Doesn't Prove)

Be honest with yourself about these:

- **No customer has paid anything yet.** 50 customers is a modelling scenario, not a pipeline.
- **No paid acquisition is modelled.** All growth assumed founder-led outreach and referral.
- **Churn is not in these numbers.** At 5% monthly churn you need ~2.5 new customers/month just to hold at 50.
- **Support time is not costed.** If each customer needs 30 min/month, 50 customers = 25 hours/month of founder time — that's the real constraint, not servers.
- **Competitor pricing is from public pages,** not trials. Directional only.

---

## The Three Numbers to Watch

1. **Willingness to pay** — do owners actually say yes to €80/mo on top of their POS spend? (Unvalidated. Interviews required.)
2. **AI cost per customer** — must stay under ~€3/mo or margin story weakens. (Track from day one.)
3. **Support hours per customer** — the hidden cost that kills solo-founder SaaS. (Track from first pilot.)

---

## Immediate Priority

Nothing in this document matters until demand is validated. **Complete the 15–20 bike shop interviews in `15_Customer_Discovery.md` before spending further money or build time.** The economics are good *if* people buy. That "if" is the entire risk.

---

*All figures are planning estimates, not financial projections or advice. Replace with real measurements as pilot data arrives.*