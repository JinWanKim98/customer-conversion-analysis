# Future experiment appendix — TV delivery-information clarity

**Proposed design only: not an executed experiment or a finding about the cause.**

| Element | Prespecified proposal |
|---|---|
| Hypothesis | If journey review supports delivery-information uncertainty, showing accurate delivery timing/fees earlier on a TV product page may increase verified TV purchases. No price or promotion change is bundled. |
| Population and trigger | First eligible TV detail-page request during enrollment, before variant content is served. Predefine supported market/device, internal/bot exclusions and stock rules from pre-assignment information. |
| Assignment | Stable customer ID, 1:1 current page versus delivery-information module; sticky across sessions/devices where identity is resolved. Enroll each customer once; never randomize sessions of the same customer independently. Unresolvable identities require a revised protocol before launch. |
| Primary estimand | Treatment minus control probability of at least one verified TV order in [assignment, assignment+7 days), among all assigned eligible customers (ITT). Include render failures and nonclickers; never condition on carting or module exposure. |
| Measurement prerequisites | New authoritative order IDs and order timestamps linked to assignment, exposure/error logs and verified taxonomy. Current REES46 does not contain verified order IDs, eligibility assignment or delivery fields. Reconcile all assigned customers; missing follow-up is not silently classified as no purchase. |
| Primary analysis | One two-sided customer-level purchase contrast, alpha .05; report absolute pp difference and marginal Newcombe–Wilson 95% interval. Use the prespecified pooled two-proportion z test when counts support approximation; if the prelaunch baseline implies sparse counts, redesign sizing/inference before launch. Secondary cart/module clicks are exploratory. |
| Guardrails | Proposed margins: seven-day any-category verified purchase difference lower one-sided 97.5% bound > −0.3 pp; seven-day any-checkout-error customer share difference upper one-sided 97.5% bound < +0.2 pp. Both use all assigned customers and validated logs. Two one-sided noninferiority checks use Bonferroni .025 each. Margins are planning choices requiring stakeholder agreement and separate power calculations before launch; no significant harm is not evidence of safety. |
| Quality / SRM | Check unique assignment, stable allocation, cross-variant contamination, missing outcome linkage and 1:1 allocation. SRM p<.001 flags investigation, not automatic efficacy rejection or data reweighting. Daily repeated diagnostics are operational alerts, not family-controlled evidence; diagnose and reconcile before interpreting efficacy. |
| Duration | Choose fixed enrollment days from contemporary eligible unique-customer traffic and the maximum primary/guardrail sample requirement, rounded up to full weeks, minimum 14 days. Freeze a maximum calendar date before launch; after enrollment, wait 7 complete days plus validated ingestion lag (illustrative 1 day). If sample/completeness fails, report inconclusive; no outcome-driven extension. |
| Stopping / decision | Do not stop when efficacy p first falls below .05. Severe broken checkout/privacy defects may pause for safety, without an efficacy claim. At fixed analysis: require data-quality checks, positive primary estimate and p<.05, both guardrails demonstrating noninferiority, and business feasibility. Evaluate effect/interval against the agreed +0.4 pp planning target; MDE is not a guaranteed result. Otherwise no broad rollout from this test. |

## Illustrative sizing — assumptions, not observed business outcomes

Assume independent customers, control purchase probability **2.0%**, 1:1 allocation, two-sided alpha .05 and 80% power. The +0.4 pp example means 2.0%→2.4%, a 20% relative increase. These inputs are not estimated from REES46's 1.34% TV session-product funnel or Hillstrom's email effects.

| Absolute MDE | Treatment rate at MDE | Customers/arm | Total customers |
|---|---:|---:|---:|
| +0.2 pp | 2.2% | 80,682 | 161,364 |
| +0.4 pp | 2.4% | 21,109 | 42,218 |
| +0.6 pp | 2.6% | 9,798 | 19,596 |

The independent-proportion normal approximation uses pooled null and unpooled alternative variance, without continuity correction. Integer search verifies power(n−1)<.8≤power(n); a separate two-tail expression agrees within 1e−12. This is primary-only sizing, not a launch-ready sample requirement. Guardrail baselines, verified-order baseline, eligible traffic, linkage quality and business margins remain prelaunch requirements. No invented daily traffic or promised calendar completion is used.

Code: `src/build_decision_memo.py`; actual calculation inputs, outputs and versions: [11_experiment_power.json](11_experiment_power.json). Reproduce with `/opt/anaconda3/bin/python src/build_decision_memo.py` from the project root. This refreshes Chapter 11 outputs; preserve personal edits first.

Method sources: [statsmodels independent-proportion power](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.power_proportions_2indep.html), [Microsoft Research SRM diagnosis](https://www.microsoft.com/en-us/research/publication/diagnosing-sample-ratio-mismatch-in-online-controlled-experiments-a-taxonomy-and-rules-of-thumb-for-practitioners/), [fixed-design inference discussion](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/06/ftir-online-evaluation-final-journal.pdf). Local execution uses statsmodels 0.14.0 and scipy 1.11.4; linked documentation may describe a different release.
