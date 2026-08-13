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

# A rule-extracted sentence is worth less per character than a statement the
# agent itself marked with a confidence. Without this the atomic harvester —
# which produces far more items than the others — would crowd paths, ids and
# decisions out of the budget on agent transcripts, which is the case the
# supplement floor exists for.
RULE_EXTRACTED_WEIGHT = 0.75

# A retraction outranks everything else at equal length. After compaction the
# agent restates whatever survived with undiminished confidence, so a refuted
# claim that outlives its own refutation is the one failure a memory layer must
# not produce. The fleet hook protects a slot for the newest few; here the same
# intent is expressed as a weight, which composes with recency instead of
# fighting it.
RETRACTION_BOOST = 2.0


def _recency(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return index / (total - 1)


def score_claim(claim: Claim, index: int, total: int) -> float:
    confidence = DEFAULT_CONFIDENCE if claim.confidence is None else claim.confidence
    score = BASE_CLAIM * (
        W_BASE + W_CONFIDENCE * confidence + W_RECENCY * _recency(index, total)
    )
    if claim.topic.startswith("retraction"):
        score *= RETRACTION_BOOST
    elif claim.source_harvester == "atomic" and claim.confidence is None:
        score *= RULE_EXTRACTED_WEIGHT
    if not claim.is_active:
        score *= SUPERSEDED_PENALTY
    return score


def score_supplement(item: Supplement, index: int, total: int) -> float:
    kind = KIND_WEIGHT.get(item.kind, 0.5)
    return (
        BASE_SUPPLEMENT
        * kind
        * (W_BASE + W_RECENCY * _recency(index, total) + W_CONFIDENCE)
    )


def _cost(text: str) -> int:
    """Characters this item will occupy in the rendered brief, newline included."""
    return len(text) + 1


def _ranked(brief: Brief) -> List[Tuple[float, int, str, Any]]:
    """Items in drop-last order: highest priority first, ties by original position."""
    ranked: List[Tuple[float, int, str, Any]] = []
    total_claims = len(brief.claims)
    for index, claim in enumerate(brief.claims):
        ranked.append((score_claim(claim, index, total_claims), index, "claim", claim))
    total_supplement = len(brief.supplement)
    for index, item in enumerate(brief.supplement):
        ranked.append(
            (score_supplement(item, index, total_supplement), index, "supplement", item)
        )
    ranked.sort(key=lambda row: (-row[0], row[2], row[1]))
    return ranked


def _keep_top(
    brief: Brief, ranked: List[Tuple[float, int, str, Any]], count: int
) -> Brief:
    """A brief holding the `count` highest-priority items, in original order."""
    keep = ranked[:count]
    claim_ids = {item.id for _s, _i, bucket, item in keep if bucket == "claim"}
    supp_ids = {item.id for _s, _i, bucket, item in keep if bucket == "supplement"}
    return Brief(
        claims=[c for c in brief.claims if c.id in claim_ids],
        supplement=[s for s in brief.supplement if s.id in supp_ids],
        created_utc=brief.created_utc,
        source=dict(brief.source or {}),
        open_threads=list(brief.open_threads),
        last_user_ask=brief.last_user_ask,
        narrative=list(brief.narrative),
    )


def fit_rendered(brief: Brief, budget_chars: int, build) -> Brief:
    """Largest prefix of the priority order whose *rendered* form fits the budget.

    `apply_budget` bounds the sum of item texts, which is not what reaches the
    agent: rendering adds headings, confidences, topics and markdown, and at
    SessionStart the marker instruction as well. A brief reporting 2,870 used
    characters produced 7,799 characters of context — a budget that is only
    advisory is not a budget, and the whole point of the brief is to fit back
    into the window compaction just cleared.

    Binary search over the priority order, so the answer costs a handful of
    renders rather than one per item, and drops the same items every time.
    """
    if budget_chars <= 0:
        return brief
    ranked = _ranked(brief)
    if len(build(brief)) <= budget_chars:
        return brief
    low, high, best = 0, len(ranked), None
    while low <= high:
        mid = (low + high) // 2
        candidate = _keep_top(brief, ranked, mid)
        if len(build(candidate)) <= budget_chars:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    # Even an empty brief can overrun a very small budget, because the frame and
    # the marker instruction have a size of their own. Returning the empty brief
    # is honest: it renders the smallest thing this can produce.
    return best if best is not None else _keep_top(brief, ranked, 0)


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
        ranked.append(
            (score_supplement(item, index, total_supplement), index, "supplement", item)
        )

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
    ordered_supplement = [
        item for item in brief.supplement if item.id in kept_supplement_ids
    ]

    # The pass above bounds the sum of item texts, which is not the size of the
    # brief: rendering wraps every item in a heading, a confidence, a topic and
    # an id. Measured, that gap was 2.7x — a brief reporting 2,870 characters
    # rendered to 7,799. So the budget is settled against the rendered form,
    # and what gets reported is what the file actually costs.
    #
    # Imported here rather than at module scope: `rehydrate` imports this module
    # for `fit_rendered`, and a top-level import would close the cycle.
    from .rehydrate import render

    fitted = fit_rendered(
        Brief(
            claims=ordered_claims,
            supplement=ordered_supplement,
            created_utc=brief.created_utc,
            source=dict(brief.source or {}),
            open_threads=list(brief.open_threads),
            last_user_ask=brief.last_user_ask,
            narrative=list(brief.narrative),
        ),
        budget_chars,
        render,
    )
    dropped += (len(ordered_claims) - len(fitted.claims)) + (
        len(ordered_supplement) - len(fitted.supplement)
    )
    ordered_claims = fitted.claims
    ordered_supplement = fitted.supplement
    used = sum(_cost(item.text) for item in ordered_claims) + sum(
        _cost(item.text) for item in ordered_supplement
    )
    rendered_chars = len(render(fitted))

    source: Dict[str, Any] = dict(brief.source or {})
    source["budget"] = {
        "budget_chars": budget_chars,
        # Sum of item texts, kept for continuity, and the size of the brief as
        # rendered — the number the cap is actually enforced against.
        "used_chars": used,
        "rendered_chars": rendered_chars,
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
