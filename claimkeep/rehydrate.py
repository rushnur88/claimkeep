"""Render and hook payload helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from .brief import Brief


def render(brief: Brief) -> str:
    lines: List[str] = ["# ClaimKeep Brief", ""]
    if brief.created_utc:
        lines.extend(["Created: " + brief.created_utc, ""])

    lines.append("## Claims")
    claims = sorted(
        brief.claims,
        key=lambda claim: (-1.0 if claim.confidence is None else -claim.confidence, claim.topic, claim.id or ""),
    )
    if claims:
        for claim in claims:
            confidence = "unknown" if claim.confidence is None else f"{claim.confidence:.2f}"
            lines.append(f"- [{confidence}] {claim.text} (topic: {claim.topic}; id: {claim.id})")
    else:
        lines.append("- None")
    lines.append("")

    grouped: Dict[str, List[str]] = defaultdict(list)
    for item in brief.supplement:
        grouped[item.kind].append(item.text)
    lines.append("## Supplement")
    for kind in ("id", "path", "decision"):
        lines.append(f"### {kind}")
        values = grouped.get(kind, [])
        if values:
            for value in values:
                lines.append("- " + value)
        else:
            lines.append("- None")
    lines.append("")

    if brief.open_threads:
        lines.append("## Open Threads")
        for thread in brief.open_threads:
            lines.append("- " + thread)
        lines.append("")

    if brief.last_user_ask:
        lines.extend(["## Last User Ask", brief.last_user_ask, ""])

    if brief.narrative:
        lines.append("## Narrative")
        for item in brief.narrative:
            lines.append("- " + item)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def postcompact_payload(brief: Brief, event: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": render(brief)}}
