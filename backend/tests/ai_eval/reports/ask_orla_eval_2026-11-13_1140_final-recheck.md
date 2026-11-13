# Ask ORLA accuracy eval — 2026-11-13T11:40:34+00:00 (final-recheck)

- **Pass rate: 9/9 cases (100.0%)** — 0 failed, 0 provider errors, 1 question(s) re-asked after a provider failure
- Business: Debug Bike Shop · data as of 2026-11-13T12:00:00+00:00 · 11 questions
- Models that answered: cohere/north-mini-code:free (configured: openai/gpt-oss-20b:free, fallbacks: google/gemma-4-31b-it:free,cohere/north-mini-code:free)
- AI calls: 22 (2.00/question, max 2) · tokens in/out: 54,610/12,966 · reported cost: $0
- Run time: 205s · selection: {"only": "fin-04,ret-04,fnd-01,pur-02,multi-03,multi-04,fu-01,fu-02,hal-04", "category": null, "failed_from": null}

## Fact integrity (independent SQL vs app calculation layer)

- No disagreements.

## By category

| Category | Passed | Cases |
|---|---|---|
| financial | 1 | 1 |
| retail | 1 | 1 |
| findings | 1 | 1 |
| purchase_lookup | 1 | 1 |
| multi_part | 2 | 2 |
| follow_up | 2 | 2 |
| hallucination_trap | 1 | 1 |

## Check failure counts (per question)

| Check | Failed |
|---|---|
| intent | 0 |
| behaviour | 0 |
| facts | 0 |
| grounded | 0 |
| leaks | 0 |
| repeats | 0 |
| forbidden | 0 |
| ai_calls | 0 |

## Results

| Case | Category | Intent(s) | Result | Failed checks |
|---|---|---|---|---|
| fin-04 | financial | financial_performance | PASS |  |
| ret-04 | retail | retail_operations | PASS |  |
| fnd-01 | findings | findings_recommendations | PASS |  |
| pur-02 | purchase_lookup | purchase_lookup | PASS |  |
| multi-03 | multi_part | financial_performance,product_help | PASS |  |
| multi-04 | multi_part | product_lookup,metric_definition | PASS |  |
| fu-01 | follow_up | financial_performance → financial_performance | PASS |  |
| fu-02 | follow_up | workshop_performance → workshop_performance | PASS |  |
| hal-04 | hallucination_trap | financial_performance | PASS |  |
