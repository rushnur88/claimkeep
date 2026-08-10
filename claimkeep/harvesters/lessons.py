"""Lesson harvester: pick up the rules an agent states about its own work.

Two recognisers, deliberately narrow.

The explicit one takes a labelled line — `LESSON:` and its common variants. An
agent told to write lessons will write them this way, and an exact label costs
nothing in false positives.

The implicit one takes the shape a lesson actually has in running text: an
outcome followed by a rule for next time ("... so next time ...", "... therefore
always ..."). It is kept tight on purpose. A loose recogniser fills the store
with ordinary sentences, and a store full of noise is worse than an empty one:
it spends budget every session and teaches nothing.
"""

from __future__ import annotations

import re
from typing import List, Sequence

from ..brief import Claim
from ..config import Config
from .base import Harvester


LABEL_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:[A-Z][A-Z0-9]{0,15}[- ])?LESSON(?:\s+LEARNED)?"
    # Agents that stamp their lessons write `LESSON [2026-08-10T14:22:40Z] (local): body`.
    # The stamp sits between the label and the separator, so it has to be skipped
    # or every timestamped lesson is silently missed - measured on a real transcript.
    r"(?:\s*\[[^\]\n]{0,60}\])?(?:\s*\([^)\n]{0,60}\))?"
    r"\s*[:\-—]\s*(?P<body>.+?)\s*$"
)

# outcome -> rule. The rule half must be present; a bare outcome is not a lesson.
RULE_RE = re.compile(
    r"(?i)\b(?:so|therefore|which means|lesson)\b[^.!?\n]{0,40}?\b"
    r"(?:next time|from now on|always|never|going forward|in future)\b"
)

MIN_LEN = 25
MAX_LEN = 500


class LessonHarvester(Harvester):
    """Emits lessons as claims tagged with the reserved topic `lesson`."""

    name = "lessons"
    TOPIC = "lesson"

    def harvest(self, transcript: Sequence[str], config: Config) -> List[Claim]:
        if not getattr(config, "lessons_enabled", True):
            return []
        seen = set()
        found: List[Claim] = []
        for unit in transcript:
            for text in self._extract(unit):
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    Claim(
                        text=text,
                        confidence=None,
                        # Every lesson gets its own topic so that one lesson does
                        # not supersede another: they accumulate, they do not
                        # replace each other the way claims on a topic do.
                        topic=self.TOPIC + ":" + text.casefold()[:40],
                        source_harvester=self.name,
                        source_span=unit,
                    )
                )
        return found

    def _extract(self, unit: str) -> List[str]:
        out: List[str] = []
        for match in LABEL_RE.finditer(unit):
            body = match.group("body").strip()
            if MIN_LEN <= len(body) <= MAX_LEN:
                out.append(body)
        if out:
            return out
        for line in unit.split("\n"):
            line = line.strip(" \t-*")
            if MIN_LEN <= len(line) <= MAX_LEN and RULE_RE.search(line):
                out.append(line)
        return out
