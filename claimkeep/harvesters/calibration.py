"""Calibration-marker harvester."""

from __future__ import annotations

import re
from typing import List, Sequence

from ..brief import Claim
from ..config import Config
from .base import Harvester

# Any script, not just Latin. The old class was [A-Za-z0-9_./#-], so a sentence
# written entirely in Cyrillic — or Greek, Hebrew, Chinese — matched no words at
# all and every such claim fell back to the literal topic "claim". Sharing one
# topic is not harmless: dedup treats a topic as one subject restated over time,
# so unrelated facts marked each other superseded. Three Russian statements went
# in and two came back flagged as retracted by the third.
#
# `[^\W_]` is "word character except underscore" under Unicode, which covers
# every script; the explicit punctuation keeps paths and versions intact.
_SLUG_WORD = re.compile(r"[^\W_]+(?:[._/#-][^\W_]+)*|[A-Za-z0-9_./#-]+", re.UNICODE)


def _slug_topic(text: str) -> str:
    words = _SLUG_WORD.findall(text)[:6]
    slug = "-".join(word.casefold() for word in words).strip("-")
    return slug or "claim"


def _topic(text: str) -> str:
    """Prefer the atomic subject|predicate key, fall back to a leading-words slug.

    The slug embeds the value being stated, so "the retry ceiling is 5" and
    "the retry ceiling is 4" land on different topics and supersession never
    chains — exactly on the corrections it exists to track. The atomic key is
    built from subject and predicate only, so a restatement keeps the topic and
    the earlier claim gets marked superseded_by.

    Sentences the atomic parser cannot resolve keep the old slug: a stable-looking
    key that is wrong would collide unrelated facts into false corrections.
    """
    try:
        from .atomic import _topic as _atomic_topic
        from .atomic import extract_triple

        triple = extract_triple(text)
        if triple is not None:
            subject, predicate, obj = triple
            key = _atomic_topic(subject, predicate, obj)
            if key:
                return key
    except Exception:  # never let topic derivation break a harvest
        pass
    return _slug_topic(text)


def _confidence(match: "re.Match") -> float:
    try:
        return max(0, min(100, int(match.group(1)))) / 100.0
    except (IndexError, ValueError):
        return None


def _tidy(text: str, marker: "re.Pattern") -> str:
    """Strip list bullets and the punctuation left behind by the previous split."""
    return marker.sub("", text).strip().strip("-•*—,;:.)（(").strip()


def _scoped_statements(unit: str, marker: "re.Pattern"):
    """Yield (statement, confidence) — one per marker, scoped to that marker.

    A marker annotates the statement it follows, not the whole message. The old
    code took the first marker's confidence, stripped every marker, and stored
    the entire message as one claim. On real transcripts 45% of marked assistant
    messages carry two or more markers, so nearly half of all claims averaged
    unrelated facts under one confidence and one topic — and any unmarked aside
    in the same message inherited that confidence, which is how "this is
    explicitly not a fact" ended up stored at 90%.

    The statement runs from the previous marker to this one, trimmed to its last
    non-empty line: a marker ends its own line far more often than it ends a
    paragraph, and taking the whole span would drag headings and preamble in.
    Text after the final marker is deliberately dropped — it carries no marker,
    so it is not a claim.
    """
    matches = list(marker.finditer(unit))
    for index, match in enumerate(matches):
        before = unit[(matches[index - 1].end() if index else 0) : match.start()]
        lines = [line for line in before.split("\n") if line.strip()]
        text = _tidy(lines[-1], marker) if lines else ""
        if not text:
            # "[C:80%] the statement" — the marker leads instead of trailing.
            nxt = matches[index + 1].start() if index + 1 < len(matches) else len(unit)
            text = _tidy(unit[match.end() : nxt].split("\n", 1)[0], marker)
        if text:
            yield text, _confidence(match)


class CalibrationHarvester(Harvester):
    name = "calibration"

    def harvest(self, transcript: Sequence[str], config: Config) -> List[Claim]:
        marker = re.compile(config.calibration_marker_regex)
        claims: List[Claim] = []
        for unit in transcript:
            for text, confidence in _scoped_statements(unit, marker):
                claims.append(
                    Claim(
                        text=text,
                        confidence=confidence,
                        topic=_topic(text),
                        source_harvester=self.name,
                        # Provenance stays the message as written, so a reader can
                        # still see the statement in the context it came from.
                        source_span=unit,
                    )
                )
        return claims
