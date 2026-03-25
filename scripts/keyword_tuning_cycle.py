#!/usr/bin/env python3
"""T8: Keyword tuning cycle for Grant Hunter v4.0.

Runs a keyword audit, proposes new keywords from suggestions, re-scores all
grants with the proposed keywords, and evaluates whether to commit the update.

Success criterion: recall for label>=2 grants improves by >= 5 percentage points.
Partial: 0-5pp improvement.
Failure: recall decreases -> rollback (keywords.json is NOT modified).

Usage:
    python scripts/keyword_tuning_cycle.py --dry-run
    python scripts/keyword_tuning_cycle.py
    python scripts/keyword_tuning_cycle.py --gold-set data/labels/gold_set.json
    python scripts/keyword_tuning_cycle.py --max-new-keywords 10
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

K = 10
RECALL_THRESHOLD = 0.15     # relevance_score floor for "passing threshold" recall
LABEL_THRESHOLD = 2         # gold label >= this counts as relevant
SUCCESS_DELTA = 0.05        # 5 percentage point improvement for success
DEFAULT_MAX_NEW_KW = 10

# ---------------------------------------------------------------------------
# Snapshot loading (shared logic with weight_ablation.py)
# ---------------------------------------------------------------------------


def _load_latest_snapshot(snapshot_dir: Path) -> List[Any]:
    """Load all grants from the most recent snapshot files in snapshot_dir."""
    from grant_hunter.models import Grant

    json_files = sorted(snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not json_files:
        return []

    source_latest: Dict[str, Path] = {}
    for f in json_files:
        stem = f.stem
        parts = stem.rsplit("_", 1)
        source = parts[0] if len(parts) == 2 else stem
        source_latest[source] = f

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
# Rescoring with alternative keywords
# ---------------------------------------------------------------------------


def _rescore_with_keywords(grants: List[Any], keywords: dict) -> List[Any]:
    """Return new Grant objects with relevance_score recomputed from *keywords*.

    Uses the scoring module directly, bypassing the cached keywords singleton.
    """
    import copy
    from grant_hunter.scoring import (
        _flatten,
        _keyword_score,
    )
    from grant_hunter.profiles import get_default_profile

    profile = get_default_profile()
    weights = dict(profile.weights)

    amr_kw = _flatten(keywords, "amr")
    ai_kw = _flatten(keywords, "ai")
    drug_kw = _flatten(keywords, "drug_discovery")

    rescored: List[Any] = []
    for g in grants:
        text = f"{g.title} {g.description} {' '.join(g.keywords)}"
        amr_s = _keyword_score(text, amr_kw)
        ai_s = _keyword_score(text, ai_kw)
        drug_s = _keyword_score(text, drug_kw)
        score = (
            weights["amr"] * amr_s
            + weights["ai"] * ai_s
            + weights.get("drug", weights.get("drug_discovery", 0.0)) * drug_s
        )
        score = round(min(score, 1.0), 6)

        # Shallow copy, replace relevance_score
        g2 = copy.copy(g)
        object.__setattr__(g2, "relevance_score", score)
        rescored.append(g2)

    return rescored


# ---------------------------------------------------------------------------
# Score distribution stats
# ---------------------------------------------------------------------------


def _score_distribution(grants: List[Any]) -> dict:
    scores = [g.relevance_score for g in grants]
    if not scores:
        return {"count": 0, "mean": 0.0, "std": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    scores_sorted = sorted(scores)
    n = len(scores_sorted)
    mean = sum(scores_sorted) / n
    variance = sum((s - mean) ** 2 for s in scores_sorted) / n
    std = variance ** 0.5

    def _percentile(sorted_vals: List[float], p: float) -> float:
        idx = (p / 100) * (len(sorted_vals) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(sorted_vals) - 1)
        frac = idx - lo
        return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac, 6)

    return {
        "count": n,
        "mean": round(mean, 6),
        "std": round(std, 6),
        "p25": _percentile(scores_sorted, 25),
        "p50": _percentile(scores_sorted, 50),
        "p75": _percentile(scores_sorted, 75),
        "p90": _percentile(scores_sorted, 90),
    }


# ---------------------------------------------------------------------------
# Recall for label>=2 grants passing threshold
# ---------------------------------------------------------------------------


def _recall_label2_passing(
    grants: List[Any],
    gold: Dict[str, int],
    score_threshold: float = RECALL_THRESHOLD,
) -> float:
    """Fraction of gold label>=2 grants whose relevance_score >= score_threshold."""
    relevant_ids = {gid for gid, lbl in gold.items() if lbl >= LABEL_THRESHOLD}
    if not relevant_ids:
        return 0.0
    passing = {g.id for g in grants if g.relevance_score >= score_threshold}
    hits = len(relevant_ids & passing)
    return round(hits / len(relevant_ids), 6)


def _precision_at_k(grants: List[Any], gold: Dict[str, int], k: int = K) -> float:
    """Precision@k using grants sorted by relevance_score descending."""
    from grant_hunter.gold_set import precision_at_k
    ranked_ids = [g.id for g in sorted(grants, key=lambda g: g.relevance_score, reverse=True)]
    return precision_at_k(ranked_ids, gold, k=k)


# ---------------------------------------------------------------------------
# Keywords mutation
# ---------------------------------------------------------------------------


def _build_proposed_keywords(
    current_keywords: dict,
    suggestions: List[dict],
    max_new: int,
) -> Tuple[dict, List[dict]]:
    """Return (proposed_keywords_dict, added_list).

    Takes the top *max_new* suggestions not already in current keywords and
    adds each to its suggested_category bucket under the "suggested" language key.
    """
    import copy
    from grant_hunter.scoring import _flatten

    proposed = copy.deepcopy(current_keywords)
    existing_flat = set()
    for cat in ("amr", "ai", "drug_discovery"):
        for kw in _flatten(current_keywords, cat):
            existing_flat.add(kw.lower())

    added: List[dict] = []
    for suggestion in suggestions[:max_new]:
        term = suggestion["term"]
        if term.lower() in existing_flat:
            continue
        cat = suggestion["suggested_category"]
        if cat not in proposed:
            proposed[cat] = {}
        if "suggested" not in proposed[cat]:
            proposed[cat]["suggested"] = []
        proposed[cat]["suggested"].append(term)
        existing_flat.add(term.lower())
        added.append({"term": term, "category": cat, "frequency": suggestion["frequency"]})

    return proposed, added


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------


def run_keyword_tuning_cycle(
    gold_set_path: Path,
    snapshot_dir: Path,
    output_path: Path,
    max_new_keywords: int = DEFAULT_MAX_NEW_KW,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run a single keyword tuning cycle.

    Parameters
    ----------
    gold_set_path:
        Path to gold_set.json.
    snapshot_dir:
        Directory containing snapshot JSON files.
    output_path:
        Where to save results JSON.
    max_new_keywords:
        Maximum number of new keywords to add per cycle.
    dry_run:
        If True, show plan without modifying any files.

    Returns
    -------
    Results dict (also saved to output_path).
    """
    from grant_hunter.gold_set import load_gold_set
    from grant_hunter.keyword_audit import generate_audit_report
    from grant_hunter.scoring import _get_keywords
    from grant_hunter.config import KEYWORDS_FILE

    # -- Dry run: show plan without loading data ------------------------------
    if dry_run:
        print(f"\n[DRY RUN] Keyword tuning cycle plan:")
        print(f"  Gold set:         {gold_set_path}")
        print(f"  Snapshot dir:     {snapshot_dir}")
        print(f"  keywords.json:    {KEYWORDS_FILE}")
        print(f"  Max new keywords: {max_new_keywords}")
        print(f"  Success criterion: recall (label>={LABEL_THRESHOLD}, score>={RECALL_THRESHOLD}) improves >= {SUCCESS_DELTA:.0%}")
        print(f"  Output would be saved to: {output_path}")
        print(f"\n  Steps:")
        print(f"    1. Load grants from snapshot dir")
        print(f"    2. Run keyword_audit.generate_audit_report()")
        print(f"    3. Add top {max_new_keywords} suggestions to proposed keywords.json")
        print(f"    4. Rescore all grants with proposed keywords")
        print(f"    5. Compare before/after: score distribution, precision@{K}, recall")
        print(f"    6. Verdict: success/partial -> write keywords.json; failure -> rollback")
        return {"dry_run": True}

    # -- Load gold set --------------------------------------------------------
    print(f"Loading gold set from {gold_set_path} ...")
    gold_labels = load_gold_set(gold_set_path)
    gold: Dict[str, int] = {e["grant_id"]: int(e["label"]) for e in gold_labels}
    print(f"  Loaded {len(gold)} labeled grants.")

    # -- Load grants ----------------------------------------------------------
    print(f"Loading grants from {snapshot_dir} ...")
    grants = _load_latest_snapshot(snapshot_dir)
    print(f"  Loaded {len(grants)} grants.")

    if not grants:
        print("[ERROR] No grants loaded.", file=sys.stderr)
        sys.exit(1)

    # -- Run keyword audit ----------------------------------------------------
    print("Running keyword audit ...")
    audit = generate_audit_report(grants)
    suggestions = audit["suggestions"]
    print(f"  Audit complete: {audit['summary']['suggestion_count']} suggestions, "
          f"{audit['summary']['false_negative_count']} false negatives detected.")

    # -- Current keywords & baseline scores -----------------------------------
    current_keywords = _get_keywords()

    before_dist = _score_distribution(grants)
    before_recall = _recall_label2_passing(grants, gold)
    before_p10 = _precision_at_k(grants, gold)

    print(f"\nBaseline:")
    print(f"  Score distribution: mean={before_dist['mean']:.4f}  std={before_dist['std']:.4f}")
    print(f"  Precision@{K}: {before_p10:.4f}")
    print(f"  Recall (label>=2, score>={RECALL_THRESHOLD}): {before_recall:.4f}")

    # -- Build proposed keywords ----------------------------------------------
    proposed_keywords, added_keywords = _build_proposed_keywords(
        current_keywords, suggestions, max_new_keywords
    )

    if not added_keywords:
        print("\n[INFO] No new keywords to add (all suggestions already present).")
        verdict = "no_change"
        after_dist = before_dist
        after_recall = before_recall
        after_p10 = before_p10
        delta_recall = 0.0
    else:
        print(f"\nProposed {len(added_keywords)} new keywords:")
        for a in added_keywords:
            print(f"  + [{a['category']}] {a['term']!r}  (freq={a['frequency']})")

        # -- Rescore with proposed keywords -----------------------------------
        print("\nRescoring grants with proposed keywords ...")
        rescored_grants = _rescore_with_keywords(grants, proposed_keywords)

        after_dist = _score_distribution(rescored_grants)
        after_recall = _recall_label2_passing(rescored_grants, gold)
        after_p10 = _precision_at_k(rescored_grants, gold)
        delta_recall = round(after_recall - before_recall, 6)

        print(f"\nAfter proposed keywords:")
        print(f"  Score distribution: mean={after_dist['mean']:.4f}  std={after_dist['std']:.4f}")
        print(f"  Precision@{K}: {after_p10:.4f}")
        print(f"  Recall (label>=2, score>={RECALL_THRESHOLD}): {after_recall:.4f}")
        print(f"  Delta recall: {delta_recall:+.4f}")

        # -- Verdict ----------------------------------------------------------
        if delta_recall >= SUCCESS_DELTA:
            verdict = "success"
        elif delta_recall >= 0.0:
            verdict = "partial"
        else:
            verdict = "failure"

    print(f"\nVerdict: {verdict.upper()}")

    # -- Apply update (success or partial) ------------------------------------
    keywords_updated = False
    backup_path: Optional[str] = None

    if verdict in ("success", "partial") and added_keywords:
        # Backup original
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = str(KEYWORDS_FILE.parent / f"keywords_backup_{ts}.json")
        shutil.copy2(str(KEYWORDS_FILE), backup_path)
        print(f"  Backed up original keywords.json -> {backup_path}")

        # Write updated keywords
        KEYWORDS_FILE.write_text(
            json.dumps(proposed_keywords, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  Updated {KEYWORDS_FILE}")
        keywords_updated = True

    elif verdict == "failure":
        print("  Rollback: keywords.json NOT modified (recall decreased).")

    elif verdict == "no_change":
        print("  No update needed.")

    # -- Build output ---------------------------------------------------------
    output: Dict[str, Any] = {
        "experiment": "keyword_tuning_cycle",
        "cycle": 1,
        "version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "k": K,
            "score_threshold": RECALL_THRESHOLD,
            "label_threshold": LABEL_THRESHOLD,
            "success_delta": SUCCESS_DELTA,
            "max_new_keywords": max_new_keywords,
            "gold_set_path": str(gold_set_path),
            "snapshot_dir": str(snapshot_dir),
            "keywords_file": str(KEYWORDS_FILE),
        },
        "gold_set_size": len(gold),
        "grant_count": len(grants),
        "audit_summary": audit["summary"],
        "top_suggestions": suggestions[:max_new_keywords],
        "added_keywords": added_keywords,
        "before": {
            "score_distribution": before_dist,
            "precision_at_10": round(before_p10, 6),
            "recall_label2_passing": round(before_recall, 6),
        },
        "after": {
            "score_distribution": after_dist,
            "precision_at_10": round(after_p10, 6),
            "recall_label2_passing": round(after_recall, 6),
        },
        "delta_recall": delta_recall if added_keywords else 0.0,
        "verdict": verdict,
        "keywords_updated": keywords_updated,
        "backup_path": backup_path,
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
        description="T8: Keyword tuning cycle — audit, propose, rescore, evaluate",
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
        default=_PROJECT_ROOT / "data" / "experiments" / "keyword_tuning_cycle1.json",
        help="Output path for results JSON (default: data/experiments/keyword_tuning_cycle1.json)",
    )
    parser.add_argument(
        "--max-new-keywords",
        type=int,
        default=DEFAULT_MAX_NEW_KW,
        help=f"Maximum new keywords to add per cycle (default: {DEFAULT_MAX_NEW_KW})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying any files",
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

    if args.dry_run and not args.snapshot_dir.exists():
        print(f"[DRY RUN] Snapshot dir not found at {args.snapshot_dir} — would fail on real run.")
        sys.exit(0)

    run_keyword_tuning_cycle(
        gold_set_path=args.gold_set,
        snapshot_dir=args.snapshot_dir,
        output_path=args.output,
        max_new_keywords=args.max_new_keywords,
        dry_run=args.dry_run,
    )
