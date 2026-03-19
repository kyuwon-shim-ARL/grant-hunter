#!/usr/bin/env python3
"""Analyze FP labels and compute statistics with Wilson confidence intervals.

Reads fp_sample_80.json (after human annotation) and computes:
- Overall FP rate with 95% Wilson CI
- FP rate by tier (tier1 vs tier2)
- FP rate by source (NIH/EU/Grants.gov)
- Score distribution of FPs vs TPs
"""
import json
import math
import sys
from pathlib import Path


def wilson_ci(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for binomial proportion.

    Returns (lower, upper) bounds of 95% confidence interval.
    """
    if total == 0:
        return 0.0, 0.0

    p_hat = successes / total
    denominator = 1 + z**2 / total
    center = (p_hat + z**2 / (2 * total)) / denominator
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * total)) / total) / denominator

    return max(0.0, center - spread), min(1.0, center + spread)


def main():
    data_dir = Path(__file__).parent.parent / "data" / "validation"
    input_path = data_dir / "fp_sample_80.json"
    output_path = data_dir / "fp_analysis.md"

    if not input_path.exists():
        print(f"ERROR: Missing: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        grants = json.load(f)

    # Check annotation completeness
    unlabeled = [g for g in grants if g.get("label", {}).get("false_positive") is None]
    if unlabeled:
        print(f"WARNING: {len(unlabeled)} grants not yet labeled!")
        print("Please annotate all grants before running analysis.")
        print(f"Unlabeled IDs: {[g['id'] for g in unlabeled[:5]]}...")
        sys.exit(1)

    # Compute overall FP rate
    total = len(grants)
    fps = [g for g in grants if g["label"]["false_positive"]]
    fp_count = len(fps)
    fp_rate = fp_count / total if total > 0 else 0
    ci_low, ci_high = wilson_ci(fp_count, total)

    # By tier
    tier1 = [g for g in grants if g["tier"] == "tier1"]
    tier2 = [g for g in grants if g["tier"] == "tier2"]
    tier1_fps = [g for g in tier1 if g["label"]["false_positive"]]
    tier2_fps = [g for g in tier2 if g["label"]["false_positive"]]

    tier1_rate = len(tier1_fps) / len(tier1) if tier1 else 0
    tier2_rate = len(tier2_fps) / len(tier2) if tier2 else 0
    tier1_ci = wilson_ci(len(tier1_fps), len(tier1))
    tier2_ci = wilson_ci(len(tier2_fps), len(tier2))

    # By source
    sources = {}
    for g in grants:
        src = g["source"]
        if src not in sources:
            sources[src] = {"total": 0, "fp": 0}
        sources[src]["total"] += 1
        if g["label"]["false_positive"]:
            sources[src]["fp"] += 1

    # Score distribution
    fp_scores = [g["relevance_score"] for g in fps if g["relevance_score"] is not None]
    tp_scores = [g["relevance_score"] for g in grants if not g["label"]["false_positive"] and g["relevance_score"] is not None]

    # FP reasons
    reasons = {}
    for g in fps:
        reason = g["label"].get("fp_reason", "unspecified") or "unspecified"
        reasons[reason] = reasons.get(reason, 0) + 1

    def fmt_mean(scores):
        return f"{sum(scores)/len(scores):.3f}" if scores else "N/A"

    def fmt_min(scores):
        return f"{min(scores):.3f}" if scores else "N/A"

    def fmt_max(scores):
        return f"{max(scores):.3f}" if scores else "N/A"

    if ci_high < 0.10:
        verdict = "LLM unnecessary"
        next_steps = "- Current filtering is sufficient. No LLM needed.\n"
    elif ci_low > 0.20:
        verdict = "LLM justified"
        next_steps = "- Proceed to e058 (LLM Reranker implementation).\n"
    else:
        verdict = "Try rule improvements first"
        next_steps = "- Proceed to e057 (rule-based improvements) and re-measure.\n"

    # Generate report
    report = f"""# FP Rate Analysis Report

## Overall Results

| Metric | Value |
|--------|-------|
| Total sampled | {total} |
| False positives | {fp_count} |
| **FP Rate** | **{fp_rate:.1%}** |
| **95% Wilson CI** | **[{ci_low:.1%}, {ci_high:.1%}]** |

## Decision Matrix

| Condition | Action |
|-----------|--------|
| CI upper < 10% | LLM unnecessary — current filtering sufficient |
| CI lower > 20% | LLM justified — proceed to e058 |
| CI spans 10-20% | Try rule improvements (e057) first |

**Current verdict**: {verdict}

## By Tier

| Tier | Total | FP | FP Rate | 95% CI |
|------|-------|----|---------|--------|
| Tier 1 (AMR+AI) | {len(tier1)} | {len(tier1_fps)} | {tier1_rate:.1%} | [{tier1_ci[0]:.1%}, {tier1_ci[1]:.1%}] |
| Tier 2 (AMR-only) | {len(tier2)} | {len(tier2_fps)} | {tier2_rate:.1%} | [{tier2_ci[0]:.1%}, {tier2_ci[1]:.1%}] |

## By Source

| Source | Total | FP | FP Rate |
|--------|-------|----|---------|
"""
    for src, info in sorted(sources.items()):
        src_rate = info["fp"] / info["total"] if info["total"] > 0 else 0
        report += f"| {src} | {info['total']} | {info['fp']} | {src_rate:.1%} |\n"

    report += f"""
## Score Distribution

| Group | Count | Mean | Min | Max |
|-------|-------|------|-----|-----|
| True Positives | {len(tp_scores)} | {fmt_mean(tp_scores)} | {fmt_min(tp_scores)} | {fmt_max(tp_scores)} |
| False Positives | {len(fp_scores)} | {fmt_mean(fp_scores)} | {fmt_min(fp_scores)} | {fmt_max(fp_scores)} |

## FP Reasons

"""
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        report += f"- **{reason}**: {count} grants\n"

    report += f"""
## Next Steps

Based on FP rate = {fp_rate:.1%} (CI: [{ci_low:.1%}, {ci_high:.1%}]):
{next_steps}"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\nReport saved to {output_path}")


if __name__ == "__main__":
    main()
