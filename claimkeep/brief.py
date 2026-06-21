"""Brief schema v1 primitives."""

from __future__ import annotations

import json
import re
import hashlib
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 1


def normalize(text: str) -> str:
    """Normalize text for deterministic id hashing only."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold().strip())


def make_id(source_harvester: str, middle: str, text: str) -> str:
    payload = source_harvester + "|" + middle + "|" + normalize(text)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Claim:
    text: str
    confidence: Optional[float]
    topic: str
    source_harvester: str
    ts: Optional[str] = None
    source_span: Optional[str] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.confidence is not None:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.id is None:
            self.id = make_id(self.source_harvester, self.topic, self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "confidence": self.confidence,
            "topic": self.topic,
            "source_harvester": self.source_harvester,
            "ts": self.ts,
            "source_span": self.source_span,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Claim":
        return cls(
            id=str(data["id"]),
            text=str(data["text"]),
            confidence=None if data.get("confidence") is None else float(data["confidence"]),
            topic=str(data["topic"]),
            source_harvester=str(data["source_harvester"]),
            ts=data.get("ts"),
            source_span=data.get("source_span"),
        )


@dataclass
class Supplement:
    text: str
    kind: str
    source_harvester: str
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in {"id", "path", "decision"}:
            raise ValueError("supplement kind must be one of: id, path, decision")
        if self.id is None:
            self.id = make_id(self.source_harvester, self.kind, self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "source_harvester": self.source_harvester,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Supplement":
        return cls(
            id=str(data["id"]),
            text=str(data["text"]),
            kind=str(data["kind"]),
            source_harvester=str(data["source_harvester"]),
        )


@dataclass
class Brief:
    claims: List[Claim] = field(default_factory=list)
    supplement: List[Supplement] = field(default_factory=list)
    created_utc: Optional[str] = None
    source: Optional[Dict[str, Any]] = None
    open_threads: List[str] = field(default_factory=list)
    last_user_ask: Optional[str] = None
    narrative: List[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        self.claims = self._dedup_claims(self.claims)
        self.supplement = self._dedup_supplement(self.supplement)

    def add_claim(self, claim: Claim) -> None:
        self.claims.append(claim)
        self.claims = self._dedup_claims(self.claims)

    def add_supplement(self, supplement: Supplement) -> None:
        self.supplement.append(supplement)
        self.supplement = self._dedup_supplement(self.supplement)

    @staticmethod
    def _dedup_claims(claims: Iterable[Claim]) -> List[Claim]:
        latest_by_id: Dict[str, tuple[int, Claim]] = {}
        for index, claim in enumerate(claims):
            latest_by_id[str(claim.id)] = (index, claim)
        latest_by_topic: Dict[str, tuple[int, Claim]] = {}
        for index, claim in sorted(latest_by_id.values(), key=lambda item: item[0]):
            latest_by_topic[claim.topic] = (index, claim)
        return [claim for _, claim in sorted(latest_by_topic.values(), key=lambda item: item[0])]

    @staticmethod
    def _dedup_supplement(supplements: Iterable[Supplement]) -> List[Supplement]:
        by_id: Dict[str, Supplement] = {}
        for item in supplements:
            by_id[str(item.id)] = item
        return list(by_id.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_utc": self.created_utc,
            "source": self.source,
            "claims": [claim.to_dict() for claim in self.claims],
            "supplement": [item.to_dict() for item in self.supplement],
            "open_threads": list(self.open_threads),
            "last_user_ask": self.last_user_ask,
            "narrative": list(self.narrative),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Brief":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        for key in ("claims", "supplement"):
            if key not in data:
                raise ValueError("missing required key: " + key)
        return cls(
            schema_version=SCHEMA_VERSION,
            created_utc=data.get("created_utc"),
            source=data.get("source"),
            claims=[Claim.from_dict(item) for item in data.get("claims", [])],
            supplement=[Supplement.from_dict(item) for item in data.get("supplement", [])],
            open_threads=list(data.get("open_threads", [])),
            last_user_ask=data.get("last_user_ask"),
            narrative=list(data.get("narrative", [])),
        )

    @classmethod
    def from_json(cls, text: str) -> "Brief":
        return cls.from_dict(json.loads(text))

    def render(self) -> str:
        from .rehydrate import render

        return render(self)
