"""A corrected fact must chain even when the agent marked its confidence.

The calibration topic used to be a slug of the leading words, which embeds the
value being stated: "the retry ceiling is 5" and "the retry ceiling is 4" landed
on different topics, so supersession never fired on the corrections it exists to
track. The more disciplined the agent was about markers, the less the chain
worked. These tests fail against that version.
"""

import unittest

from claimkeep.brief import Brief
from claimkeep.config import Config
from claimkeep.harvesters.calibration import CalibrationHarvester, _topic


class TestTopicIsStableAcrossCorrection(unittest.TestCase):
    def test_same_subject_and_predicate_share_a_topic(self):
        self.assertEqual(
            _topic("The retry ceiling is 5"), _topic("The retry ceiling is 4")
        )

    def test_topic_uses_the_atomic_key(self):
        self.assertEqual(_topic("The retry ceiling is 5"), "retry|ceil")

    def test_unrelated_facts_do_not_collide(self):
        self.assertNotEqual(
            _topic("The retry ceiling is 5"),
            _topic("The gateway reads its token from /etc/aria/proxy.env"),
        )

    def test_unparsable_sentence_falls_back_to_slug(self):
        """A stable-looking key that is wrong would merge unrelated facts."""
        self.assertEqual(
            _topic("Ship ClaimKeep package Friday"), "ship-claimkeep-package-friday"
        )


class TestMarkedClaimsSupersede(unittest.TestCase):
    def _harvest(self, lines):
        claims = CalibrationHarvester().harvest(lines, Config())
        return Brief(claims=claims)

    def test_correction_marks_the_earlier_claim(self):
        brief = self._harvest(
            ["The retry ceiling is 5 [C:70%]", "The retry ceiling is 4 [C:95%]"]
        )
        by_text = {c.text: c for c in brief.claims}
        old, new = by_text["The retry ceiling is 5"], by_text["The retry ceiling is 4"]
        self.assertEqual(old.superseded_by, new.id)
        self.assertEqual(new.supersedes, old.id)
        self.assertIsNone(new.superseded_by)

    def test_confidence_survives_the_change(self):
        brief = self._harvest(
            ["The retry ceiling is 5 [C:70%]", "The retry ceiling is 4 [C:95%]"]
        )
        self.assertEqual({c.confidence for c in brief.claims}, {0.7, 0.95})

    def test_no_duplicate_of_the_same_fact(self):
        brief = self._harvest(["The retry ceiling is 4 [C:95%]"])
        self.assertEqual(len(brief.claims), 1)

    def test_text_stays_verbatim(self):
        brief = self._harvest(
            ["The gateway reads its token from /etc/aria/proxy.env [C:90%]"]
        )
        self.assertEqual(
            brief.claims[0].text, "The gateway reads its token from /etc/aria/proxy.env"
        )


if __name__ == "__main__":
    unittest.main()
