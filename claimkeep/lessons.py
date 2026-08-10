"""Durable lessons: the part of memory that is meant to outlive the session.

A claim answers "what is true right now". A lesson answers "what should be done
differently next time". The two have different lifetimes, so they get different
storage: claims live and die with a brief, lessons accumulate in an append-only
store and are carried forward into every later brief.

The store is JSONL, append-only, deduplicated by content id, and never rewritten
in place. An append-only log is the cheapest thing that cannot lose an earlier
lesson by rewriting a later one, and it stays readable with `tail` when
something goes wrong.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .brief import make_id, normalize


@dataclass
class Lesson:
    text: str
    ts: Optional[str] = None
    session: Optional[str] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        self.text = self.text.strip()
        if self.id is None:
            self.id = make_id("lesson", "", self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "text": self.text, "ts": self.ts, "session": self.session}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Lesson":
        return cls(
            id=str(data["id"]),
            text=str(data["text"]),
            ts=data.get("ts"),
            session=data.get("session"),
        )


class LessonStore:
    """Append-only JSONL store, deduplicated by lesson id."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(os.path.expanduser(path))

    def load(self) -> List[Lesson]:
        if not os.path.isfile(self.path):
            return []
        lessons: Dict[str, Lesson] = {}
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    lessons[str(json.loads(line)["id"])] = Lesson.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError, TypeError):
                    # One malformed line must not cost the whole store.
                    continue
        return list(lessons.values())

    def append(self, lessons: List[Lesson]) -> List[Lesson]:
        """Append lessons not already stored. Returns the ones actually written."""
        if not lessons:
            return []
        known = {lesson.id for lesson in self.load()}
        fresh = []
        seen = set()
        for lesson in lessons:
            if lesson.id in known or lesson.id in seen:
                continue
            seen.add(lesson.id)
            fresh.append(lesson)
        if not fresh:
            return []
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            for lesson in fresh:
                handle.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")
        return fresh

    def recent(self, limit: int) -> List[Lesson]:
        """Newest-first slice of the store.

        Newest-first because a later lesson may reverse an earlier one, and the
        reader takes the first match as current.
        """
        if limit <= 0:
            return []
        return list(reversed(self.load()))[:limit]


def dedupe(lessons: List[Lesson]) -> List[Lesson]:
    by_key: Dict[str, Lesson] = {}
    for lesson in lessons:
        by_key.setdefault(normalize(lesson.text), lesson)
    return list(by_key.values())
