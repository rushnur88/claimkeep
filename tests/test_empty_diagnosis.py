"""An unmeasurable count must name the right reason.

Both "these briefs hold no claims" and "these briefs came from another tool"
arrive as zero labelled claims, and the report used to print the second
explanation for both. Telling someone their briefs were written by a foreign
collector, when in fact the session simply stated no facts, sends them looking
for a problem that does not exist. These tests fail against that version.
"""

import json
import os
import tempfile
import unittest

from claimkeep.config import Config
from claimkeep.stats import collect, render


def brief(claims):
    return {
        "schema_version": 1,
        "created_utc": "2026-08-11T00:00:00Z",
        "source": {"agent": "claude-code", "session": "s"},
        "claims": claims,
        "supplement": [],
    }


OURS = [
    {
        "id": "a1",
        "text": "The retry ceiling is 4",
        "confidence": 0.9,
        "topic": "retry|ceil",
        "source_harvester": "calibration",
        "ts": None,
        "source_span": None,
    }
]
FOREIGN = [
    {
        "id": "b1",
        "text": "Some fact from another tool",
        "confidence": 0.8,
        "topic": "some-fact",
        "source_harvester": "someone_elses_collector",
        "ts": None,
        "source_span": None,
    }
]


class DiagnosisNamesTheRightCause(unittest.TestCase):
    def _text(self, claims):
        with tempfile.TemporaryDirectory() as tmp:
            with open(
                os.path.join(tmp, "20260811T000000Z-b.json"), "w", encoding="utf-8"
            ) as fh:
                json.dump(brief(claims), fh)
            cfg = Config()
            cfg.brief_dir = tmp
            return render(collect(cfg))

    def test_no_claims_is_not_blamed_on_a_foreign_collector(self):
        text = self._text([])
        self.assertIn("no claims at all", text)
        self.assertNotIn("different collector", text)

    def test_foreign_collector_is_still_named_when_it_is_the_cause(self):
        text = self._text(FOREIGN)
        self.assertIn("different collector", text)
        self.assertNotIn("no claims at all", text)

    def test_a_healthy_corpus_reports_a_number(self):
        text = self._text(OURS)
        self.assertIn("Retractions: 0", text)
        # Scope the check to the retraction line: the lessons line may legitimately
        # say "not measurable" when no lesson store exists, which is a different fact.
        self.assertNotIn("Retractions: not measurable", text)


class ReservedFieldsAreDocumentedAsReserved(unittest.TestCase):
    """The producer never fills these; the contract has to say so."""

    def test_schema_marks_them_reserved(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        doc = open(
            os.path.join(here, "docs", "BRIEF_SCHEMA.md"), encoding="utf-8"
        ).read()
        self.assertIn("reserved and not produced", doc)

    def test_producer_really_does_not_fill_them(self):
        from claimkeep.brief import Brief

        b = Brief(claims=[], supplement=[], created_utc="2026-08-11T00:00:00Z")
        self.assertEqual(b.open_threads, [])
        self.assertEqual(b.narrative, [])
        self.assertIsNone(b.last_user_ask)


if __name__ == "__main__":
    unittest.main()
