# Executive decision memo — Customer conversion measurement and experimentation

Independent portfolio study | Hypothetical Product/CRM stakeholders | 2026-10-28

**Recommendation.** Prioritize measurement coverage, then investigate TV journeys before selecting a customer-experience intervention. Evaluate the historical email experiment separately. No operational change has been deployed and no business improvement is claimed.

## Case A — REES46: what deserves investigation?

The frozen primary funnel records **23,672/644,660 = 3.67%** ordered progressions. A unit is a customer–30-minute-session–product group, attributed at first view, with strict view < cart < purchase and a completed-session buffer. This is neither customer conversion nor an order/revenue count.

| Priority | Observed evidence | Recommended action and completion evidence |
|---|---|---|
| P0: measurement coverage | Unknown category: 180,978/644,660 eligible groups (28.07%). | Analytics/catalog owner: audit product mappings and logging; deliver reconciled coverage and exception counts while preserving Unknown. |
| P1: TV journey | 228/17,065 ordered progression (1.34%); view→cart 3.49% versus 7.67% overall. | Product/UX: review logging and sampled journeys; validate a specific friction hypothesis, then test it. Delivery-information clarity is a proposed hypothesis, not a finding. |
| P2: high-price context | Price 1000+ source units: 50/5,443 (0.92%). | Commercial/analytics: inspect category/product mix, exposure and instrumentation before proposing a price change. |

These are qualitative investigation priorities, not a financial-return ranking. Segments overlap and counts must not be added. Video cards show 6.54% progression but a different stage pattern; they are not a randomized control for TVs. Missing labels, product mix, repeated users/products and incomplete logging can explain observed gaps. Unobserved progression is not proven abandonment or recoverable sales.

TV gaps versus its complement remain negative across seven declared measurement scenarios. The primary TV proportion has exploratory 95% marginal user-cluster interval 1.149–1.533% and alternative product-cluster interval 0.854–1.748%. Targets were selected after exploration; these are separate one-way sensitivity analyses, not joint adjustment, simultaneous intervals or evidence of a UX effect. Keep the primary definition fixed when comparing reports.

## Case B — Hillstrom: what does the actual experiment support?

All 64,000 assigned rows, including nonbuyers and zero spend, remain in the separate two-week historical analysis.

| Email versus no email | Purchase difference | 95% marginal interval | Holm p |
|---|---:|---:|---:|
| Mens merchandise | +0.6805 pp | [0.5014, 0.8641] pp | 3.05e-13 |
| Womens merchandise | +0.3111 pp | [0.1502, 0.4745] pp | 0.0001571 |

Both primary comparisons pass the two-test Holm policy. The intervals are individual Newcombe–Wilson intervals, not Holm-adjusted simultaneous intervals. Secondary recorded-spend differences per assigned customer are +$0.7698 [$0.4976, $1.0566] and +$0.4244 [$0.1703, $0.6828], with exploratory 95% bootstrap intervals including zero-spend customers. Mens has the larger purchase estimate; its direct comparison with Womens remains exploratory. Merchandise labels do not describe customer gender. Historical assignment effects do not establish current campaign performance, optimal targeting, profit or ROI; costs and margins are absent. Do not transfer these effects to REES46.

## Next decision

Complete mapping/journey checks before testing a TV-page delivery-information module. The [future experiment appendix](11_future_experiment_plan.md) specifies customer randomization, seven-day outcomes, guardrails, sizing and stopping rules. Its 2% baseline and +0.4 pp MDE are explicit assumptions; the primary-only illustration requires 21,109 customers per arm. The historical 1.34% session-product rate is not this customer-level baseline. Re-estimate the baseline and size guardrails before launch. Proposed owners are hypothetical; no experiment has been run.

Evidence: [conversion diagnostics](07_conversion_results.json), [robustness](08_robustness_results.json), [historical experiment](09_ab_results.json), [proposed experiment plan](11_future_experiment_plan.md). Raw-source redistribution requires a source-specific review. The computation above is reproduced from the declared inputs.
