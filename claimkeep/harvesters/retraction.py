"""Corrections: what turned out to be wrong, and who said so.

Ported from the fleet PreCompact hook (2026-08-10), where these two passes came
out of a year of real multi-agent work rather than design.

**Why a retraction is the most valuable line in a brief.** After compaction the
agent keeps whatever survived and states it with the same confidence as before.
If the surviving set contains a claim that was later refuted, the agent will
confidently repeat something it already knows to be false — the one failure mode
a memory layer must never produce. So a retraction is not just another claim: it
has to survive the budget, and it has to be found first.

**Why corrections from other speakers need their own pass.** In a multi-agent
setup, a sister's correction arrives through the relay as a *user* turn. It is
structurally outside the agent's own claim stream, so a harvester that only
reads assistant text loses it — and with it the fact that a conclusion was
overturned by someone else. The fleet measured this exactly: the refutation that
mattered came from another agent, and every assistant-only pass missed it.

Both passes are gated on substance rather than keyword alone, because "снял" or
"scratch that" on its own carries no fact worth keeping.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from ..brief import Claim, normalize
from ..config import Config
from .base import Harvester

# Retraction / correction signal, English and Russian. The fleet hook needed both
# scripts from the start; an English-only pattern silently harvests nothing on a
# Russian transcript rather than failing loudly.
# Two patterns rather than one: English keys need a trailing word boundary,
# Russian stems must not have one. `\bпоправк\b` never matches "поправка" —
# the boundary falls inside the word. The fleet hook learned this the same way,
# by silently harvesting nothing from Russian turns.
RETRACT_EN_RX = re.compile(
    r"(?i)\b(retract(?:ed|ion)?|refute[sd]?|refutation|correction|corrected|"
    r"was wrong|were wrong|not true|turns out|scratch that|disproved|disproven|"
    r"overturn(?:ed)?|supersede[sd]?|no longer holds)\b"
)
RETRACT_RU_RX = re.compile(
    r"(?i)(ошиб(?:лась|ся|ка|ки)|неверно|неправильно|опроверг|поправк|исправл(?:ение|яю)|"
    r"уточн(?:ение|яю)|на самом деле|снимаю|беру свои слова|"
    r"отмен(?:яю|ено)|ты прав|была не права|оказалось не|не подтвердилось)"
)


def _is_retraction(line: str) -> bool:
    return bool(RETRACT_EN_RX.search(line) or RETRACT_RU_RX.search(line))


# A distinctive token: long enough to identify a subject, not a stopword.
_TOKEN_RX = re.compile(r"[\wЀ-ӿ]{4,}")
_ID_RX = re.compile(r"\b(?:[0-9a-f]{7,40}|[A-Z]+-\d+|#\d+)\b")
_NUM_RX = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")

_STOP = {
    "that",
    "this",
    "with",
    "from",
    "have",
    "been",
    "what",
    "when",
    "which",
    "there",
    "their",
    "would",
    "could",
    "should",
    "about",
    "after",
    "before",
    "быть",
    "было",
    "этот",
    "этом",
    "того",
    "тоже",
    "чтобы",
    "потому",
    "когда",
}

MIN_LEN = 24
MAX_LEN = 360
ASSISTANT_MIN_TOKENS = 4
# User text is noisier than the agent's own, so an external correction has to
# carry more substance before it is believed.
EXTERNAL_MIN_TOKENS = 5


def _tokens(text: str) -> set:
    return {t.casefold() for t in _TOKEN_RX.findall(text) if t.casefold() not in _STOP}


def entity_signature(text: str) -> set:
    """Ids and numbers in a line — the strongest cross-phrasing anchor.

    Two lines about the same fact rarely share wording, but they do share the
    commit hash, the ticket number or the measured value.
    """
    return set(_ID_RX.findall(text)) | set(_NUM_RX.findall(text))


def _correction_topic(line: str, external: bool) -> str:
    """A topic per corrected thing, not one topic for "corrections".

    Every retraction used to share `retraction:external`, on the reasoning that
    newest-wins within the class is right — "an older correction about the same
    thing is itself superseded". The class is not one thing, though: supersession
    reads one topic as one subject restated, so the second correction of a
    session retired the first. "The port is 4444, not 3333" went inactive because
    "the retry ceiling is 9, not 5" came after it. A correction is the most
    valuable line in a brief; losing one to an unrelated correction is the same
    outcome as never harvesting it.

    The ids and numbers in the line are the anchor — two corrections of one value
    share them, two corrections of different values do not.
    """
    base = "retraction:external" if external else "retraction"
    signature = sorted(entity_signature(line))
    if signature:
        return base + ":" + "-".join(signature[:3])
    words = [w for w in _TOKEN_RX.findall(line) if w.casefold() not in _STOP][:4]
    return base + ":" + "-".join(w.casefold() for w in words) if words else base


def refutes(retraction: str, claim: str) -> bool:
    """True when the retraction plausibly overturns that specific claim."""
    if entity_signature(retraction) & entity_signature(claim):
        return True
    return len(_tokens(retraction) & _tokens(claim)) >= 2


def _units(transcript: Sequence) -> List[Tuple[str, str]]:
    """Accept both shapes: plain strings, or (role, text) pairs.

    The package has always passed plain strings. Roles matter here and nowhere
    else so far, so the interface widens instead of breaking: a bare string is
    treated as assistant text, which is what it always was.
    """
    out: List[Tuple[str, str]] = []
    for unit in transcript:
        if isinstance(unit, (tuple, list)) and len(unit) == 2:
            out.append((str(unit[0]), str(unit[1])))
        else:
            out.append(("assistant", str(unit)))
    return out


class RetractionHarvester(Harvester):
    """Lines that overturn something, from the agent and from anyone else."""

    name = "retraction"

    def harvest(self, transcript: Sequence, config: Config) -> List[Claim]:
        items: List[Claim] = []
        seen = set()
        for role, text in _units(transcript):
            external = role != "assistant"
            floor = EXTERNAL_MIN_TOKENS if external else ASSISTANT_MIN_TOKENS
            for line in text.splitlines():
                line = line.strip()
                if not (MIN_LEN <= len(line) <= MAX_LEN):
                    continue
                if not _is_retraction(line):
                    continue
                if not (entity_signature(line) or len(_tokens(line)) >= floor):
                    continue
                key = normalize(line)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    Claim(
                        text=line,
                        confidence=None,
                        topic=_correction_topic(line, external),
                        source_harvester=self.name,
                    )
                )
        return items
