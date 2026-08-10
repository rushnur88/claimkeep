"""Tests for the brief budget and the supersession chain."""

import unittest

from claimkeep.brief import Brief, Claim, Supplement
from claimkeep.select import apply_budget


def _claim(text: str, topic: str, confidence=None) -> Claim:
    return Claim(text=text, confidence=confidence, topic=topic, source_harvester="calibration")


class SupersessionTest(unittest.TestCase):
    def test_later_claim_supersedes_earlier_without_deleting_it(self):
        """A retraction must stay visible.

        The earlier behaviour dropped the older same-topic claim outright, which
        made 'this was retracted' indistinguishable from 'this was never said'.
        """
        old = _claim("Discover drives the traffic", "traffic", 0.8)
        new = _claim("Discover is zero, traffic is direct", "traffic", 0.9)
        brief = Brief(claims=[old, new])

        self.assertEqual(len(brief.claims), 2, "the superseded claim must be kept")
        self.assertEqual(len(brief.active_claims), 1)
        self.assertEqual(brief.active_claims[0].text, "Discover is zero, traffic is direct")

        kept_old = [c for c in brief.claims if c.text.startswith("Discover drives")][0]
        kept_new = brief.active_claims[0]
        self.assertEqual(kept_old.superseded_by, kept_new.id)
        self.assertEqual(kept_new.supersedes, kept_old.id)
        self.assertFalse(kept_old.is_active)

    def test_exact_repeat_is_not_a_supersession(self):
        same = _claim("Ship on Friday", "ship", 0.8)
        again = _claim("Ship on Friday", "ship", 0.8)
        brief = Brief(claims=[same, again])
        self.assertEqual(len(brief.claims), 1)
        self.assertTrue(brief.claims[0].is_active)
        self.assertIsNone(brief.claims[0].supersedes)

    def test_supersession_survives_round_trip(self):
        brief = Brief(claims=[_claim("first", "topic", 0.5), _claim("second", "topic", 0.6)])
        restored = Brief.from_json(brief.to_json())
        self.assertEqual(len(restored.claims), 2)
        self.assertEqual(len(restored.active_claims), 1)
        self.assertEqual(restored.active_claims[0].text, "second")

    def test_render_separates_superseded_from_live(self):
        brief = Brief(claims=[_claim("old fact", "topic", 0.5), _claim("new fact", "topic", 0.9)])
        rendered = brief.render()
        self.assertIn("## Claims", rendered)
        self.assertIn("## Superseded Claims", rendered)
        self.assertIn("old fact", rendered)
        head, tail = rendered.split("## Superseded Claims", 1)
        self.assertIn("new fact", head, "the live claim belongs above the retracted section")
        self.assertIn("old fact", tail)


class BudgetTest(unittest.TestCase):
    def _big_brief(self) -> Brief:
        claims = [_claim("claim number %d with some body text" % i, "topic-%d" % i, 0.9) for i in range(60)]
        supplement = [
            Supplement(text="/very/long/path/number/%d/file.py" % i, kind="path", source_harvester="regex_floor")
            for i in range(60)
        ]
        return Brief(claims=claims, supplement=supplement, source={"agent": "test"})

    def test_budget_caps_the_rendered_size(self):
        brief = self._big_brief()
        budget = 500
        trimmed = apply_budget(brief, budget)
        used = sum(len(c.text) + 1 for c in trimmed.claims) + sum(len(s.text) + 1 for s in trimmed.supplement)
        self.assertLessEqual(used, budget)
        self.assertLess(len(trimmed.claims) + len(trimmed.supplement),
                        len(brief.claims) + len(brief.supplement))

    def test_budget_reports_what_it_dropped(self):
        trimmed = apply_budget(self._big_brief(), 500)
        report = (trimmed.source or {}).get("budget")
        self.assertIsNotNone(report, "a silent cut is indistinguishable from a short session")
        self.assertEqual(report["budget_chars"], 500)
        self.assertGreater(report["dropped_items"], 0)
        self.assertEqual(report["harvested_claims"], 60)

    def test_zero_budget_means_unbounded(self):
        brief = self._big_brief()
        self.assertIs(apply_budget(brief, 0), brief)

    def test_claims_outrank_bare_paths_under_pressure(self):
        """Under a tight budget the assessed statements must win the space."""
        trimmed = apply_budget(self._big_brief(), 400)
        self.assertGreater(len(trimmed.claims), len(trimmed.supplement))

    def test_active_claims_outrank_superseded_ones(self):
        brief = Brief(claims=[_claim("stale position", "topic", 0.9), _claim("current position", "topic", 0.9)])
        trimmed = apply_budget(brief, len("current position") + 1)
        self.assertEqual([c.text for c in trimmed.claims], ["current position"])

    def test_output_keeps_harvest_order(self):
        brief = self._big_brief()
        trimmed = apply_budget(brief, 2000)
        original = [c.id for c in brief.claims]
        kept = [c.id for c in trimmed.claims]
        self.assertEqual(kept, [i for i in original if i in set(kept)])



class RuleExtractedWeightTest(unittest.TestCase):
    def test_a_marked_claim_outranks_a_rule_extracted_one(self):
        """Otherwise the atomic harvester, which is far more prolific, crowds the
        supplement floor out of the budget on agent transcripts."""
        from claimkeep.brief import Supplement
        from claimkeep.select import score_claim, score_supplement

        atomic = Claim(
            text="I moved to Austin in June",
            confidence=None,
            topic="i|move",
            source_harvester="atomic",
        )
        marked = Claim(
            text="the bridge is warm",
            confidence=0.9,
            topic="bridge",
            source_harvester="calibration",
        )
        path = Supplement(text="/etc/hosts", kind="path", source_harvester="regex_floor")

        self.assertGreater(score_claim(marked, 5, 10), score_claim(atomic, 5, 10))
        self.assertGreater(score_claim(atomic, 5, 10), score_supplement(path, 5, 10))


if __name__ == "__main__":
    unittest.main()
