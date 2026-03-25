#!/usr/bin/env python3
"""T5: Weight ablation experiment for Grant Hunter v4.0.

Tests 5 blending weight combinations (tfidf_w, llm_w) and selects the optimal
weights using NDCG@10 as primary criterion with recall@10 >= 80% constraint.

Usage:
    python scripts/weight_ablation.py --dry-run
    python scripts/weight_ablation.py
    python scripts/weight_ablation.py --gold-set data/labels/gold_set.json
    python scripts/weight_ablation.py --snapshot-dir data/snapshots --output data/experiments/weight_ablation.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEIGHT_COMBOS: List[Tuple[float, float]] = [
    (0.0, 1.0),
    (0.3, 0.7),
    (0.5, 0.5),
    (0.7, 0.3),
    (1.0, 0.0),
]

K = 10
N_BOOTSTRAP = 1000
RECALL_CONSTRAINT = 0.80
CI_LEVEL = 0.95
SEED = 42

# ---------------------------------------------------------------------------
# Snapshot loading
# ---------------------------------------------------------------------------


def _load_latest_snapshot(snapshot_dir: Path) -> List[Any]:
    """Load all grants from the most recent snapshot files in snapshot_dir.

    Snapshot files are named <source>_YYYYMMDD.json and contain a JSON array
    of grant dicts. All sources are merged into a single list, deduplicating
    by grant id (last-writer wins).
    """
    from grant_hunter.models import Grant

    json_files = sorted(snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not json_files:
        return []

    # Group by source prefix (e.g. "nih", "eu", "grants_gov") and pick latest
    source_latest: Dict[str, Path] = {}
    for f in json_files:
        stem = f.stem
        parts = stem.rsplit("_", 1)
        source = parts[0] if len(parts) == 2 else stem
        source_latest[source] = f  # overwrite keeps latest

    grants_by_id: Dict[str, Any] = {}
    for source, path in source_latest.items():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for d in raw:
                g = Grant.from_dict(d)
                grants_by_id[g.id] = g
        except Exception as exc:
            print(f"  [WARN] Could not load {path}: {exc}", file=sys.stderr)

    return list(grants_by_id.values())


# ---------------------------------------------------------------------------
# Blended ranking
# ---------------------------------------------------------------------------


def _blend_and_rank(
    grants: List[Any],
    tfidf_w: float,
    llm_w: float,
) -> List[str]:
    """Return grant IDs ranked by blended_score = tfidf_w * relevance_score + llm_w * llm_score.

    Grants without llm_score fall back to relevance_score for the blended value
    (i.e. llm_score is treated as relevance_score when unavailable).
    """
    scored: List[Tuple[float, str]] = []
    for g in grants:
        llm_s = getattr(g, "llm_score", None)
        if llm_s is None:
            # No LLM score: use tfidf only, normalised same range [0,1]
            blended = g.relevance_score
        else:
            blended = tfidf_w * g.relevance_score + llm_w * float(llm_s)
        scored.append((blended, g.id))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [gid for _, gid in scored]


# ---------------------------------------------------------------------------
# Multi-criteria selection
# ---------------------------------------------------------------------------


def _select_best(results: List[dict]) -> dict:
    """Apply multi-criteria selection:

    1. Primary: NDCG@10 maximum among combos with recall@10 >= RECALL_CONSTRAINT
    2. Fallback: best recall@10 among all combos if none satisfy constraint
    3. Tie-break: prefer higher tfidf_w (lower API cost)
    """
    compliant = [r for r in results if r["recall_at_10"] >= RECALL_CONSTRAINT]
    candidates = compliant if compliant else results

    best = max(
        candidates,
        key=lambda r: (r["ndcg_at_10"], r["tfidf_w"]),
    )
    return best


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------


def run_weight_ablation(
    gold_set_path: Path,
    snapshot_dir: Path,
    output_path: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the weight ablation experiment.

    Parameters
    ----------
    gold_set_path:
        Path to gold_set.json.
    snapshot_dir:
        Directory containing snapshot JSON files.
    output_path:
        Where to save results JSON.
    dry_run:
        If True, print plan without computing metrics.

    Returns
    -------
    Results dict (also saved to output_path).
    """
    from grant_hunter.gold_set import (
        load_gold_set,
        precision_at_k,
        recall_at_k,
        ndcg_at_k,
        bootstrap_ci,
    )

    # -- Dry run: show plan without loading data ------------------------------
    if dry_run:
        print("\n[DRY RUN] Would test the following weight combos:")
        for tfidf_w, llm_w in WEIGHT_COMBOS:
            print(f"  tfidf_w={tfidf_w:.1f}  llm_w={llm_w:.1f}")
        print(f"\nMetrics: precision@{K}, recall@{K}, NDCG@{K}")
        print(f"Bootstrap: {N_BOOTSTRAP} resamples, {int(CI_LEVEL*100)}% CI, seed={SEED}")
        print(f"Selection constraint: recall@{K} >= {RECALL_CONSTRAINT:.0%}")
        print(f"\nGold set path: {gold_set_path}")
        print(f"Snapshot dir:  {snapshot_dir}")
        print(f"Output would be saved to: {output_path}")
        return {"dry_run": True}

    # -- Load gold set --------------------------------------------------------
    print(f"Loading gold set from {gold_set_path} ...")
    gold_labels = load_gold_set(gold_set_path)
    gold: Dict[str, int] = {e["grant_id"]: int(e["label"]) for e in gold_labels}
    print(f"  Loaded {len(gold)} labeled grants.")

    # -- Load grants from snapshot -------------------------------------------
    print(f"Loading grants from snapshot dir: {snapshot_dir} ...")
    grants = _load_latest_snapshot(snapshot_dir)
    print(f"  Loaded {len(grants)} grants.")

    if not grants:
        print("[ERROR] No grants loaded from snapshot dir.", file=sys.stderr)
        sys.exit(1)

    # -- Run ablation ---------------------------------------------------------
    combo_results: List[dict] = []

    print(f"\nRunning ablation over {len(WEIGHT_COMBOS)} weight combos ...")
    print(f"{'tfidf_w':>8} {'llm_w':>7}  {'P@10':>7} {'R@10':>7} {'NDCG@10':>9}  CI_NDCG")
    print("-" * 70)

    for tfidf_w, llm_w in WEIGHT_COMBOS:
        ranked_ids = _blend_and_rank(grants, tfidf_w, llm_w)

        p10 = precision_at_k(ranked_ids, gold, k=K)
        r10 = recall_at_k(ranked_ids, gold, k=K)
        n10 = ndcg_at_k(ranked_ids, gold, k=K)

        # Bootstrap CI for NDCG@10
        _, ci_lo, ci_hi = bootstrap_ci(
            ndcg_at_k,
            ranked_ids,
            gold,
            k=K,
            n_bootstrap=N_BOOTSTRAP,
            ci=CI_LEVEL,
            seed=SEED,
        )
        # Bootstrap CI for recall@10
        _, r_ci_lo, r_ci_hi = bootstrap_ci(
            recall_at_k,
            ranked_ids,
            gold,
            k=K,
            n_bootstrap=N_BOOTSTRAP,
            ci=CI_LEVEL,
            seed=SEED,
        )
        # Bootstrap CI for precision@10
        _, p_ci_lo, p_ci_hi = bootstrap_ci(
            precision_at_k,
            ranked_ids,
            gold,
            k=K,
            n_bootstrap=N_BOOTSTRAP,
            ci=CI_LEVEL,
            seed=SEED,
        )

        print(
            f"{tfidf_w:>8.1f} {llm_w:>7.1f}  {p10:>7.4f} {r10:>7.4f} {n10:>9.4f}"
            f"  [{ci_lo:.4f}, {ci_hi:.4f}]"
        )

        combo_results.append({
            "tfidf_w": tfidf_w,
            "llm_w": llm_w,
            "precision_at_10": round(p10, 6),
            "recall_at_10": round(r10, 6),
            "ndcg_at_10": round(n10, 6),
            "ndcg_ci_lower": round(ci_lo, 6),
            "ndcg_ci_upper": round(ci_hi, 6),
            "recall_ci_lower": round(r_ci_lo, 6),
            "recall_ci_upper": round(r_ci_hi, 6),
            "precision_ci_lower": round(p_ci_lo, 6),
            "precision_ci_upper": round(p_ci_hi, 6),
        })

    # -- Multi-criteria selection ---------------------------------------------
    best = _select_best(combo_results)
    recall_constraint_met = best["recall_at_10"] >= RECALL_CONSTRAINT

    print("\n" + "=" * 70)
    print("SELECTION RESULT")
    print("=" * 70)
    print(f"Best combo: tfidf_w={best['tfidf_w']:.1f}, llm_w={best['llm_w']:.1f}")
    print(f"  NDCG@10:      {best['ndcg_at_10']:.4f}")
    print(f"  Recall@10:    {best['recall_at_10']:.4f}  (constraint {RECALL_CONSTRAINT:.0%}: {'MET' if recall_constraint_met else 'NOT MET — used fallback'})")
    print(f"  Precision@10: {best['precision_at_10']:.4f}")

    # -- Build output ---------------------------------------------------------
    output: Dict[str, Any] = {
        "experiment": "weight_ablation",
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "k": K,
            "n_bootstrap": N_BOOTSTRAP,
            "ci_level": CI_LEVEL,
            "recall_constraint": RECALL_CONSTRAINT,
            "seed": SEED,
            "gold_set_path": str(gold_set_path),
            "snapshot_dir": str(snapshot_dir),
        },
        "gold_set_size": len(gold),
        "grant_count": len(grants),
        "combo_results": combo_results,
        "best": {
            "tfidf_w": best["tfidf_w"],
            "llm_w": best["llm_w"],
            "ndcg_at_10": best["ndcg_at_10"],
            "recall_at_10": best["recall_at_10"],
            "precision_at_10": best["precision_at_10"],
            "recall_constraint_met": recall_constraint_met,
            "selection_note": (
                "Primary selection (NDCG maximised, recall >= 80%)"
                if recall_constraint_met
                else "Fallback selection (no combo met recall >= 80%; chose best recall)"
            ),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to {output_path}")

    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="T5: Weight ablation experiment — blending tfidf vs LLM scores",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--gold-set",
        type=Path,
        default=_PROJECT_ROOT / "data" / "labels" / "gold_set.json",
        help="Path to gold_set.json (default: data/labels/gold_set.json)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=_PROJECT_ROOT / "data" / "snapshots",
        help="Directory containing snapshot JSON files (default: data/snapshots)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_PROJECT_ROOT / "data" / "experiments" / "weight_ablation.json",
        help="Output path for results JSON (default: data/experiments/weight_ablation.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without computing metrics",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not args.dry_run and not args.gold_set.exists():
        print(f"[ERROR] Gold set file not found: {args.gold_set}", file=sys.stderr)
        print("Create gold set labels first, or use --dry-run.", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and not args.snapshot_dir.exists():
        print(f"[ERROR] Snapshot directory not found: {args.snapshot_dir}", file=sys.stderr)
        sys.exit(1)

    # Dry-run tolerates missing files; run_weight_ablation exits before data loading
    if args.dry_run:
        if not args.gold_set.exists():
            print(f"[DRY RUN] Note: gold set not found at {args.gold_set} — would fail on real run.")
        if not args.snapshot_dir.exists():
            print(f"[DRY RUN] Note: snapshot dir not found at {args.snapshot_dir} — would fail on real run.")

    run_weight_ablation(
        gold_set_path=args.gold_set,
        snapshot_dir=args.snapshot_dir,
        output_path=args.output,
        dry_run=args.dry_run,
    )
