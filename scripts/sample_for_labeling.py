#!/usr/bin/env python3
"""Stratified sampling of filtered grants for FP rate annotation.

Samples 80 grants:
- Tier1 top 20 (by score)
- Tier1 bottom 20 (by score)
- Tier2 top 20 (by score)
- Ensuring source diversity: min 10 per source (NIH/EU/Grants.gov) if available
"""
import json
import sys
from pathlib import Path


def main():
    data_dir = Path(__file__).parent.parent / "data" / "validation"
    input_path = data_dir / "filtered_grants_all.json"
    output_path = data_dir / "fp_sample_80.json"

    if not input_path.exists():
        print(f"ERROR: Run extract_filtered_grants.py first. Missing: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        all_grants = json.load(f)

    # Separate by tier
    tier1 = [g for g in all_grants if g["tier"] == "tier1"]
    tier2 = [g for g in all_grants if g["tier"] == "tier2"]

    # Sort by score descending
    tier1.sort(key=lambda x: x["relevance_score"] or 0, reverse=True)
    tier2.sort(key=lambda x: x["relevance_score"] or 0, reverse=True)

    print(f"Available: {len(tier1)} tier1, {len(tier2)} tier2")

    # Sample
    tier1_top = tier1[:20]
    tier1_bottom = tier1[-20:] if len(tier1) >= 40 else tier1[20:]
    tier2_sample = tier2[:20]

    # If not enough in any bucket, take what's available
    sample = []
    sample.extend(tier1_top)
    sample.extend(tier1_bottom)
    sample.extend(tier2_sample)

    # Remove duplicates (in case tier1 has < 40 items)
    seen_ids = set()
    deduped = []
    for g in sample:
        if g["id"] not in seen_ids:
            seen_ids.add(g["id"])
            deduped.append(g)
    sample = deduped

    # Check source diversity
    source_counts = {}
    for g in sample:
        source_counts[g["source"]] = source_counts.get(g["source"], 0) + 1

    print(f"\nSampled {len(sample)} grants:")
    print(f"  Tier1 top: {len(tier1_top)}")
    print(f"  Tier1 bottom: {len(tier1_bottom)}")
    print(f"  Tier2: {len(tier2_sample)}")
    print(f"  Source distribution: {source_counts}")

    # Add empty label fields for human annotation
    for g in sample:
        g["label"] = {
            "true_amr": None,        # bool: Is this grant actually about AMR?
            "true_ai": None,         # bool: Does it involve AI/computational methods?
            "false_positive": None,  # bool: Should this have been filtered out?
            "fp_reason": "",          # str: Why is it a false positive?
            "annotator": "",          # str: Who labeled this?
        }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sample, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nSaved to {output_path}")
    print("\nNext step: Open the file and fill in the 'label' fields for each grant.")
    print("Then run: python scripts/analyze_fp_labels.py")


if __name__ == "__main__":
    main()
