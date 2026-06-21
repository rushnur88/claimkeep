"""Marker-free floor harvester for ids, paths, and decisions."""

from __future__ import annotations

import re
from typing import List, Sequence, Set

from ..brief import Supplement, normalize
from ..config import Config
from .base import Harvester


PATH_RE = re.compile(r"(?<![\w])(?:~|\.)?/[A-Za-z0-9._~@%+=:,/-]+|(?<![\w])(?:[A-Za-z0-9_.-]+/){1,}[A-Za-z0-9._~@%+=:,-]+")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
HEX_RE = re.compile(r"\b[0-9a-fA-F]{7,40}\b")
ISSUE_RE = re.compile(r"(?i)(?:\bobs\s+#\d+\b|#\d+\b)")
DECISION_RE = re.compile(
    r"(?i)\b(decided|chose|going with|will use|locked|approved|DECISION)\b|\buse\s+.+?\s+not\s+.+"
)


class RegexFloorHarvester(Harvester):
    name = "regex_floor"

    def harvest(self, transcript: Sequence[str], config: Config) -> List[Supplement]:
        items: List[Supplement] = []
        seen: Set[str] = set()
        path_texts: List[str] = []

        def add(text: str, kind: str) -> str:
            cleaned = text.strip().rstrip(".,;:")
            if not cleaned:
                return ""
            key = kind + "|" + normalize(cleaned)
            if key in seen:
                return ""
            seen.add(key)
            items.append(Supplement(text=cleaned, kind=kind, source_harvester=self.name))
            return cleaned

        for unit in transcript:
            if config.floor_paths:
                for match in PATH_RE.finditer(unit):
                    candidate = match.group(0)
                    if "/" in candidate.strip("/"):
                        cleaned = add(candidate, "path")
                        if cleaned:
                            path_texts.append(cleaned)
            if config.floor_ids:
                for regex in (UUID_RE, HEX_RE, ISSUE_RE):
                    for match in regex.finditer(unit):
                        token = match.group(0)
                        # pure-digit runs are not ids: a hex id must carry a letter
                        if token.isdigit():
                            continue
                        # don't double-count an id that lives inside a captured path
                        if any(token in p for p in path_texts):
                            continue
                        add(token, "id")
            if config.floor_decisions and DECISION_RE.search(unit):
                add(unit, "decision")
        return items
