"""The confidence-marker instruction the plugin ships with.

The calibration harvester only sees claims an agent has already marked with
`[C:NN%]`. That made the strongest half of ClaimKeep useless to anyone who had
not independently adopted the habit — the plugin required a convention it did
not supply. This module supplies it.

The text is deliberately short. A long instruction competes for the same window
the plugin is trying to protect, and an agent that ignores a five-line rule will
ignore a fifty-line one.
"""

from __future__ import annotations

MARKER_INSTRUCTION = """\
## Confidence markers

End any statement of fact with a confidence marker: `[C:NN%, basis: <=5 words]`.

- 95-100% — immutable evidence you can point at (a commit hash, a quoted spec, a
  screenshot). Would you bet 19:1 on it? If you would hesitate, it is not 95%.
- 80-94% — you verified it once, just now. Most "I just checked" claims live here:
  a single live read can be stale or wrong.
- 65-79% — inference from indirect evidence, or recall without a fresh check.
- 50-64% — informed guess. Say so.
- Below 50% — say you do not know instead.

Mark file paths, numbers, identifiers, dates, versions, and status claims
("running", "deployed", "passing"). Skip markers on greetings, questions,
opinions, and instructions.

Markers are not decoration. They are how a claim survives context compaction:
an unmarked assertion looks exactly like small talk to anything reading the
transcript afterwards, including you.
"""


def marker_instruction() -> str:
    """Return the instruction fragment to append to an agent's system prompt."""
    return MARKER_INSTRUCTION
