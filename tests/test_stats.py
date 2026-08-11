"""Tests for the stats report.

The interesting case is not the arithmetic — it is the zero. A brief written
by a different collector carries no harvester labels, so a naive count of
retractions returns 0 and reads exactly like "nothing was retracted". This
project spent a full day chasing zeros of that shape, so the report has to
distinguish "measured zero" from "cannot measure here".
"""

import json
import os
import tempfile
import unittest

from claimkeep.config import Config
from claimkeep.stats import collect, render


def _write(dirpath, name, claims, created="2026-08-10T00:00:00Z", supplement=None):
    payload = {
        "schema_version": 1,
        "created_utc": created,
        "source": None,
        "claims": claims,
        "supplement": supplement or [],
    }
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _claim(text, harvester, topic, confidence=None, superseded_by=None):
    return {
        "text": text,
        "topic": topic,
        "source_harvester": harvester,
        "confidence": confidence,
        "superseded_by": superseded_by,
        "id": text[:8],
    }


class StatsTest(unittest.TestCase):
    def test_counts_from_labelled_briefs(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.json", [
                _claim("I moved to Boston", "atomic", "i|move"),
                _claim("Correction: it was Postgres", "retraction", "retraction"),
                _claim("the build is green", "calibration", "build", confidence=0.8),
            ], supplement=[{"text": "379ec48", "kind": "id", "source_harvester": "regex_floor"}])
            report = collect(Config(brief_dir=d, lessons_enabled=False))

        self.assertEqual(report["briefs"], 1)
        self.assertEqual(report["claims_total"], 3)
        self.assertEqual(report["retractions"], 1)
        self.assertEqual(report["marked_claims"], 1)
        self.assertEqual(report["mean_confidence"], 0.8)
        self.assertEqual(report["supplement_by_kind"], {"id": 1})
        self.assertIn("Retractions: 1", render(report))

    def test_a_retraction_is_counted_from_either_signal(self):
        """Harvester name and topic are independent survivors of a round-trip;
        either one alone must still identify the claim."""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.json", [
                _claim("topic only", "unknown_collector", "retraction:external"),
                _claim("harvester only", "retraction", "whatever"),
            ])
            report = collect(Config(brief_dir=d, lessons_enabled=False))
        self.assertEqual(report["retractions"], 2)

    def test_unlabelled_briefs_report_not_measurable_instead_of_zero(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.json", [
                _claim("some fact from another tool", "fleet_precompact", "free text topic"),
            ])
            report = collect(Config(brief_dir=d, lessons_enabled=False))
            text = render(report)

        self.assertEqual(report["labelled_claims"], 0)
        self.assertNotIn("Retractions: 0", text)
        self.assertIn("not measurable", text)

    def test_empty_store_says_so_without_inventing_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            report = collect(Config(brief_dir=d, lessons_enabled=False))
            text = render(report)
        self.assertEqual(report["briefs"], 0)
        self.assertIn("No briefs stored yet", text)

    def test_a_corrupt_brief_does_not_take_down_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "good.json", [_claim("fine", "atomic", "t")])
            with open(os.path.join(d, "bad.json"), "w", encoding="utf-8") as handle:
                handle.write("{not json")
            report = collect(Config(brief_dir=d, lessons_enabled=False))
        self.assertEqual(report["briefs"], 1)
        self.assertEqual(report["claims_total"], 1)

    def test_superseded_claims_are_counted(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.json", [
                _claim("old", "atomic", "t", superseded_by="abc123"),
                _claim("new", "atomic", "t"),
            ])
            report = collect(Config(brief_dir=d, lessons_enabled=False))
        self.assertEqual(report["superseded"], 1)

    def test_a_missing_lesson_store_is_not_reported_as_zero(self):
        """The same zero as retractions, one line down: LessonStore.load()
        returns [] for a file that was never created, which reads exactly like
        "no lesson was ever carried forward"."""
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.json", [_claim("fact", "atomic", "t")])
            missing = os.path.join(d, "never_created.jsonl")
            report = collect(Config(brief_dir=d, lessons_enabled=True, lessons_path=missing))
            text = render(report)

        self.assertFalse(report["lessons_store_found"])
        self.assertNotIn("Lessons carried forward: 0", text)
        self.assertIn("no lesson store", text)
        self.assertIn(missing, text)

    def test_an_existing_but_empty_lesson_store_reports_an_honest_zero(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.json", [_claim("fact", "atomic", "t")])
            present = os.path.join(d, "lessons.jsonl")
            open(present, "w", encoding="utf-8").close()
            report = collect(Config(brief_dir=d, lessons_enabled=True, lessons_path=present))
            text = render(report)

        self.assertTrue(report["lessons_store_found"])
        self.assertEqual(report["lessons_total"], 0)
        self.assertIn("Lessons carried forward: 0", text)
        self.assertNotIn("no lesson store", text)


if __name__ == "__main__":
    unittest.main()
