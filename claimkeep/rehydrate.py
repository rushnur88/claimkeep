"""Render and hook payload helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from .brief import Brief
from .prompt import marker_instruction
from .select import fit_rendered

# Reserved topic prefix the lesson harvester writes; kept here as a constant so
# the renderer does not import a harvester just to know one string.
LESSON_TOPIC = "lesson"


def render(brief: Brief) -> str:
    lines: List[str] = ["# ClaimKeep Brief", ""]
    if brief.created_utc:
        lines.extend(["Created: " + brief.created_utc, ""])

    def _sorted(items: List) -> List:
        return sorted(
            items,
            key=lambda claim: (
                -1.0 if claim.confidence is None else -claim.confidence,
                claim.topic,
                claim.id or "",
            ),
        )

    def _line(claim) -> str:
        confidence = (
            "unknown" if claim.confidence is None else f"{claim.confidence:.2f}"
        )
        return f"- [{confidence}] {claim.text} (topic: {claim.topic}; id: {claim.id})"

    # Lessons are rules for the next session, not facts about this one, so they
    # get their own section instead of competing for attention inside Claims.
    lesson_prefix = LESSON_TOPIC + ":"
    lessons = [claim for claim in brief.claims if claim.topic.startswith(lesson_prefix)]
    facts = [
        claim for claim in brief.claims if not claim.topic.startswith(lesson_prefix)
    ]

    active = _sorted([claim for claim in facts if claim.is_active])
    superseded = _sorted([claim for claim in facts if not claim.is_active])

    lines.append("## Claims")
    if active:
        lines.extend(_line(claim) for claim in active)
    else:
        lines.append("- None")
    lines.append("")

    if lessons:
        lines.append("## Lessons")
        for claim in lessons:
            lines.append("- " + claim.text)
        lines.append("")

    # Retracted history is listed separately and never mixed with live facts:
    # a reader must not have to guess which of two conflicting claims holds.
    if superseded:
        lines.append("## Superseded Claims")
        for claim in superseded:
            lines.append(_line(claim) + f" [superseded by: {claim.superseded_by}]")
        lines.append("")

    grouped: Dict[str, List[str]] = defaultdict(list)
    for item in brief.supplement:
        grouped[item.kind].append(item.text)
    # Empty kinds are omitted rather than rendered as "None". The brief is text
    # the agent reads after compaction, so a placeholder is not neutral: it
    # spends context to say nothing, and "path: None" reads as a finding.
    if any(grouped.get(kind) for kind in ("id", "path", "decision")):
        lines.append("## Supplement")
        for kind in ("id", "path", "decision"):
            values = grouped.get(kind, [])
            if not values:
                continue
            lines.append(f"### {kind}")
            for value in values:
                lines.append("- " + value)
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


def postcompact_payload(brief: Brief, event: str, budget_chars: int = 0) -> dict:
    """Assemble the context handed back to the agent after a compaction.

    At SessionStart the marker instruction rides along, so a fresh session is
    taught the convention the calibration harvester depends on. Repeating it on
    every PostCompact would spend budget teaching what the agent already knows —
    and, since it is part of what reaches the window, it counts against the
    budget like everything else.

    `budget_chars <= 0` means unbounded. Otherwise the cap is enforced here,
    against the finished string, because this is the only place that knows what
    the agent will actually receive.
    """

    def build(b: Brief) -> str:
        text = render(b)
        if event == "SessionStart":
            text = text + "\n" + marker_instruction()
        return text

    if budget_chars > 0:
        brief = fit_rendered(brief, budget_chars, build)
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": build(brief),
        }
    }
