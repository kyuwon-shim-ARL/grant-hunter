"""LLM-based reranker for grant scoring using 4-dimension structured evaluation.

Uses Anthropic Claude to score grants on research_alignment, institutional_fit,
strategic_value, and feasibility dimensions. Results are cached for 90 days.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from grant_hunter.config import DATA_HOME
from grant_hunter.models import Grant

if TYPE_CHECKING:
    from grant_hunter.profiles import ResearcherProfile

logger = logging.getLogger(__name__)

# ── Anthropic SDK (optional dependency) ──────────────────────────────────────

try:
    import anthropic as _anthropic_mod

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_mod = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False
    logger.warning(
        "anthropic package not installed; LLM reranker disabled. "
        "Install with: pip install anthropic"
    )

# ── Config ────────────────────────────────────────────────────────────────────

LLM_RERANK_ENABLED: bool = os.environ.get("GRANT_HUNTER_LLM_RERANK", "false").lower() in (
    "1",
    "true",
    "yes",
)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_CACHE_TTL_DAYS = 90
_BATCH_SIZE = 5
_MAX_BACKOFF_SECS = 30.0

# ── Scoring prompt template (versioned via hash) ──────────────────────────────

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

# ── Dimension weights ─────────────────────────────────────────────────────────

_DIMENSION_WEIGHTS: Dict[str, float] = {
    "research_alignment": 0.40,
    "institutional_fit": 0.25,
    "strategic_value": 0.20,
    "feasibility": 0.15,
}


# ── Score result dataclass ────────────────────────────────────────────────────


@dataclass
class LLMScoreResult:
    """Structured LLM scoring output for a single grant."""

    grant_id: str
    research_alignment: int
    institutional_fit: int
    strategic_value: int
    feasibility: int
    rationale: str
    llm_score: float = field(init=False)
    stale: bool = False
    scored_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        self.llm_score = round(
            self.research_alignment * _DIMENSION_WEIGHTS["research_alignment"]
            + self.institutional_fit * _DIMENSION_WEIGHTS["institutional_fit"]
            + self.strategic_value * _DIMENSION_WEIGHTS["strategic_value"]
            + self.feasibility * _DIMENSION_WEIGHTS["feasibility"],
            4,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LLMScoreResult":
        obj = cls(
            grant_id=d["grant_id"],
            research_alignment=d["research_alignment"],
            institutional_fit=d["institutional_fit"],
            strategic_value=d["strategic_value"],
            feasibility=d["feasibility"],
            rationale=d["rationale"],
            stale=d.get("stale", False),
            scored_at=d.get("scored_at", ""),
        )
        return obj


# ── Prompt / cache key helpers ────────────────────────────────────────────────


def _prompt_version_hash() -> str:
    """Return SHA-256 of the scoring prompt template (first 16 hex chars)."""
    return hashlib.sha256(SCORING_PROMPT_TEMPLATE.encode()).hexdigest()[:16]


def _description_hash(grant: Grant) -> str:
    """Return SHA-256 of grant title + description content."""
    content = f"{grant.title}\n{grant.description}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _cache_key(grant: Grant, profile_hash: str) -> str:
    """Return a stable cache key for a grant + profile + prompt version."""
    parts = f"{grant.fingerprint()}|{_description_hash(grant)}|{_prompt_version_hash()}|{profile_hash}"
    return hashlib.sha256(parts.encode()).hexdigest()


def _profile_hash(profile: Optional["ResearcherProfile"]) -> str:
    """Return a short hash representing the profile (or 'default')."""
    if profile is None:
        return "default"
    payload = json.dumps(profile.weights, sort_keys=True) + profile.name
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── Cache I/O ─────────────────────────────────────────────────────────────────


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def _cache_read(cache_dir: Path, key: str) -> Optional[LLMScoreResult]:
    """Read a cached result; returns None if missing or expired."""
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        scored_at_str = data.get("scored_at", "")
        if scored_at_str:
            scored_at = datetime.fromisoformat(scored_at_str)
            if scored_at.tzinfo is None:
                scored_at = scored_at.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - scored_at).days
            if age_days > _CACHE_TTL_DAYS:
                return None
        return LLMScoreResult.from_dict(data)
    except Exception as exc:
        logger.debug("Cache read error for %s: %s", key, exc)
        return None


def _cache_write(cache_dir: Path, key: str, result: LLMScoreResult) -> None:
    """Write a result to cache (creates directory if needed)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        _cache_path(cache_dir, key).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Cache write error for %s: %s", key, exc)


def _cache_read_stale(cache_dir: Path, key: str) -> Optional[LLMScoreResult]:
    """Read a cached result regardless of TTL (for fallback); marks stale=True."""
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = LLMScoreResult.from_dict(data)
        result.stale = True
        return result
    except Exception as exc:
        logger.debug("Stale cache read error for %s: %s", key, exc)
        return None


# ── External scores loader (subagent results) ───────────────────────────────


def load_external_scores(
    scores_dir: Optional[Path] = None,
) -> Dict[str, LLMScoreResult]:
    """Load the most recent subagent_scores_*.json file.

    Looks for files matching ``subagent_scores_*.json`` in *scores_dir*,
    picks the most recent by filename date suffix, and returns a dict
    mapping ``grant_id -> LLMScoreResult``.

    Returns an empty dict if no files are found or on parse error.
    """
    if scores_dir is None:
        scores_dir = DATA_HOME / "scores"

    if not scores_dir.exists():
        return {}

    score_files = sorted(scores_dir.glob("subagent_scores_*.json"), reverse=True)
    if not score_files:
        return {}

    latest = score_files[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read external scores from %s: %s", latest, exc)
        return {}

    if not isinstance(data, dict) or "grants" not in data:
        logger.warning("Invalid external scores format in %s", latest)
        return {}

    results: Dict[str, LLMScoreResult] = {}
    for item in data["grants"]:
        try:
            gid = str(item["grant_id"])
            # Clamp dimension scores to 1-5
            ra = max(1, min(5, int(item["research_alignment"])))
            inf = max(1, min(5, int(item["institutional_fit"])))
            sv = max(1, min(5, int(item["strategic_value"])))
            fe = max(1, min(5, int(item["feasibility"])))
            result = LLMScoreResult(
                grant_id=gid,
                research_alignment=ra,
                institutional_fit=inf,
                strategic_value=sv,
                feasibility=fe,
                rationale=str(item.get("rationale", "")),
                scored_at=data.get("scored_at", ""),
            )
            results[gid] = result
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping invalid grant entry in external scores: %s", exc)
            continue

    if results:
        logger.info(
            "Loaded %d external scores from %s", len(results), latest.name
        )
    return results


# ── Grant serialisation for prompt ───────────────────────────────────────────


def _grant_to_prompt_dict(grant: Grant) -> Dict[str, Any]:
    """Reduce a Grant to only the fields needed for LLM scoring."""
    amount_str = "unknown"
    if grant.amount_max:
        amount_str = f"up to ${grant.amount_max:,.0f}"
    elif grant.amount_min:
        amount_str = f"from ${grant.amount_min:,.0f}"

    deadline_str = grant.deadline.isoformat() if grant.deadline else "unknown"

    return {
        "id": grant.id,
        "title": grant.title,
        "agency": grant.agency,
        "source": grant.source,
        "amount": amount_str,
        "deadline": deadline_str,
        "description": (grant.description or "")[:1500],  # truncate for token budget
        "keywords": grant.keywords[:20],
    }


# ── LLM API call with retry ───────────────────────────────────────────────────


def _call_llm_batch(
    client: Any,
    model: str,
    grants: List[Grant],
) -> List[Dict[str, Any]]:
    """Call the Anthropic API for a batch of grants; returns list of score dicts.

    Raises on non-retryable errors. Caller handles retry logic.
    """
    grants_json = json.dumps(
        [_grant_to_prompt_dict(g) for g in grants],
        ensure_ascii=False,
        indent=2,
    )
    prompt = SCORING_PROMPT_TEMPLATE.format(grants_json=grants_json)

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text from response
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    # Parse JSON array from response
    # Handle markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # strip first and last fence lines
        text = "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:])

    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array from LLM, got {type(parsed)}")
    return parsed


def _call_with_retry(
    client: Any,
    model: str,
    grants: List[Grant],
) -> Optional[List[Dict[str, Any]]]:
    """Call LLM with one retry on failure (exponential backoff, max 30s).

    Returns parsed list on success, None on total failure.
    """
    attempt = 0
    last_exc: Optional[Exception] = None
    while attempt < 2:
        try:
            return _call_llm_batch(client, model, grants)
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                wait = min(2.0 ** attempt * 2, _MAX_BACKOFF_SECS)
                logger.warning(
                    "LLM batch call failed (attempt %d), retrying in %.1fs: %s",
                    attempt + 1,
                    wait,
                    exc,
                )
                time.sleep(wait)
            attempt += 1

    logger.error("LLM batch call failed after 2 attempts: %s", last_exc)
    return None


# ── Main reranker class ───────────────────────────────────────────────────────


class LLMReranker:
    """Re-rank grants using LLM-based 4-dimension structured scoring.

    Scores grants on research_alignment, institutional_fit, strategic_value,
    and feasibility. Results are cached in DATA_DIR/cache/reranker/ for 90 days.

    Args:
        model: Anthropic model ID to use for scoring.
        cache_dir: Override the default cache directory.
        ipk_profile: Reserved for future use (IPK-specific prompt variants).
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        cache_dir: Optional[Path] = None,
        ipk_profile: Optional[str] = None,
    ) -> None:
        self._model = model
        self._cache_dir = cache_dir or (DATA_HOME / "cache" / "reranker")
        self._ipk_profile = ipk_profile
        self._client: Optional[Any] = None

        if not _ANTHROPIC_AVAILABLE:
            logger.warning("LLMReranker: anthropic package unavailable; scoring will be skipped.")
        elif not LLM_RERANK_ENABLED:
            logger.debug(
                "LLMReranker: GRANT_HUNTER_LLM_RERANK is not enabled; "
                "set to 'true' to activate LLM reranking."
            )

    def _get_client(self) -> Optional[Any]:
        """Lazily initialise the Anthropic client."""
        if self._client is not None:
            return self._client
        if not _ANTHROPIC_AVAILABLE:
            return None
        try:
            self._client = _anthropic_mod.Anthropic()
        except Exception as exc:
            logger.error("Failed to create Anthropic client: %s", exc)
            return None
        return self._client

    def _score_batch(
        self,
        grants: List[Grant],
        profile: Optional["ResearcherProfile"],
    ) -> Dict[str, Optional[LLMScoreResult]]:
        """Score a single batch of grants (up to _BATCH_SIZE).

        Returns dict mapping grant.id -> LLMScoreResult (or None on failure).
        """
        ph = _profile_hash(profile)
        results: Dict[str, Optional[LLMScoreResult]] = {}
        to_call: List[Grant] = []
        stale_fallbacks: Dict[str, LLMScoreResult] = {}

        # Check cache first
        for grant in grants:
            key = _cache_key(grant, ph)
            cached = _cache_read(self._cache_dir, key)
            if cached is not None:
                results[grant.id] = cached
            else:
                # Collect stale for fallback
                stale = _cache_read_stale(self._cache_dir, key)
                if stale is not None:
                    stale_fallbacks[grant.id] = stale
                to_call.append(grant)

        if not to_call:
            return results

        client = self._get_client()
        if client is None:
            # No client — use stale or None
            for grant in to_call:
                results[grant.id] = stale_fallbacks.get(grant.id)
            return results

        raw = _call_with_retry(client, self._model, to_call)

        if raw is None:
            # Tier 3 fallback: stale cache or None
            for grant in to_call:
                fallback = stale_fallbacks.get(grant.id)
                if fallback is not None:
                    logger.info(
                        "Using stale cached LLM score for grant %s", grant.id
                    )
                results[grant.id] = fallback
            return results

        # Map returned scores back to grants by grant_id
        scored_map: Dict[str, Dict[str, Any]] = {}
        for item in raw:
            gid = str(item.get("grant_id", ""))
            if gid:
                scored_map[gid] = item

        for grant in to_call:
            item = scored_map.get(grant.id)
            if item is None:
                logger.warning("LLM did not return score for grant %s", grant.id)
                results[grant.id] = stale_fallbacks.get(grant.id)
                continue
            try:
                result = LLMScoreResult(
                    grant_id=grant.id,
                    research_alignment=int(item["research_alignment"]),
                    institutional_fit=int(item["institutional_fit"]),
                    strategic_value=int(item["strategic_value"]),
                    feasibility=int(item["feasibility"]),
                    rationale=str(item.get("rationale", "")),
                )
                key = _cache_key(grant, ph)
                _cache_write(self._cache_dir, key, result)
                results[grant.id] = result
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "Failed to parse LLM score for grant %s: %s", grant.id, exc
                )
                results[grant.id] = stale_fallbacks.get(grant.id)

        return results

    def rerank(
        self,
        grants: List[Grant],
        profile: Optional["ResearcherProfile"] = None,
    ) -> List[Grant]:
        """Re-rank grants using LLM-based 4-dimension structured scoring.

        Sets grant.llm_score and grant.llm_details for each grant.
        Returns grants sorted by blended_score descending.

        If LLM reranking is disabled or unavailable, grants are returned
        sorted by their existing relevance_score.

        Args:
            grants: List of Grant objects to re-rank.
            profile: Optional researcher profile (affects cache key).

        Returns:
            List of Grant objects sorted by blended score (highest first).
        """
        if not grants:
            return grants

        # Step 1: Try external scores (subagent results) first
        external = load_external_scores()
        if external:
            logger.info("Using external subagent scores (%d grants)", len(external))
            return self._apply_scores(grants, external)

        # Step 2: API path (requires anthropic package + env toggle)
        if not _ANTHROPIC_AVAILABLE or not LLM_RERANK_ENABLED:
            logger.debug("LLM reranking skipped; sorting by relevance_score only.")
            for grant in grants:
                if not hasattr(grant, "llm_score"):
                    object.__setattr__(grant, "llm_score", None)
                    object.__setattr__(grant, "llm_details", None)
            return sorted(grants, key=lambda g: g.relevance_score, reverse=True)

        # Process in batches via API
        all_scores: Dict[str, Optional[LLMScoreResult]] = {}
        for i in range(0, len(grants), _BATCH_SIZE):
            batch = grants[i : i + _BATCH_SIZE]
            batch_scores = self._score_batch(batch, profile)
            all_scores.update(batch_scores)

        return self._apply_scores(grants, all_scores)

    def _apply_scores(
        self,
        grants: List[Grant],
        scores: Dict[str, Optional[LLMScoreResult]],
    ) -> List[Grant]:
        """Attach LLM scores to grants and sort by blended score."""
        for grant in grants:
            score_result = scores.get(grant.id)
            if score_result is not None:
                # Normalise llm_score from [1,5] weighted sum to [0,1]
                raw_llm = score_result.llm_score
                llm_normalized = (raw_llm - 1.0) / (5.0 - 1.0)
                # Blended: 60% tfidf + 40% LLM
                blended = 0.60 * grant.relevance_score + 0.40 * llm_normalized
                object.__setattr__(grant, "llm_score", round(llm_normalized, 4))
                object.__setattr__(grant, "llm_details", score_result)
                object.__setattr__(grant, "blended_score", round(blended, 4))
            else:
                object.__setattr__(grant, "llm_score", None)
                object.__setattr__(grant, "llm_details", None)
                object.__setattr__(grant, "blended_score", grant.relevance_score)

        return sorted(
            grants,
            key=lambda g: getattr(g, "blended_score", g.relevance_score),
            reverse=True,
        )
