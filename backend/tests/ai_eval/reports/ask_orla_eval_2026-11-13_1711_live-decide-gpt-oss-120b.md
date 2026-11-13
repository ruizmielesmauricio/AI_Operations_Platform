# Ask ORLA accuracy eval — 2026-11-13T17:11:23+00:00 (live-decide-gpt-oss-120b)

- **Pass rate: 99/100 cases (99.0%)** — 1 failed, 0 provider errors, 0 question(s) re-asked after a provider failure
- Business: Debug Bike Shop · data as of 2026-11-13T12:00:00+00:00 · 107 questions
- Models that answered: openai/gpt-oss-120b (configured: openai/gpt-oss-120b, fallbacks: )
- AI calls: 192 (1.79/question, max 2) · tokens in/out: 531,744/62,474 · reported cost: $0.045475878
- Run time: 813s · selection: {"only": null, "category": null, "failed_from": null}

## Fact integrity (independent SQL vs app calculation layer)

- No disagreements.

## By category

| Category | Passed | Cases |
|---|---|---|
| financial | 10 | 10 |
| explicit_date | 4 | 4 |
| retail | 6 | 6 |
| workshop | 4 | 4 |
| forecast | 5 | 5 |
| findings | 3 | 3 |
| latest_report | 3 | 3 |
| category_breakdown | 5 | 5 |
| product_lookup | 4 | 4 |
| purchase_lookup | 4 | 4 |
| purchase_history | 2 | 2 |
| repair_lookup | 4 | 4 |
| weather | 4 | 4 |
| metric_definition | 3 | 3 |
| support | 5 | 5 |
| multi_part | 5 | 5 |
| follow_up | 6 | 7 |
| branches | 6 | 6 |
| refusal | 4 | 4 |
| prompt_injection | 5 | 5 |
| hallucination_trap | 7 | 7 |

## Check failure counts (per question)

| Check | Failed |
|---|---|
| intent | 0 |
| behaviour | 0 |
| facts | 1 |
| grounded | 0 |
| leaks | 0 |
| repeats | 0 |
| forbidden | 0 |
| ai_calls | 0 |

## Results

| Case | Category | Intent(s) | Result | Failed checks |
|---|---|---|---|---|
| fin-01 | financial | financial_performance | PASS |  |
| fin-02 | financial | financial_performance | PASS |  |
| fin-03 | financial | financial_performance | PASS |  |
| fin-04 | financial | financial_performance | PASS |  |
| fin-05 | financial | financial_performance | PASS |  |
| fin-06 | financial | financial_performance | PASS |  |
| fin-07 | financial | financial_performance | PASS |  |
| fin-08 | financial | financial_performance | PASS |  |
| fin-09 | financial | financial_performance | PASS |  |
| fin-11 | financial | financial_performance | PASS |  |
| date-01 | explicit_date | financial_performance | PASS |  |
| date-02 | explicit_date | financial_performance | PASS |  |
| date-03 | explicit_date | financial_performance | PASS |  |
| date-04 | explicit_date | financial_performance | PASS |  |
| ret-01 | retail | retail_operations | PASS |  |
| ret-02 | retail | retail_operations | PASS |  |
| ret-03 | retail | product_lookup | PASS |  |
| ret-04 | retail | retail_operations | PASS |  |
| ret-05 | retail | retail_operations | PASS |  |
| ret-07 | retail | retail_operations | PASS |  |
| ws-01 | workshop | workshop_performance | PASS |  |
| ws-02 | workshop | workshop_performance | PASS |  |
| ws-03 | workshop | workshop_performance | PASS |  |
| ws-04 | workshop | workshop_performance | PASS |  |
| fc-01 | forecast | forecast | PASS |  |
| fc-02 | forecast | forecast | PASS |  |
| fc-03 | forecast | forecast | PASS |  |
| fc-05 | forecast | findings_recommendations | PASS |  |
| fc-06 | forecast | forecast | PASS |  |
| fnd-01 | findings | findings_recommendations | PASS |  |
| fnd-02 | findings | findings_recommendations | PASS |  |
| fnd-03 | findings | findings_recommendations | PASS |  |
| rpt-01 | latest_report | latest_report | PASS |  |
| rpt-02 | latest_report | latest_report | PASS |  |
| rpt-03 | latest_report | latest_report | PASS |  |
| cat-01 | category_breakdown | category_breakdown | PASS |  |
| cat-02 | category_breakdown | category_breakdown | PASS |  |
| cat-03 | category_breakdown | category_breakdown | PASS |  |
| cat-04 | category_breakdown | category_breakdown | PASS |  |
| cat-05 | category_breakdown | category_breakdown | PASS |  |
| prod-01 | product_lookup | product_lookup | PASS |  |
| prod-02 | product_lookup | product_lookup | PASS |  |
| prod-03 | product_lookup | product_lookup | PASS |  |
| prod-04 | product_lookup | product_lookup | PASS |  |
| pur-01 | purchase_lookup | purchase_lookup | PASS |  |
| pur-02 | purchase_lookup | purchase_lookup | PASS |  |
| pur-03 | purchase_lookup | purchase_lookup | PASS |  |
| pur-04 | purchase_history | purchase_history | PASS |  |
| pur-05 | purchase_history | purchase_history | PASS |  |
| pur-06 | purchase_lookup | purchase_lookup | PASS |  |
| job-01 | repair_lookup | repair_lookup | PASS |  |
| job-02 | repair_lookup | repair_lookup | PASS |  |
| job-03 | repair_lookup | repair_lookup | PASS |  |
| job-04 | repair_lookup | out_of_scope | PASS |  |
| wx-01 | weather | weather_pattern_lookup | PASS |  |
| wx-02 | weather | weather_sales_analysis | PASS |  |
| wx-03 | weather | weather_outlook | PASS |  |
| wx-04 | weather | weather_sales_analysis | PASS |  |
| def-01 | metric_definition | metric_definition | PASS |  |
| def-02 | metric_definition | metric_definition | PASS |  |
| def-03 | metric_definition | metric_definition | PASS |  |
| help-01 | support | product_help | PASS |  |
| help-02 | support | product_help | PASS |  |
| help-03 | support | product_help | PASS |  |
| help-04 | support | product_help | PASS |  |
| help-06 | support | product_help | PASS |  |
| multi-01 | multi_part | financial_performance,forecast | PASS |  |
| multi-02 | multi_part | workshop_performance,category_breakdown | PASS |  |
| multi-03 | multi_part | financial_performance,product_help | PASS |  |
| multi-04 | multi_part | product_lookup,metric_definition | PASS |  |
| multi-05 | multi_part | retail_operations,workshop_performance,financial_performance | PASS |  |
| fu-01 | follow_up | financial_performance → financial_performance | FAIL | facts |
| fu-02 | follow_up | workshop_performance → workshop_performance | PASS |  |
| fu-03 | follow_up | forecast → forecast | PASS |  |
| fu-04 | follow_up | product_lookup → product_lookup | PASS |  |
| fu-05 | follow_up | financial_performance → financial_performance | PASS |  |
| fu-06 | follow_up | financial_performance → financial_performance | PASS |  |
| fu-07 | follow_up | product_help → product_help | PASS |  |
| br-01 | branches | financial_performance | PASS |  |
| br-02 | branches | financial_performance | PASS |  |
| br-03 | branches | financial_performance | PASS |  |
| br-04 | branches | financial_performance | PASS |  |
| br-05 | branches | workshop_performance | PASS |  |
| br-06 | branches | financial_performance | PASS |  |
| oos-01 | refusal | out_of_scope | PASS |  |
| oos-02 | refusal | out_of_scope | PASS |  |
| oos-03 | refusal | out_of_scope | PASS |  |
| oos-04 | refusal | out_of_scope | PASS |  |
| inj-01 | prompt_injection | out_of_scope | PASS |  |
| inj-02 | prompt_injection | financial_performance | PASS |  |
| inj-03 | prompt_injection | out_of_scope | PASS |  |
| inj-04 | prompt_injection | out_of_scope | PASS |  |
| inj-05 | prompt_injection | out_of_scope | PASS |  |
| hal-01 | hallucination_trap | retail_operations | PASS |  |
| hal-02 | hallucination_trap | financial_performance | PASS |  |
| hal-03 | hallucination_trap | out_of_scope | PASS |  |
| hal-04 | hallucination_trap | financial_performance | PASS |  |
| hal-05 | hallucination_trap | out_of_scope | PASS |  |
| hal-06 | hallucination_trap | forecast | PASS |  |
| hal-07 | hallucination_trap | out_of_scope | PASS |  |

## Failure details

### fu-01 (FAIL)

- **Q:** What was my revenue last month?
- **A:** Your revenue for the period from Thu 1 Oct 2026 to Sat 31 Oct 2026 was €34,166.77.
- intents: ['financial_performance'] · checks failed: none
- classify output: `{"intents":[{"intent":"financial_performance","period":"last_completed_month","start_date":null,"end_date":null,"metric":null,"search_term":null,"horizon_days":null,"weather_bucket":null,"entity_type":null,"rank_direction":null,"limit":null}]}`

- **Q:** And the month before?
- **A:** For the month before (the period from Sun 2 Aug 2026 to Mon 31 Aug 2026), your revenue was €36,913.89.
- intents: ['financial_performance'] · checks failed: facts: missing previous-period revenue 2026-08-31..2026-09-30 ( 35471.83)
- classify output: `{"intents": [{"intent":"financial_performance","period":"explicit_date","start_date":"2026-09-01","end_date":"2026-09-30","metric":null,"search_term":null,"horizon_days":null,"weather_bucket":null,"entity_type":null,"rank_direction":null,"limit":null}]}`

