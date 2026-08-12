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


class CalibrationHarvester(Harvester):
    name = "calibration"

    def harvest(self, transcript: Sequence[str], config: Config) -> List[Claim]:
        marker = re.compile(config.calibration_marker_regex)
        claims: List[Claim] = []
        for unit in transcript:
            match = marker.search(unit)
            if not match:
                continue
            try:
                confidence = max(0, min(100, int(match.group(1)))) / 100.0
            except (IndexError, ValueError):
                confidence = None
            text = marker.sub("", unit).strip()
            if not text:
                continue
            claims.append(
                Claim(
                    text=text,
                    confidence=confidence,
                    topic=_topic(text),
                    source_harvester=self.name,
                    source_span=unit,
                )
            )
        return claims
