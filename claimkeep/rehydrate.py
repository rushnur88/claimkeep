"""Render and hook payload helpers."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List

from .brief import Brief
from .prompt import marker_instruction
from .select import fit_rendered

# Reserved topic prefix the lesson harvester writes; kept here as a constant so
# the renderer does not import a harvester just to know one string.
LESSON_TOPIC = "lesson"


# Words that make a sentence a statement about *now*: a version, a deployment,
# a service state. These are the claims that go stale silently — the ones that
# read as current a week after they stopped being true. Both languages, because
# the harvesters are bilingual.
_LIVE_STATE = re.compile(
    # Every alternative is anchored at a word start. Without that, short roots
    # match inside longer words: "порт" fires on "паспортов" and "уже" on
    # "нужен", which marked 67% of a production corpus and made the mark
    # meaningless. Russian stems stay open-ended on the right — the language
    # inflects — but never on the left.
    r"(?i)\b(?:current(?:ly)?|latest|still|deployed|active|"
    r"version|release|commit|port)\b"
    r"|\b(?:всё ещё|все ещё)\b"
    r"|\b(?:текущ|развёрнут|развернут|верси|релиз|коммит|порт)\w*",
    re.UNICODE,
)


def asserts_live_state(text: str) -> bool:
    """Whether a claim is about the present rather than about what happened.

    Supersession cannot keep these fresh: it matches by topic, a topic comes
    from phrasing, and four sentences about one subject give four keys. So the
    render says which claims to recheck instead of pretending they are current.
    """
    return bool(_LIVE_STATE.search(text or ""))


def recorded_on(claim, fallback: str) -> str:
    """The date a claim was recorded — its own, never the time of rendering."""
    stamp = (getattr(claim, "ts", None) or fallback or "").strip()
    return stamp[:10]


def render(brief: Brief) -> str:
    lines: List[str] = ["# ClaimKeep Brief", ""]
    if brief.created_utc:
        # One statement of provenance for the whole file: everything below was
        # recorded then unless a line says otherwise.
        lines.extend([
            "recorded " + brief.created_utc + " (claims are as of this time "
            "unless a line says otherwise)",
            "",
        ])

    def _sorted(items: List) -> List:
        return sorted(
            items,
            key=lambda claim: (
                -1.0 if claim.confidence is None else -claim.confidence,
                claim.topic,
                claim.id or "",
            ),
        )

    brief_date = (brief.created_utc or "")[:10]

    def _line(claim) -> str:
        confidence = (
            "unknown" if claim.confidence is None else f"{claim.confidence:.2f}"
        )
        parts = [confidence]
        # The date only when it differs from the brief's own, which the header
        # states once. Repeating an identical date on every line cost about 25
        # characters each, and at a fixed budget that is fewer facts carried —
        # measured, it moved the headline result by nearly three points. What
        # needs saying is which claims are *older* than the brief around them.
        recorded = recorded_on(claim, brief.created_utc)
        if recorded and recorded != brief_date:
            parts.append("recorded " + recorded)
        if asserts_live_state(claim.text):
            parts.append("VERIFY CURRENT")
        head = " · ".join(p for p in parts if p.strip())
        return f"- [{head}] {claim.text} (topic: {claim.topic}; id: {claim.id})"

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
