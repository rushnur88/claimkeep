"""Budget-aware selection for the brief.

A PreCompact brief is re-injected into the very context window the compaction
just freed. An unbounded brief therefore defeats its own purpose: harvesting a
long session yields far more material than any window can take back.

This module answers the only question that matters once a budget exists: when
not everything fits, what goes in. Selection is deterministic and explainable —
no model call, no wall clock — so the same transcript always yields the same
brief and a reviewer can reconstruct why an item made the cut.

Ranking signals, in order of weight:
  recency     later in the session beats earlier
  confidence  a calibrated claim beats an unmarked one
  kind        decisions beat identifiers beat bare paths
  standing    an active claim beats one a later claim superseded

Superseded claims are ranked low but not excluded: knowing a fact was retracted
is worth spending budget on once the live facts are in.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .brief import Brief, Claim, Supplement

# Claims carry the agent's own assessed statements; supplement carries the
# marker-free floor. A claim is worth more per character than a bare path.
BASE_CLAIM = 1.0
BASE_SUPPLEMENT = 0.6

KIND_WEIGHT = {"decision": 1.0, "id": 0.8, "path": 0.7}

W_BASE = 0.5
W_CONFIDENCE = 0.3
W_RECENCY = 0.2

SUPERSEDED_PENALTY = 0.35
DEFAULT_CONFIDENCE = 0.5


def _recency(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return index / (total - 1)


def score_claim(claim: Claim, index: int, total: int) -> float:
    confidence = DEFAULT_CONFIDENCE if claim.confidence is None else claim.confidence
    score = BASE_CLAIM * (
        W_BASE + W_CONFIDENCE * confidence + W_RECENCY * _recency(index, total)
    )
    if not claim.is_active:
        score *= SUPERSEDED_PENALTY
    return score


def score_supplement(item: Supplement, index: int, total: int) -> float:
    kind = KIND_WEIGHT.get(item.kind, 0.5)
    return BASE_SUPPLEMENT * kind * (W_BASE + W_RECENCY * _recency(index, total) + W_CONFIDENCE)


def _cost(text: str) -> int:
    """Characters this item will occupy in the rendered brief, newline included."""
    return len(text) + 1


def apply_budget(brief: Brief, budget_chars: int) -> Brief:
    """Return a brief trimmed to budget_chars, with a report on what was cut.

    budget_chars <= 0 means unbounded and the brief is returned unchanged.
    Selection order is by score; output order is the original harvest order, so
    the brief still reads chronologically.
    """
    if budget_chars <= 0:
        return brief

    ranked: List[Tuple[float, int, str, Any]] = []
    total_claims = len(brief.claims)
    for index, claim in enumerate(brief.claims):
        ranked.append((score_claim(claim, index, total_claims), index, "claim", claim))
    total_supplement = len(brief.supplement)
    for index, item in enumerate(brief.supplement):
        ranked.append((score_supplement(item, index, total_supplement), index, "supplement", item))

    # Highest score first; ties broken by original position so the result is
    # stable and reproducible across runs.
    ranked.sort(key=lambda row: (-row[0], row[2], row[1]))

    kept_claims: List[Claim] = []
    kept_supplement: List[Supplement] = []
    used = 0
    dropped = 0
    for _score, _index, bucket, item in ranked:
        cost = _cost(item.text)
        if used + cost > budget_chars:
            dropped += 1
            continue
        used += cost
        if bucket == "claim":
            kept_claims.append(item)
        else:
            kept_supplement.append(item)

    kept_claim_ids = {claim.id for claim in kept_claims}
    kept_supplement_ids = {item.id for item in kept_supplement}
    ordered_claims = [claim for claim in brief.claims if claim.id in kept_claim_ids]
    ordered_supplement = [item for item in brief.supplement if item.id in kept_supplement_ids]

    source: Dict[str, Any] = dict(brief.source or {})
    source["budget"] = {
        "budget_chars": budget_chars,
        "used_chars": used,
        "kept_claims": len(ordered_claims),
        "kept_supplement": len(ordered_supplement),
        "dropped_items": dropped,
        "harvested_claims": total_claims,
        "harvested_supplement": total_supplement,
    }

    return Brief(
        claims=ordered_claims,
        supplement=ordered_supplement,
        created_utc=brief.created_utc,
        source=source,
        open_threads=list(brief.open_threads),
        last_user_ask=brief.last_user_ask,
        narrative=list(brief.narrative),
    )
