"""Calibration-marker harvester."""

from __future__ import annotations

import re
from typing import List, Sequence

from ..brief import Claim
from ..config import Config
from .base import Harvester


def _topic(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9_./#-]+", text)[:6]
    slug = "-".join(word.casefold() for word in words).strip("-")
    return slug or "claim"


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
