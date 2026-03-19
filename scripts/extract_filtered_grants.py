#!/usr/bin/env python3
"""Extract filtered grants from latest snapshot for FP rate analysis.

Loads all snapshots, applies filter_grants(), and outputs a JSON file
with relevant fields for human annotation.
"""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grant_hunter.config import SNAPSHOTS_DIR
from grant_hunter.models import Grant
from grant_hunter.filters import filter_grants, passes_keyword_gate, _count_hits, AMR_KEYWORDS, AI_KEYWORDS, DRUG_KEYWORDS


def load_latest_snapshots() -> list[Grant]:
    """Load grants from the latest snapshot file per source (not all dates)."""
    grants = []
    if not SNAPSHOTS_DIR.exists():
        print(f"ERROR: Snapshot directory not found: {SNAPSHOTS_DIR}")
        sys.exit(1)

    # Group by source prefix, pick latest file per source
    source_files: dict[str, Path] = {}
    for snapshot_file in sorted(SNAPSHOTS_DIR.glob("*.json")):
        # e.g. nih_20260318.json → source = "nih"
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


def extract_grant_info(grant: Grant) -> dict:
    """Extract relevant fields for annotation."""
    searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"
    amr_hits, amr_matched = _count_hits(searchable, AMR_KEYWORDS)
    ai_hits, ai_matched = _count_hits(searchable, AI_KEYWORDS)
    drug_hits, drug_matched = _count_hits(searchable, DRUG_KEYWORDS)
    tier = passes_keyword_gate(grant)

    return {
        "id": grant.id,
        "title": grant.title,
        "description_snippet": (grant.description or "")[:300],
        "source": grant.source,
        "url": grant.url,
        "relevance_score": grant.relevance_score,
        "tier": tier,
        "matched_keywords": {
            "amr": amr_matched[:10],  # cap for readability
            "ai": ai_matched[:10],
            "drug": drug_matched[:5],
        },
        "amr_hits": amr_hits,
        "ai_hits": ai_hits,
        "drug_hits": drug_hits,
    }


def main():
    output_dir = Path(__file__).parent.parent / "data" / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "filtered_grants_all.json"

    print("Loading snapshots...")
    all_grants = load_latest_snapshots()
    print(f"  Loaded {len(all_grants)} grants from snapshots")

    print("Applying keyword filter...")
    filtered = filter_grants(all_grants)
    print(f"  {len(filtered)} grants passed filter")

    results = []
    for grant in filtered:
        info = extract_grant_info(grant)
        results.append(info)

    results.sort(key=lambda x: x["relevance_score"] or 0, reverse=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nExtracted {len(results)} grants to {output_path}")

    # Print tier distribution
    tier1 = sum(1 for r in results if r["tier"] == "tier1")
    tier2 = sum(1 for r in results if r["tier"] == "tier2")
    print(f"  Tier 1 (AMR+AI): {tier1}")
    print(f"  Tier 2 (AMR-only): {tier2}")

    # Print source distribution
    sources = {}
    for r in results:
        sources[r["source"]] = sources.get(r["source"], 0) + 1
    for src, count in sorted(sources.items()):
        print(f"  {src}: {count}")


if __name__ == "__main__":
    main()
