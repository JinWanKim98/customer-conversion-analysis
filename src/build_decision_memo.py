"""Build the Chapter 11 decision memo from frozen results; do not reanalyse raw data.

Run with /opt/anaconda3/bin/python. Future-test power inputs are labelled planning
assumptions, never estimates of the historical session-product funnel.
"""
import csv
import hashlib
import json
import math
from pathlib import Path

import scipy
import statsmodels
from scipy.stats import norm
from statsmodels.stats.proportion import power_proportions_2indep

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
INPUTS = ["reports/07_conversion_results.json", "reports/08_robustness_results.json",
          "reports/08_cluster_intervals.json", "reports/09_ab_results.json",
          "docs/04_metric_contract.json"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def required_n(p0, difference, target=.8, alpha=.05):
    """Smallest per-arm integer reaching normal-approximation two-sided power."""
    if not (0 < p0 < p0 + difference < 1 and 0 < alpha < 1 and .5 < target < 1):
        raise ValueError("Invalid independent-proportion planning assumptions")

    def power(n):
        return float(power_proportions_2indep(
            difference, p0, n, ratio=1, alpha=alpha,
            alternative="two-sided", return_results=False))

    low, high = 1, 2
    while power(high) < target:
        high *= 2
    while low < high:
        mid = (low + high) // 2
        if power(mid) >= target:
            high = mid
        else:
            low = mid + 1
    n = low
    assert power(n - 1) < target <= power(n)
    # Independent expression of the same pooled-null/unpooled-alternative
    # approximation: verify both tails, rather than compare unrelated methods.
    p1 = p0 + difference
    pooled = (p0 + p1) / 2
    se0 = math.sqrt(2 * pooled * (1 - pooled) / n)
    se1 = math.sqrt((p0 * (1 - p0) + p1 * (1 - p1)) / n)
    critical = norm.isf(alpha / 2) * se0
    independent = float(norm.sf((critical - difference) / se1)
                        + norm.cdf((-critical - difference) / se1))
    assert abs(independent - power(n)) < 1e-12
    return {"baseline_probability_assumed": p0,
            "treatment_probability_at_mde": p1,
            "absolute_mde_pp": difference * 100,
            "relative_mde_pct": 100 * difference / p0,
            "alpha_two_sided": alpha, "target_power": target,
            "n_per_arm": n, "total_n": n * 2,
            "power_at_n": power(n), "power_at_n_minus_one": power(n - 1),
            "independent_formula_matches": True}


def main():
    hashes = {name: sha(ROOT / name) for name in INPUTS}
    sources = {name: json.loads((ROOT / name).read_text()) for name in INPUTS}
    diagnostic = sources[INPUTS[0]]["profiles"]
    robust = sources[INPUTS[1]]["profiles"]
    experiment = sources[INPUTS[3]]
    frozen = experiment["snapshots_unchanged"]
    assert all(sha(ROOT / name) == value for name, value in frozen.items())
    overall = next(x for x in diagnostic["overall"] if x["cohort"] == "session_30")
    categories = {x["category_label"]: x for x in diagnostic["category"]
                  if x["cohort"] == "session_30"}
    unknown, tv, gpu = (categories[k] for k in
                        ["Unknown", "electronics.video.tv", "computers.components.videocards"])
    expensive = next(x for x in diagnostic["price_band"]
                     if x["cohort"] == "session_30" and x["price_band"] == "[1000,+inf)")
    effects = {x["treatment"]: x for x in experiment["profiles"]["binary_effects"]
               if x["metric"] == "purchase"}
    assert experiment["all_assigned_rows_retained"] and experiment["n"] == 64000
    assert not experiment["rees46_joined"]
    tv_intervals = {x["cluster"]: x["target_pct_interval"]
                    for x in sources[INPUTS[2]]["results"] if x["target"] == "TV"}
    user_ci, product_ci = tv_intervals["user_id"], tv_intervals["product_id"]
    tv_scenarios = [x for x in robust["scenarios"] if x["target"] == "TV"]
    assert len(tv_scenarios) == 7
    for target in tv_scenarios:
        total = next(x for x in robust["scenarios"]
                     if x["target"] == "Overall" and x["scenario"] == target["scenario"])
        complement_rate = 100 * (total["purchase_groups"] - target["purchase_groups"]) / (total["eligible_groups"] - target["eligible_groups"])
        assert target["ordered_purchase_pct"] < complement_rate
    share = 100 * unknown["eligible_groups"] / overall["eligible_groups"]
    sizing = [required_n(.02, diff) for diff in [.002, .004, .006]]
    chosen = sizing[1]
    power_path = REPORTS / "11_experiment_power.json"
    power_path.write_text(json.dumps({
        "data_kind": "illustrative future planning assumptions; not observed outcomes",
        "method": "Independent two-proportion z-test normal approximation; pooled null variance and unpooled alternative; no continuity correction",
        "allocation": "1:1 independent customers", "baseline_is_measured": False,
        "historical_tv_session_rate_is_not_customer_baseline": True,
        "rows": sizing, "chosen_example_mde_pp": .4,
        "versions": {"scipy": scipy.__version__, "statsmodels": statsmodels.__version__},
        "limitation": "Primary-endpoint illustration only. Re-estimate contemporary customer baseline/traffic and size guardrails before launch. Independence, complete outcomes and no interference assumed."
    }, ensure_ascii=False, indent=2) + "\n")
    priority_rows = [
        {"priority": "P0", "case": "REES46", "evidence_kind": "observed measurement coverage",
         "finding": f"Unknown category {unknown['eligible_groups']:,}/{overall['eligible_groups']:,} eligible groups ({share:.2f}%)",
         "decision": "Audit event-to-product category mapping by time, product and event type; preserve Unknown",
         "proposed_owner": "Analytics + catalog/instrumentation owner (hypothetical)",
         "completion_evidence": "Reconciled coverage report and reviewed mapping exceptions; no silent cohort deletion",
         "not_established": "Metadata correction causes more sales", "source": INPUTS[0]},
        {"priority": "P1", "case": "REES46", "evidence_kind": "exploratory observational pattern",
         "finding": f"TV ordered progression {tv['ordered_purchase_groups']:,}/{tv['eligible_groups']:,} ({tv['ordered_purchase_pct']:.2f}%)",
         "decision": "Review event coverage and sampled TV journeys, then validate a delivery-information hypothesis before a customer-randomized test",
         "proposed_owner": "Product analyst + UX + instrumentation owner (hypothetical)",
         "completion_evidence": "Documented journey review, reconciled logging and signed-off future experiment protocol",
         "not_established": "Delivery information or checkout UX is the cause", "source": INPUTS[0]},
        {"priority": "P2", "case": "REES46", "evidence_kind": "exploratory overlapping segment",
         "finding": f"Price 1000+ progression {expensive['ordered_purchase_groups']:,}/{expensive['eligible_groups']:,} ({expensive['ordered_purchase_pct']:.2f}%)",
         "decision": "Check category/product mix, exposure, inventory and tracking before considering a pricing intervention",
         "proposed_owner": "Commercial + product analyst (hypothetical)",
         "completion_evidence": "Comparable within-category/product coverage analysis with small-cell flags",
         "not_established": "Discounting creates incremental orders or profit", "source": INPUTS[0]},
        {"priority": "Separate CRM case", "case": "Hillstrom 2008", "evidence_kind": "historical randomized assignment effects",
         "finding": "Both treatment-control purchase comparisons pass the two-test Holm rule",
         "decision": "Use the historical evidence as an evaluation example; obtain current cost, margin, consent and outcome evidence before a new campaign test",
         "proposed_owner": "CRM analyst (hypothetical)",
         "completion_evidence": "Contemporary randomized plan and economic inputs before a present-day deployment decision",
         "not_established": "Current ROI, optimal targeting, or a REES46 campaign effect", "source": INPUTS[3]}
    ]
    with (REPORTS / "11_decision_register.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(priority_rows[0]))
        writer.writeheader()
        writer.writerows(priority_rows)

    mens, womens = effects["Mens E-Mail"], effects["Womens E-Mail"]
    spend = {x["treatment"]: x for x in experiment["profiles"]["spend_effects"]}
    ms, ws = spend["Mens E-Mail"], spend["Womens E-Mail"]
    memo = f"""# Executive decision memo — Customer conversion measurement and experimentation

Independent portfolio study | Hypothetical Product/CRM stakeholders | 2026-10-28

**Recommendation.** Prioritize measurement coverage, then investigate TV journeys before selecting a customer-experience intervention. Evaluate the historical email experiment separately. No operational change has been deployed and no business improvement is claimed.

## Case A — REES46: what deserves investigation?

The frozen primary funnel records **{overall['ordered_purchase_groups']:,}/{overall['eligible_groups']:,} = {overall['ordered_purchase_pct']:.2f}%** ordered progressions. A unit is a customer–30-minute-session–product group, attributed at first view, with strict view < cart < purchase and a completed-session buffer. This is neither customer conversion nor an order/revenue count.

| Priority | Observed evidence | Recommended action and completion evidence |
|---|---|---|
| P0: measurement coverage | Unknown category: {unknown['eligible_groups']:,}/{overall['eligible_groups']:,} eligible groups ({share:.2f}%). | Analytics/catalog owner: audit product mappings and logging; deliver reconciled coverage and exception counts while preserving Unknown. |
| P1: TV journey | {tv['ordered_purchase_groups']:,}/{tv['eligible_groups']:,} ordered progression ({tv['ordered_purchase_pct']:.2f}%); view→cart {tv['view_to_cart_pct']:.2f}% versus {overall['view_to_cart_pct']:.2f}% overall. | Product/UX: review logging and sampled journeys; validate a specific friction hypothesis, then test it. Delivery-information clarity is a proposed hypothesis, not a finding. |
| P2: high-price context | Price 1000+ source units: {expensive['ordered_purchase_groups']:,}/{expensive['eligible_groups']:,} ({expensive['ordered_purchase_pct']:.2f}%). | Commercial/analytics: inspect category/product mix, exposure and instrumentation before proposing a price change. |

These are qualitative investigation priorities, not a financial-return ranking. Segments overlap and counts must not be added. Video cards show {gpu['ordered_purchase_pct']:.2f}% progression but a different stage pattern; they are not a randomized control for TVs. Missing labels, product mix, repeated users/products and incomplete logging can explain observed gaps. Unobserved progression is not proven abandonment or recoverable sales.

TV gaps versus its complement remain negative across seven declared measurement scenarios. The primary TV proportion has exploratory 95% marginal user-cluster interval {user_ci['low']:.3f}–{user_ci['high']:.3f}% and alternative product-cluster interval {product_ci['low']:.3f}–{product_ci['high']:.3f}%. Targets were selected after exploration; these are separate one-way sensitivity analyses, not joint adjustment, simultaneous intervals or evidence of a UX effect. Keep the primary definition fixed when comparing reports.

## Case B — Hillstrom: what does the actual experiment support?

All 64,000 assigned rows, including nonbuyers and zero spend, remain in the separate two-week historical analysis.

| Email versus no email | Purchase difference | 95% marginal interval | Holm p |
|---|---:|---:|---:|
| Mens merchandise | +{mens['difference_pp']:.4f} pp | [{mens['ci_low_pp']:.4f}, {mens['ci_high_pp']:.4f}] pp | {mens['p_holm']:.3g} |
| Womens merchandise | +{womens['difference_pp']:.4f} pp | [{womens['ci_low_pp']:.4f}, {womens['ci_high_pp']:.4f}] pp | {womens['p_holm']:.4g} |

Both primary comparisons pass the two-test Holm policy. The intervals are individual Newcombe–Wilson intervals, not Holm-adjusted simultaneous intervals. Secondary recorded-spend differences per assigned customer are +${ms['difference_dollars_per_assigned_customer']:.4f} [${ms['ci_low_dollars']:.4f}, ${ms['ci_high_dollars']:.4f}] and +${ws['difference_dollars_per_assigned_customer']:.4f} [${ws['ci_low_dollars']:.4f}, ${ws['ci_high_dollars']:.4f}], with exploratory 95% bootstrap intervals including zero-spend customers. Mens has the larger purchase estimate; its direct comparison with Womens remains exploratory. Merchandise labels do not describe customer gender. Historical assignment effects do not establish current campaign performance, optimal targeting, profit or ROI; costs and margins are absent. Do not transfer these effects to REES46.

## Next decision

Complete mapping/journey checks before testing a TV-page delivery-information module. The [future experiment appendix](11_future_experiment_plan.md) specifies customer randomization, seven-day outcomes, guardrails, sizing and stopping rules. Its 2% baseline and +0.4 pp MDE are explicit assumptions; the primary-only illustration requires {chosen['n_per_arm']:,} customers per arm. The historical 1.34% session-product rate is not this customer-level baseline. Re-estimate the baseline and size guardrails before launch. Proposed owners are hypothetical; no experiment has been run.

Evidence: [conversion diagnostics](07_conversion_diagnostics.md), [robustness](08_robustness.md), [historical experiment](09_ab_test.md), [decision register](11_decision_register.csv). Raw-source redistribution requires a source-specific review. The computation above is reproduced from the declared inputs.
"""
    (REPORTS / "11_executive_memo.md").write_text(memo)
    power_table = "\n".join(f"| +{x['absolute_mde_pp']:.1f} pp | {100*x['treatment_probability_at_mde']:.1f}% | {x['n_per_arm']:,} | {x['total_n']:,} |" for x in sizing)
    appendix = f"""# Future experiment appendix — TV delivery-information clarity

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
{power_table}

The independent-proportion normal approximation uses pooled null and unpooled alternative variance, without continuity correction. Integer search verifies power(n−1)<.8≤power(n); a separate two-tail expression agrees within 1e−12. This is primary-only sizing, not a launch-ready sample requirement. Guardrail baselines, verified-order baseline, eligible traffic, linkage quality and business margins remain prelaunch requirements. No invented daily traffic or promised calendar completion is used.

Code: `src/build_decision_memo.py`; actual calculation inputs, outputs and versions: [11_experiment_power.json](11_experiment_power.json). Reproduce with `/opt/anaconda3/bin/python src/build_decision_memo.py` from the project root. This refreshes Chapter 11 outputs; preserve personal edits first.

Method sources: [statsmodels independent-proportion power](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.power_proportions_2indep.html), [Microsoft Research SRM diagnosis](https://www.microsoft.com/en-us/research/publication/diagnosing-sample-ratio-mismatch-in-online-controlled-experiments-a-taxonomy-and-rules-of-thumb-for-practitioners/), [fixed-design inference discussion](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/06/ftir-online-evaluation-final-journal.pdf). Local execution uses statsmodels {statsmodels.__version__} and scipy {scipy.__version__}; linked documentation may describe a different release.
"""
    (REPORTS / "11_future_experiment_plan.md").write_text(appendix)
    assert all(sha(ROOT / name) == value for name, value in hashes.items())
    assert all(sha(ROOT / name) == value for name, value in frozen.items())
    completion = {"chapter": 11, "status": "complete: memo and proposed design only",
                  "input_sha256": hashes, "raw_model_contract_unchanged": frozen,
                  "code_sha256": sha(Path(__file__)),
                  "observed_counts": {"overall": overall, "unknown": unknown, "tv": tv,
                                      "price_1000_plus": expensive},
                  "future_experiment_executed": False, "future_baseline_is_assumed": True,
                  "power_checks_passed": True, "chosen_primary_sizing": chosen,
                  "memo_word_count": len(memo.split()),
                  "outputs": {str(p.relative_to(ROOT)): sha(p) for p in
                              [REPORTS / "11_executive_memo.md", REPORTS / "11_future_experiment_plan.md",
                               REPORTS / "11_decision_register.csv", power_path]},
                  "open_items": ["Contemporary baseline/traffic and guardrail sizing before any real test",
                                 "Source-rights review and Chapter 12 final reproducibility QA"]}
    (REPORTS / "11_completion_checks.json").write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"memo_words": len(memo.split()), "raw_model_contract_unchanged": True,
                      "primary_planning_example": chosen, "outputs": list(completion["outputs"])}, indent=2))


if __name__ == "__main__":
    main()
