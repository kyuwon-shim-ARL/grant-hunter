"""Tests for LLM reranker default-enabled + recall regression gate.

T3 requirements:
- LLM_RERANK_ENABLED defaults to True (no env var set)
- gold set label=2 items all appear in top-50 (recall@50 = 100%)
- Precision@10 >= 50% absolute value
- gold set >= 5 items required before gate is active

NOTE: These tests do not invoke the actual LLM/Anthropic API.
      They verify config defaults and metric logic using mock ranked lists.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch


class TestLLMRerankerDefaultEnabled:
    def test_config_default_is_true(self):
        """LLM_RERANK_ENABLED must default to True when env var is unset."""
        # Reload config without the env var
        env = {k: v for k, v in os.environ.items() if k != "GRANT_HUNTER_LLM_RERANK"}
        with patch.dict(os.environ, env, clear=True):
            import importlib
            import grant_hunter.config as cfg
            importlib.reload(cfg)
            assert cfg.LLM_RERANK_ENABLED is True, (
                "LLM_RERANK_ENABLED must default to True — "
                "cost is $0.004/day max, well within $1/month budget"
            )

    def test_reranker_module_default_is_true(self):
        """reranker.py module-level LLM_RERANK_ENABLED must also default True."""
        env = {k: v for k, v in os.environ.items() if k != "GRANT_HUNTER_LLM_RERANK"}
        with patch.dict(os.environ, env, clear=True):
            import importlib
            import grant_hunter.reranker as rr
            importlib.reload(rr)
            assert rr.LLM_RERANK_ENABLED is True

    def test_env_override_false_respected(self):
        """GRANT_HUNTER_LLM_RERANK=false must disable reranker."""
        with patch.dict(os.environ, {"GRANT_HUNTER_LLM_RERANK": "false"}):
            import importlib
            import grant_hunter.config as cfg
            importlib.reload(cfg)
            assert cfg.LLM_RERANK_ENABLED is False


class TestRecallRegressionGate:
    """Verify recall@50 = 100% for gold set items in a ranked list.

    R5-M1 note: T3 activation requires gold set >= 5 items (checked below).
    """

    def _load_gold_ids(self, path: Path) -> list[str]:
        """Return grant IDs with label >= 2 from gold set file."""
        items = json.loads(path.read_text())
        return [item["grant_id"] for item in items if item.get("label", 0) >= 2]

    def test_gold_set_has_minimum_items(self):
        """Gold set must contain >= 5 items before recall gate is active."""
        gold_path = Path("data/labels/gold_set.json")
        assert gold_path.exists(), (
            "data/labels/gold_set.json must exist. "
            "Run T1 gold set bootstrap before enabling T3."
        )
        items = json.loads(gold_path.read_text())
        relevant = [i for i in items if i.get("label", 0) >= 2]
        assert len(relevant) >= 5, (
            f"Gold set has only {len(relevant)} relevant items (need >= 5). "
            "Bootstrap more labels before enabling LLM reranker gate."
        )

    def test_recall_at_50_perfect_when_gold_in_top(self):
        """recall@50 = 1.0 when all gold items appear in top-50 ranked list."""
        from grant_hunter.gold_set import recall_at_k

        gold_path = Path("data/labels/gold_set.json")
        if not gold_path.exists():
            return  # Skip if no gold set yet (T1 prerequisite)

        gold_ids = self._load_gold_ids(gold_path)
        if len(gold_ids) < 5:
            return  # Skip if insufficient items

        # Simulate perfect ranking: all gold items in top-50
        gold_dict = {gid: 2 for gid in gold_ids}
        # Build ranked list: gold items first, then filler
        filler = [f"FILLER-{i}" for i in range(50 - len(gold_ids))]
        ranked = gold_ids + filler

        recall = recall_at_k(ranked, gold_dict, k=50)
        assert recall == 1.0, f"recall@50 must be 1.0, got {recall}"

    def test_recall_at_50_fails_when_gold_missing(self):
        """recall@50 < 1.0 when gold items are NOT in top-50 (gate catches regression)."""
        from grant_hunter.gold_set import recall_at_k

        gold_dict = {"GOLD-1": 2, "GOLD-2": 2, "GOLD-3": 2}
        # Gold items not present in ranked list
        ranked = [f"IRRELEVANT-{i}" for i in range(50)]

        recall = recall_at_k(ranked, gold_dict, k=50)
        assert recall == 0.0, "Should detect missing gold items"

    def test_precision_at_10_absolute_threshold(self):
        """Precision@10 >= 0.5 must be met as absolute value (not just vs baseline)."""
        from grant_hunter.gold_set import precision_at_k

        # Simulate a ranked list where 6/10 top results are relevant
        gold_dict = {f"GOLD-{i}": 2 for i in range(6)}
        gold_dict.update({f"IRREL-{i}": 0 for i in range(4)})
        ranked = [f"GOLD-{i}" for i in range(6)] + [f"IRREL-{i}" for i in range(4)]

        p10 = precision_at_k(ranked, gold_dict, k=10)
        assert p10 >= 0.5, f"Precision@10 {p10:.2f} < 0.50 threshold"

    def test_precision_at_10_fails_below_threshold(self):
        """Gate correctly rejects ranking where Precision@10 < 0.5."""
        from grant_hunter.gold_set import precision_at_k

        # Only 3/10 top results are relevant (30%)
        gold_dict = {f"GOLD-{i}": 2 for i in range(3)}
        ranked = [f"GOLD-{i}" for i in range(3)] + [f"IRREL-{i}" for i in range(7)]

        p10 = precision_at_k(ranked, gold_dict, k=10)
        assert p10 < 0.5, f"Expected p10 < 0.5 for low-quality ranking, got {p10}"
