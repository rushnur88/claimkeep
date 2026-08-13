"""A stored claim must say when it was recorded, and say so about *then*.

A brief carries what was true when it was written. Re-injected a day later it
reads as a statement about now, and the reader has no way to tell — on a
production store, sentences saying the current version was 0.2.0 sat in a brief
rendered after 0.3.1 shipped, with nothing marking them as history.

Supersession cannot close this. It matches claims by topic, and a topic is
derived from phrasing, so four sentences about one subject produced four keys
and no link. Rather than pretend otherwise, the render states the recording date
and, for claims that assert a live state, marks them for rechecking.

The date is the one the claim was harvested with, never the time of rendering:
a brief re-read a week later must still say when it was written.
"""

import unittest

from claimkeep.brief import Brief, Claim
from claimkeep.rehydrate import render


def claim(text, topic="t", ts=None, confidence=0.9):
    return Claim(
        text=text,
        confidence=confidence,
        topic=topic,
        source_harvester="calibration",
        ts=ts,
        source_span=text,
    )


def brief_with(*claims, created="2026-08-13T00:00:00Z"):
    return Brief(
        created_utc=created,
        source={"agent": "t", "session": "s"},
        claims=list(claims),
        supplement=[],
    )


class TestRecordedDate(unittest.TestCase):
    def test_the_render_states_when_a_claim_was_recorded(self):
        # Stated once in the header for the whole file. Repeating an identical
        # date on every line spends budget that carries facts instead.
        out = render(brief_with(claim("The dashboard port is 3333")))
        self.assertIn("recorded", out)
        self.assertIn("2026-08-13", out)
        self.assertEqual(out.count("recorded"), 1)

    def test_the_date_is_the_claims_own_not_the_briefs(self):
        # A lesson carried forward from an older session keeps its own date.
        out = render(
            brief_with(
                claim("The retry ceiling is 5", ts="2026-07-01T10:00:00Z"),
                created="2026-08-13T00:00:00Z",
            )
        )
        # The claim's own date is on its line; the header still carries the
        # brief's, which is what the header is for.
        claim_line = [l for l in out.split("\n") if l.startswith("- ")][0]
        self.assertIn("recorded 2026-07-01", claim_line)
        self.assertNotIn("2026-08-13", claim_line)

    def test_rendering_twice_does_not_move_the_date(self):
        b = brief_with(claim("The dashboard port is 3333"))
        self.assertEqual(render(b), render(b))
        self.assertIn("2026-08-13", render(b))


class TestVerifyCurrentMarking(unittest.TestCase):
    """Claims asserting a live state are the ones that go stale silently."""

    LIVE = [
        "The current version is 0.2.0",
        "The latest commit is d8d158b",
        "pyproject still reports 0.2.0",
        "The gateway is active on port 3333",
        "The package is deployed to production",
        "Сейчас на проде версия 0.2.0",
        "Репозиторий всё ещё на старом коммите",
    ]
    HISTORICAL = [
        "We chose sqlite over postgres because of the write pattern",
        "The bug was caused by a missing index",
        "Ravshan asked for the Russian tokenizer fix",
    ]

    def test_live_state_claims_are_marked(self):
        for text in self.LIVE:
            out = render(brief_with(claim(text)))
            self.assertIn("VERIFY CURRENT", out, text)

    def test_settled_facts_are_not_marked(self):
        for text in self.HISTORICAL:
            out = render(brief_with(claim(text)))
            self.assertNotIn("VERIFY CURRENT", out, text)

    def test_the_marking_survives_into_the_hook_payload(self):
        from claimkeep.rehydrate import postcompact_payload

        payload = postcompact_payload(
            brief_with(claim("The current version is 0.2.0")), "PostCompact"
        )
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("VERIFY CURRENT", ctx)
        self.assertIn("recorded", ctx)


if __name__ == "__main__":
    unittest.main()
