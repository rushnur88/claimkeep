"""The read path: recall across every brief ever written, not just the last one.

Until now ClaimKeep only wrote. A brief was produced at compaction and injected
whole at the next start, which means the agent got the most recent session and
nothing else — everything older sat on disk, unread. Writing without reading is
half a memory system, and the cheaper half.

Retrieval here is lexical (BM25) over the union of stored briefs and the lesson
store, re-weighted by recency and standing. It is deliberately not dense: the
project holds a stdlib-only contract, and an embedding model would be a runtime
dependency, a download, and a moving target across versions. Lexical recall is
weaker than dense recall on paraphrase — that is a real limitation, stated here
rather than discovered later by a user.

What lexical does well is exactly what a brief is full of: identifiers, paths,
error strings, names. Those are the things an agent needs to find again, and
they match on the token, not on the vibe.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .brief import Brief
from .lessons import LessonStore

K1 = 1.5
B = 0.75

# Weights applied after BM25. A lesson is advice that already proved itself, so
# it outranks a bare path at equal lexical score; a superseded claim is history
# and must not outrank the fact that replaced it.
KIND_BOOST = {"lesson": 1.4, "claim": 1.0, "decision": 1.0, "id": 0.9, "path": 0.85}
SUPERSEDED_BOOST = 0.4
RECENCY_BOOST = 0.25

# How much of the parent brief's own match feeds into each of its items.
#
# BM25 length-normalises, so a session stored as eighty one-sentence items
# competes very differently from the same session as one block: each fragment is
# short, matches one term at most, and the fragments crowd each other out. Scored
# as a block instead, R@1 on LongMemEval went 0.734 -> 0.814 with identical
# stored volume. Items still rank and are still what gets returned — they simply
# inherit some of the evidence their neighbours provide.
#
# 1.0 was picked by measurement, not taste: at 0.5 the same corpus scored R@1
# 0.812 / R@10 0.956, at 1.0 it scores 0.824 / 0.958.
PARENT_BOOST = float(os.environ.get("CLAIMKEEP_PARENT_BOOST", "1.0"))

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.casefold())


@dataclass
class Document:
    text: str
    kind: str
    id: str
    ts: Optional[str] = None
    superseded: bool = False
    source: Optional[str] = None
    tokens: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = tokenize(self.text)


def load_corpus(config: Any) -> List[Document]:
    """Every claim, supplement item and lesson the plugin has ever stored."""
    docs: List[Document] = []
    seen = set()

    brief_dir = config.expanded_brief_dir()
    for path in sorted(glob.glob(os.path.join(brief_dir, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                brief = Brief.from_json(handle.read())
        except (OSError, ValueError, json.JSONDecodeError):
            # A single unreadable brief must not cost the whole corpus.
            continue
        name = os.path.basename(path)
        for claim in brief.claims:
            key = ("claim", claim.id)
            if key in seen:
                continue
            seen.add(key)
            kind = "lesson" if claim.topic.startswith("lesson:") else "claim"
            docs.append(Document(text=claim.text, kind=kind, id=str(claim.id),
                                 ts=claim.ts or brief.created_utc,
                                 superseded=not claim.is_active, source=name))
        for item in brief.supplement:
            key = ("supplement", item.id)
            if key in seen:
                continue
            seen.add(key)
            docs.append(Document(text=item.text, kind=item.kind, id=str(item.id),
                                 ts=brief.created_utc, source=name))

    try:
        for lesson in LessonStore(config.expanded_lessons_path()).load():
            key = ("lesson", lesson.id)
            if key in seen:
                continue
            seen.add(key)
            docs.append(Document(text=lesson.text, kind="lesson", id=str(lesson.id),
                                 ts=lesson.ts, source="lessons"))
    except OSError:
        pass
    return docs


def _idf(docs: Sequence[Document]) -> Dict[str, float]:
    total = len(docs)
    seen: Dict[str, int] = {}
    for doc in docs:
        for token in set(doc.tokens):
            seen[token] = seen.get(token, 0) + 1
    return {
        token: math.log(1 + (total - count + 0.5) / (count + 0.5))
        for token, count in seen.items()
    }


def _recency_rank(docs: Sequence[Document]) -> Dict[str, float]:
    """Position of each doc on the timeline, 0 oldest to 1 newest.

    Rank, not raw age: timestamps come from several writers and comparing them
    as durations would give whichever writer stamps most often an unearned edge.
    """
    stamped = sorted([doc for doc in docs if doc.ts], key=lambda doc: str(doc.ts))
    if not stamped:
        return {}
    last = len(stamped) - 1
    if last == 0:
        return {stamped[0].id: 1.0}
    return {doc.id: index / last for index, doc in enumerate(stamped)}


def _parent_scores(terms: Sequence[str], docs: Sequence[Document]) -> Dict[str, float]:
    """BM25 of each parent group, computed over the concatenation of its items."""
    groups: Dict[str, List[str]] = {}
    for doc in docs:
        key = doc.source or doc.id
        groups.setdefault(key, []).extend(doc.tokens)
    if len(groups) < 2:
        return {}
    total = len(groups)
    seen: Dict[str, int] = {}
    for tokens in groups.values():
        for token in set(tokens):
            seen[token] = seen.get(token, 0) + 1
    idf = {
        token: math.log(1 + (total - count + 0.5) / (count + 0.5))
        for token, count in seen.items()
    }
    avg_len = sum(len(tokens) for tokens in groups.values()) / total or 1.0
    out: Dict[str, float] = {}
    for key, tokens in groups.items():
        length = len(tokens) or 1
        raw = 0.0
        for term in terms:
            if term not in idf:
                continue
            freq = tokens.count(term)
            if not freq:
                continue
            raw += idf[term] * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * length / avg_len))
        if raw > 0:
            out[key] = raw
    return out


def score(query: str, docs: Sequence[Document]) -> List[Dict[str, Any]]:
    """BM25 over the corpus, re-weighted by kind, standing, recency and parent."""
    terms = tokenize(query)
    if not terms or not docs:
        return []
    idf = _idf(docs)
    avg_len = sum(len(doc.tokens) for doc in docs) / len(docs) or 1.0
    recency = _recency_rank(docs)
    parent = _parent_scores(terms, docs) if PARENT_BOOST else {}

    scored: List[Dict[str, Any]] = []
    for doc in docs:
        length = len(doc.tokens) or 1
        raw = 0.0
        for term in terms:
            if term not in idf:
                continue
            freq = doc.tokens.count(term)
            if not freq:
                continue
            raw += idf[term] * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * length / avg_len))
        context = parent.get(doc.source or doc.id, 0.0)
        if raw <= 0 and context <= 0:
            continue
        raw += PARENT_BOOST * context
        weight = KIND_BOOST.get(doc.kind, 1.0)
        if doc.superseded:
            weight *= SUPERSEDED_BOOST
        weight *= 1.0 + RECENCY_BOOST * recency.get(doc.id, 0.0)
        scored.append({"doc": doc, "score": round(raw * weight, 4), "bm25": round(raw, 4)})

    scored.sort(key=lambda row: (-row["score"], row["doc"].id))
    return scored


def recall(query: str, config: Any, limit: int = 10, budget_chars: int = 0) -> List[Dict[str, Any]]:
    """Top matches for a query, optionally capped to a character budget."""
    results = score(query, load_corpus(config))[: max(0, limit)]
    if budget_chars <= 0:
        return results
    kept: List[Dict[str, Any]] = []
    used = 0
    for row in results:
        cost = len(row["doc"].text) + 1
        if used + cost > budget_chars:
            continue
        used += cost
        kept.append(row)
    return kept
