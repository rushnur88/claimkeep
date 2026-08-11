"""What the budget threw away has to appear in the report.

`Claims kept: 184` reads as the whole harvest. On a long transcript it can be
0.5% of it, with the other 99.5% dropped to fit `budget_chars` — a number the
brief records and the report used to omit. Kept without harvested is the same
unanswerable figure as a retraction count with nothing to compare it against.
These tests fail against that version.
"""

import json
import os
import tempfile
import unittest

from claimkeep.config import Config
from claimkeep.stats import collect, render


def brief(claims, budget=None):
    source = {"agent": "claude-code", "session": "s"}
    if budget is not None:
        source["budget"] = budget
    return {
        "schema_version": 1,
        "created_utc": "2026-08-11T00:00:00Z",
        "source": source,
        "claims": [
            {
                "id": f"id{i}",
                "text": f"Fact {i}",
                "confidence": 0.9,
                "topic": f"t{i}",
                "source_harvester": "calibration",
                "ts": None,
                "source_span": None,
            }
            for i in range(claims)
        ],
        "supplement": [],
    }


class BudgetVisibility(unittest.TestCase):
    def _run(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            with open(
                os.path.join(tmp, "20260811T000000Z-b.json"), "w", encoding="utf-8"
            ) as fh:
                json.dump(payload, fh)
            cfg = Config()
            cfg.brief_dir = tmp
            report = collect(cfg)
            return report, render(report)

    def test_a_large_drop_is_reported(self):
        report, text = self._run(
            brief(
                2,
                budget={
                    "harvested_claims": 2000,
                    "dropped_items": 3998,
                    "budget_chars": 12000,
                },
            )
        )
        self.assertEqual(report["dropped_items"], 3998)
        self.assertEqual(report["harvested_claims"], 2000)
        self.assertTrue(report["budget_measurable"])
        self.assertIn("Dropped by budget: 3998", text)

    def test_the_kept_share_is_stated(self):
        """A raw count does not tell you whether the budget is the bottleneck."""
        _, text = self._run(
            brief(
                2,
                budget={
                    "harvested_claims": 2000,
                    "dropped_items": 3998,
                    "budget_chars": 12000,
                },
            )
        )
        self.assertIn("0.1% of harvested claims fit the brief", text)

    def test_no_drop_means_no_extra_line(self):
        _, text = self._run(
            brief(
                2,
                budget={
                    "harvested_claims": 2,
                    "dropped_items": 0,
                    "budget_chars": 12000,
                },
            )
        )
        self.assertNotIn("Dropped by budget", text)

    def test_absent_budget_is_null_not_zero(self):
        """A foreign brief records no budget; 0 dropped would be a claim we cannot make."""
        report, text = self._run(brief(1))
        self.assertIsNone(report["dropped_items"])
        self.assertIsNone(report["harvested_claims"])
        self.assertFalse(report["budget_measurable"])
        self.assertNotIn("Dropped by budget", text)


if __name__ == "__main__":
    unittest.main()
