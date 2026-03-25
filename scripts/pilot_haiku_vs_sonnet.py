#!/usr/bin/env python3
"""Pilot experiment: Haiku vs Sonnet ICC reliability comparison for Grant Hunter v4.0.

Loads a gold set, samples 10 grants via stratified sampling, scores each grant
3 times with both models (temperature=0), computes ICC(2,1) per model per
dimension, and applies a go/no-go decision tree.

Usage:
    python scripts/pilot_haiku_vs_sonnet.py
    python scripts/pilot_haiku_vs_sonnet.py --gold-set-path data/labels/gold_set.json
    python scripts/pilot_haiku_vs_sonnet.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20241022",
}

DIMENSIONS = ["research_alignment", "institutional_fit", "strategic_value", "feasibility"]

N_RUNS = 3          # repetitions per model per grant
N_SAMPLE = 10       # grants to include in pilot

# ICC decision thresholds
ICC_ADOPT = 0.70
ICC_EXPAND = 0.50

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Stratified sample (by gold label 0-3)
# ---------------------------------------------------------------------------


def stratified_sample(gold_labels: List[dict], n: int = N_SAMPLE) -> List[dict]:
    """Return at most *n* gold entries via stratified sampling over labels 0-3.

    Tries to pick 2-3 entries per label class. If a class has fewer than
    the requested quota, remaining slots are filled from other classes.
    """
    buckets: Dict[int, List[dict]] = {0: [], 1: [], 2: [], 3: []}
    for entry in gold_labels:
        lbl = int(entry["label"])
        if lbl in buckets:
            buckets[lbl].append(entry)

    # Base quota: floor(n / 4) per class, minimum 1 if class non-empty
    base = max(1, n // 4)
    selected: List[dict] = []
    remainder: List[dict] = []

    for lbl in (0, 1, 2, 3):
        bucket = buckets[lbl]
        take = min(base, len(bucket))
        selected.extend(bucket[:take])
        remainder.extend(bucket[take:])

    # Fill remaining slots from leftover items
    slots_left = n - len(selected)
    if slots_left > 0:
        selected.extend(remainder[:slots_left])

    return selected[:n]


# ---------------------------------------------------------------------------
# ICC(2,1) implementation
# ---------------------------------------------------------------------------


def compute_icc_2_1(ratings: List[List[float]]) -> float:
    """Compute ICC(2,1) — two-way random, single measures.

    Parameters
    ----------
    ratings:
        List of length n (subjects). Each element is a list of k rater scores.
        All rows must have the same length k.

    Returns
    -------
    ICC(2,1) value. Returns 0.0 when variance is zero (all scores identical).

    Formula
    -------
    ICC(2,1) = (BMS - EMS) / (BMS + (k-1)*EMS + k*(JMS-EMS)/n)

    where:
      BMS = between-subjects mean square
      JMS = between-judges (raters) mean square
      EMS = error mean square
      k   = number of raters
      n   = number of subjects
    """
    n = len(ratings)
    if n == 0:
        return 0.0
    k = len(ratings[0])
    if k <= 1:
        return 0.0

    # Grand mean
    all_vals = [v for row in ratings for v in row]
    grand_mean = sum(all_vals) / (n * k)

    # Row means (subject means)
    row_means = [sum(row) / k for row in ratings]

    # Column means (rater means)
    col_means = [sum(ratings[i][j] for i in range(n)) / n for j in range(k)]

    # SS between subjects
    ss_bms = k * sum((rm - grand_mean) ** 2 for rm in row_means)

    # SS between judges
    ss_jms = n * sum((cm - grand_mean) ** 2 for cm in col_means)

    # SS total
    ss_total = sum((ratings[i][j] - grand_mean) ** 2 for i in range(n) for j in range(k))

    # SS error
    ss_ems = ss_total - ss_bms - ss_jms

    # Degrees of freedom
    df_bms = n - 1
    df_jms = k - 1
    df_ems = (n - 1) * (k - 1)

    if df_bms == 0 or df_ems == 0:
        return 0.0

    bms = ss_bms / df_bms
    jms = ss_jms / df_jms if df_jms > 0 else 0.0
    ems = ss_ems / df_ems

    denominator = bms + (k - 1) * ems + k * (jms - ems) / n
    if denominator == 0.0:
        return 0.0

    icc = (bms - ems) / denominator
    return round(icc, 6)


# ---------------------------------------------------------------------------
# Go/no-go decision logic
# ---------------------------------------------------------------------------


def apply_decision_tree(icc_haiku: float, icc_sonnet: float) -> Dict[str, Any]:
    """Apply the go/no-go decision tree for a single dimension.

    Returns a dict with keys: haiku_decision, sonnet_decision, recommendation.
    """

    def _decide(icc: float) -> str:
        if icc >= ICC_ADOPT:
            return "adopt"
        if icc >= ICC_EXPAND:
            return "expand_pilot"
        return "rubric_redesign"

    haiku_dec = _decide(icc_haiku)
    sonnet_dec = _decide(icc_sonnet)

    # Recommendation logic
    if haiku_dec == "adopt" and sonnet_dec == "adopt":
        recommendation = "use_haiku"  # cost advantage
    elif haiku_dec == "adopt":
        recommendation = "use_haiku"
    elif sonnet_dec == "adopt":
        recommendation = "use_sonnet"
    elif haiku_dec == "expand_pilot" or sonnet_dec == "expand_pilot":
        recommendation = "expand_pilot_20_grants"
    else:
        recommendation = "rubric_redesign"

    return {
        "haiku_decision": haiku_dec,
        "sonnet_decision": sonnet_dec,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# LLM scoring (single grant, single call)
# ---------------------------------------------------------------------------

SCORING_PROMPT_TEMPLATE = """\
You are a grant-funding expert helping IPK (International Pathogen Korea), a private \
non-profit research institute in South Korea, identify the most relevant grants.

IPK PROFILE:
- Focus: Antimicrobial resistance (AMR), AI-driven drug discovery
- Capabilities: Wet-lab (BSL-2/3), computational biology, bioinformatics
- Korea is a Horizon Europe Pillar II associate country (since 2025-07)
- Eligible for NIH R01, R21, U01, P01 as foreign institution
- NOT eligible for: US-domestic-only grants, LMIC-targeted grants, university-only grants

Score each grant on FOUR dimensions (each 1-5 integer):

1. research_alignment (weight 0.40):
   "이 grant가 AMR×AI×Drug Discovery 교차점에 얼마나 위치하는가?"
   5 = AI/ML로 AMR/내성 해결을 명시적으로 요구
   3 = AMR 관련이나 AI 접근 암시적
   1 = 접선적 관련

2. institutional_fit (weight 0.25):
   "IPK(한국 비영리 연구소)가 자연스러운 지원자인가?"
   5 = 국제 비영리 연구소 환영 명시
   3 = 제한 불명확
   1 = 명백히 부적격

3. strategic_value (weight 0.20):
   "수주 시 IPK 포지셔닝에 기여하는가?"
   5 = 대형 펀딩+신규 협력+고프로필
   3 = 중간 규모+일반적
   1 = 소규모+루틴

4. feasibility (weight 0.15):
   "현실적으로 지원 가능한가?"
   5 = 충분한 일정+적절 경쟁도+보유 자원
   3 = 도전적이나 가능
   1 = 비현실적

Return a JSON array with one object per grant, in the same order as input.
Each object must have:
  - grant_id: string (the id field from input)
  - research_alignment: integer 1-5
  - institutional_fit: integer 1-5
  - strategic_value: integer 1-5
  - feasibility: integer 1-5
  - rationale: string (1-2 sentences explaining the scores)

GRANTS TO SCORE:
{grants_json}
"""


def _score_grants_once(
    client: Any,
    model: str,
    grants_data: List[dict],
) -> Optional[List[dict]]:
    """Call the LLM to score a list of grants once. Returns parsed list or None on error."""
    grants_json = json.dumps(grants_data, ensure_ascii=False, indent=2)
    prompt = SCORING_PROMPT_TEMPLATE.format(grants_json=grants_json)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        print(f"    [ERROR] API call failed: {exc}", file=sys.stderr)
        return None

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip().startswith("```") else len(lines)
        text = "\n".join(lines[1:end])

    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            print(f"    [ERROR] Expected JSON array, got {type(parsed)}", file=sys.stderr)
            return None
        return parsed
    except json.JSONDecodeError as exc:
        print(f"    [ERROR] JSON parse failed: {exc}", file=sys.stderr)
        return None


def _grant_to_prompt_dict(entry: dict) -> dict:
    """Convert a gold set entry to a minimal dict for LLM scoring.

    Gold set entries have: grant_id, label, labeler, timestamp, rubric_version.
    We use grant_id as id and try to include any available text fields.
    """
    return {
        "id": entry["grant_id"],
        "title": entry.get("title", entry["grant_id"]),
        "description": entry.get("description", ""),
        "agency": entry.get("agency", ""),
        "keywords": entry.get("keywords", []),
    }


# ---------------------------------------------------------------------------
# Main experiment runner
# ---------------------------------------------------------------------------


def run_pilot(
    gold_set_path: Path,
    output_path: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the full Haiku vs Sonnet pilot experiment.

    Parameters
    ----------
    gold_set_path:
        Path to gold_set.json.
    output_path:
        Where to save the results JSON.
    dry_run:
        If True, show what would be done without making API calls.

    Returns
    -------
    Results dict (also saved to output_path).
    """
    # -- Load gold set --------------------------------------------------------
    print(f"Loading gold set from {gold_set_path} ...")
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))
    from grant_hunter.gold_set import load_gold_set  # noqa: PLC0415

    gold_labels = load_gold_set(gold_set_path)
    print(f"  Loaded {len(gold_labels)} labeled grants.")

    # -- Stratified sample ----------------------------------------------------
    sample = stratified_sample(gold_labels, n=N_SAMPLE)
    print(f"  Sampled {len(sample)} grants (stratified by label 0-3).")

    label_dist: Dict[int, int] = {}
    for entry in sample:
        lbl = int(entry["label"])
        label_dist[lbl] = label_dist.get(lbl, 0) + 1
    print(f"  Label distribution: {dict(sorted(label_dist.items()))}")

    if dry_run:
        print("\n[DRY RUN] Would score each grant 3 times with:")
        for name, model_id in MODELS.items():
            print(f"  - {name}: {model_id}")
        print(f"\nGrants that would be scored ({len(sample)}):")
        for e in sample:
            print(f"  grant_id={e['grant_id']}  label={e['label']}")
        print("\nOutput would be saved to:", output_path)
        return {"dry_run": True, "sample_size": len(sample), "label_dist": label_dist}

    # -- Import Anthropic ------------------------------------------------------
    try:
        import anthropic
    except ImportError:
        print("[ERROR] anthropic package not installed. Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    # -- Score each grant N_RUNS times per model ------------------------------
    # Structure: scores[model_name][grant_id][run_idx][dimension] = int
    scores: Dict[str, Dict[str, List[Dict[str, int]]]] = {
        name: {e["grant_id"]: [] for e in sample}
        for name in MODELS
    }
    grants_prompt_data = [_grant_to_prompt_dict(e) for e in sample]

    for name, model_id in MODELS.items():
        print(f"\nScoring with {name} ({model_id}) — {N_RUNS} runs ...")
        for run_idx in range(N_RUNS):
            print(f"  Run {run_idx + 1}/{N_RUNS} ...", end=" ", flush=True)
            result = _score_grants_once(client, model_id, grants_prompt_data)
            if result is None:
                print("FAILED — skipping run.")
                # Fill with None placeholders so ICC can detect incomplete data
                for e in sample:
                    scores[name][e["grant_id"]].append(None)  # type: ignore[arg-type]
                continue

            scored_map = {str(item.get("grant_id", "")): item for item in result}
            run_errors = 0
            for e in sample:
                gid = e["grant_id"]
                item = scored_map.get(gid)
                if item is None:
                    run_errors += 1
                    scores[name][gid].append(None)  # type: ignore[arg-type]
                else:
                    dim_scores = {d: int(item.get(d, 3)) for d in DIMENSIONS}
                    scores[name][gid].append(dim_scores)

            print(f"OK{(' (%d errors)' % run_errors) if run_errors else ''}")

            # Brief pause to avoid rate limits between runs
            if run_idx < N_RUNS - 1:
                time.sleep(1.0)

    # -- Compute ICC per model per dimension ----------------------------------
    print("\nComputing ICC(2,1) ...")
    icc_results: Dict[str, Dict[str, float]] = {}

    for name in MODELS:
        icc_results[name] = {}
        for dim in DIMENSIONS:
            # Build ratings matrix: rows=grants, cols=runs
            ratings: List[List[float]] = []
            for e in sample:
                gid = e["grant_id"]
                run_scores = scores[name][gid]
                row = []
                for rs in run_scores:
                    if rs is None:
                        row.append(3.0)  # impute with midpoint on failure
                    else:
                        row.append(float(rs[dim]))
                if len(row) == N_RUNS:
                    ratings.append(row)

            icc = compute_icc_2_1(ratings) if len(ratings) >= 2 else 0.0
            icc_results[name][dim] = icc
            print(f"  {name:7s}  {dim:22s}  ICC={icc:.4f}")

    # -- Mean ICC per model ---------------------------------------------------
    mean_icc: Dict[str, float] = {}
    for name in MODELS:
        vals = list(icc_results[name].values())
        mean_icc[name] = round(sum(vals) / len(vals), 6) if vals else 0.0

    # -- Apply decision tree per dimension ------------------------------------
    decisions: Dict[str, Dict[str, Any]] = {}
    for dim in DIMENSIONS:
        decisions[dim] = apply_decision_tree(
            icc_results["haiku"][dim],
            icc_results["sonnet"][dim],
        )

    # Overall decision based on mean ICC
    overall = apply_decision_tree(mean_icc["haiku"], mean_icc["sonnet"])
    overall["mean_icc_haiku"] = mean_icc["haiku"]
    overall["mean_icc_sonnet"] = mean_icc["sonnet"]

    # -- Print summary --------------------------------------------------------
    print("\n" + "=" * 60)
    print("PILOT RESULTS SUMMARY")
    print("=" * 60)
    print(f"{'Model':<10} {'Mean ICC':>10}  {'Decision'}")
    print("-" * 40)
    for name in MODELS:
        dec = apply_decision_tree(mean_icc[name], mean_icc[name])["haiku_decision"]
        print(f"{name:<10} {mean_icc[name]:>10.4f}  {dec}")
    print()
    print(f"Overall recommendation: {overall['recommendation']}")
    print()
    print("Per-dimension breakdown:")
    print(f"  {'Dimension':<25} {'Haiku ICC':>10} {'Sonnet ICC':>11}  Recommendation")
    print("  " + "-" * 65)
    for dim in DIMENSIONS:
        h_icc = icc_results["haiku"][dim]
        s_icc = icc_results["sonnet"][dim]
        rec = decisions[dim]["recommendation"]
        print(f"  {dim:<25} {h_icc:>10.4f} {s_icc:>11.4f}  {rec}")

    # -- Build output dict ----------------------------------------------------
    output: Dict[str, Any] = {
        "experiment": "haiku_vs_sonnet_pilot",
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "models": MODELS,
            "n_runs": N_RUNS,
            "n_sample": N_SAMPLE,
            "icc_thresholds": {"adopt": ICC_ADOPT, "expand_pilot": ICC_EXPAND},
            "gold_set_path": str(gold_set_path),
        },
        "sample": [
            {"grant_id": e["grant_id"], "label": e["label"]}
            for e in sample
        ],
        "label_distribution": label_dist,
        "icc_per_model_per_dimension": icc_results,
        "mean_icc_per_model": mean_icc,
        "decisions_per_dimension": decisions,
        "overall_decision": overall,
        "raw_scores": {
            name: {
                gid: [rs for rs in run_list]
                for gid, run_list in model_scores.items()
            }
            for name, model_scores in scores.items()
        },
    }

    # -- Save results ---------------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to {output_path}")

    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Haiku vs Sonnet pilot experiment — ICC reliability for Grant Hunter v4.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--gold-set-path",
        type=Path,
        default=_PROJECT_ROOT / "data" / "labels" / "gold_set.json",
        help="Path to gold_set.json (default: data/labels/gold_set.json)",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=_PROJECT_ROOT / "data" / "experiments" / "pilot_haiku_vs_sonnet.json",
        help="Output path for results JSON (default: data/experiments/pilot_haiku_vs_sonnet.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making API calls",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not args.gold_set_path.exists() and not args.dry_run:
        print(f"[ERROR] Gold set file not found: {args.gold_set_path}", file=sys.stderr)
        print("Run gold set labeling first, or use --dry-run to preview.", file=sys.stderr)
        sys.exit(1)

    # Dry run does not need the file to exist
    if args.dry_run and not args.gold_set_path.exists():
        print(f"[DRY RUN] Gold set file not found at {args.gold_set_path} — would fail on real run.")
        sys.exit(0)

    run_pilot(
        gold_set_path=args.gold_set_path,
        output_path=args.output_path,
        dry_run=args.dry_run,
    )
