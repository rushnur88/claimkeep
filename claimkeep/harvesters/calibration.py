"""Calibration-marker harvester."""

from __future__ import annotations

import re
from typing import List, Sequence

from ..brief import Claim
from ..config import Config
from .base import Harvester


def _slug_topic(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9_./#-]+", text)[:6]
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
