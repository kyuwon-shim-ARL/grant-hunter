#!/usr/bin/env python3
"""Export currently-unscored grants to a JSON file for subagent LLM scoring.

Loads the latest snapshot per source, applies the keyword filter, then
excludes grants already covered by a fresh subagent_scores_*.json file
(see grant_hunter.reranker.load_external_scores). The remaining grants are
written to data/scores/unscored_grants_<YYYY-MM-DD>.json.

A Claude Code subagent (per project preference: Agent(subagent_type=
"oh-my-claudecode:scientist"), NOT the Anthropic API from the pipeline)
should read that file, score each grant on the 4 dimensions described in
grant_hunter.reranker.SCORING_PROMPT_TEMPLATE, and write the results to
data/scores/subagent_scores_<YYYY-MM-DD>.json in the format:

{
  "scored_at": "<ISO8601>",
  "scorer": "subagent:<model>",
  "prompt_version": "<any tag>",
  "grants": [
    {"grant_id": "...", "research_alignment": 1-5, "institutional_fit": 1-5,
     "strategic_value": 1-5, "feasibility": 1-5, "rationale": "..."},
    ...
  ]
}

Usage:
    uv run python scripts/export_unscored_grants.py
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grant_hunter.config import SNAPSHOTS_DIR, DATA_HOME
from grant_hunter.models import Grant
from grant_hunter.filters import filter_grants
from grant_hunter.reranker import load_external_scores, EXTERNAL_SCORES_MAX_AGE_DAYS, _grant_to_prompt_dict


def load_latest_snapshots() -> list[Grant]:
    """Load grants from the latest snapshot file per source."""
    grants = []
    if not SNAPSHOTS_DIR.exists():
        print(f"ERROR: Snapshot directory not found: {SNAPSHOTS_DIR}")
        sys.exit(1)

    source_files: dict[str, Path] = {}
    for snapshot_file in sorted(SNAPSHOTS_DIR.glob("*.json")):
        source = snapshot_file.stem.rsplit("_", 1)[0]
        source_files[source] = snapshot_file  # sorted: last = latest

    for source, snapshot_file in source_files.items():
        try:
            with open(snapshot_file, encoding="utf-8") as f:
                data = json.load(f)
            print(f"  {source}: {snapshot_file.name} ({len(data)} grants)")
            for item in data:
                grants.append(Grant.from_dict(item))
        except Exception as e:
            print(f"WARNING: Failed to load {snapshot_file}: {e}")

    return grants


def main():
    output_dir = DATA_HOME / "scores"
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    output_path = output_dir / f"unscored_grants_{today}.json"

    print("Loading snapshots...")
    all_grants = load_latest_snapshots()
    print(f"  Loaded {len(all_grants)} grants from snapshots")

    print("Applying keyword filter...")
    filtered = filter_grants(all_grants)
    print(f"  {len(filtered)} grants passed filter")

    print("Checking existing (non-stale) subagent scores...")
    existing = load_external_scores(max_age_days=EXTERNAL_SCORES_MAX_AGE_DAYS)
    print(f"  {len(existing)} grants already covered by a fresh scores file")

    unscored = [g for g in filtered if g.id not in existing]
    print(f"  {len(unscored)} grants need scoring")

    results = [_grant_to_prompt_dict(g) for g in unscored]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nExported {len(results)} unscored grants to {output_path}")
    print(
        "\nNext step: have a Claude Code subagent score these grants and write "
        f"the results to {output_dir / f'subagent_scores_{today}.json'} "
        "(see this script's module docstring for the expected format)."
    )


if __name__ == "__main__":
    main()
