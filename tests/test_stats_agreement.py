"""The two `stats` outputs must say the same thing.

README calls `--json` the same numbers, machine-readable. They were not the
same: the human line said "not measurable" while the JSON reported `0` for the
same corpus. A consumer graphing retractions would read a clean zero off an
unlabelled corpus and never learn the count was never available — the exact
"zero you cannot distinguish from never happened" the report is not allowed to
produce. These tests fail against that version.
"""

import json
import os
import tempfile
import unittest

from claimkeep.config import Config
from claimkeep.stats import collect, render

FOREIGN = {
    "schema_version": 1,
    "created_utc": "2026-08-11T00:00:00Z",
    "claims": [
        {
            "id": "aaa1",
            "text": "Some fact from another tool",
            "confidence": 0.8,
            "topic": "some-fact",
            "source_harvester": "someone_elses_collector",
            "ts": None,
            "source_span": None,
        }
    ],
    "supplement": [],
}

OURS = {
    "schema_version": 1,
    "created_utc": "2026-08-11T00:00:00Z",
    "claims": [
        {
            "id": "bbb1",
            "text": "Correction: the port binding is fine",
            "confidence": 0.9,
            "topic": "retraction",
            "source_harvester": "retraction",
            "ts": None,
            "source_span": None,
        }
    ],
    "supplement": [],
}


class StatsAgreement(unittest.TestCase):
    def _report(self, brief):
        with tempfile.TemporaryDirectory() as tmp:
            with open(
                os.path.join(tmp, "20260811T000000Z-x.json"), "w", encoding="utf-8"
            ) as fh:
                json.dump(brief, fh)
            cfg = Config()
            cfg.brief_dir = tmp
            return collect(cfg), render(collect(cfg))

    def test_foreign_corpus_reports_null_not_zero(self):
        report, text = self._report(FOREIGN)
        self.assertIsNone(report["retractions"], "0 would read as 'none happened'")
        self.assertFalse(report["retractions_measurable"])
        self.assertIn("not measurable", text)

    def test_labelled_corpus_reports_a_number_in_both(self):
        report, text = self._report(OURS)
        self.assertTrue(report["retractions_measurable"])
        self.assertEqual(report["retractions"], 1)
        self.assertIn("Retractions: 1", text)
        self.assertNotIn("not measurable — no claim", text)

    def test_the_two_outputs_never_disagree(self):
        """Whatever the corpus, 'not measurable' in text implies null in JSON."""
        for brief in (FOREIGN, OURS):
            with self.subTest(brief=brief["claims"][0]["source_harvester"]):
                report, text = self._report(brief)
                said_unmeasurable = "Retractions: not measurable" in text
                self.assertEqual(said_unmeasurable, report["retractions"] is None)
                self.assertEqual(
                    said_unmeasurable, not report["retractions_measurable"]
                )

    def test_absent_lesson_store_is_null_not_zero(self):
        report, text = self._report(OURS)
        if not report["lessons_store_found"]:
            self.assertIsNone(report["lessons_total"])
            self.assertIn("Lessons carried forward: not measurable", text)


if __name__ == "__main__":
    unittest.main()
