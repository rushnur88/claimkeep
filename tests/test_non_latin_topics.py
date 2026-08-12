"""A non-Latin claim must get a topic of its own.

The slug matched `[A-Za-z0-9_./#-]`, so a sentence written entirely in Cyrillic
produced no words and fell back to the literal topic "claim". Sharing one topic
is not harmless: dedup reads a topic as one subject restated over time, so three
unrelated Russian statements went in and two came back flagged as superseded by
the third — the brief actively told the agent that true facts had been retracted.
These tests fail against that version.
"""

import unittest

from claimkeep.brief import Brief
from claimkeep.config import Config
from claimkeep.harvesters.calibration import CalibrationHarvester, _slug_topic, _topic

RUSSIAN = [
    "Воспроизвела ошибку в гейтвее, она в порядке загрузки переменных",
    "Настя закончила курс медсестры в июне",
    "Ночной бэкап памяти флота идёт в четыре утра",
]


class NonLatinGetsARealTopic(unittest.TestCase):
    def test_cyrillic_does_not_collapse_to_the_fallback(self):
        for line in RUSSIAN:
            with self.subTest(line=line):
                self.assertNotEqual(_topic(line), "claim")

    def test_unrelated_russian_facts_get_distinct_topics(self):
        topics = [_topic(line) for line in RUSSIAN]
        self.assertEqual(len(set(topics)), len(topics))

    def test_other_scripts_work_too(self):
        for line in ("Το αρχείο βρίσκεται εδώ", "服务器在四点重启", "השרת מופעל מחדש"):
            with self.subTest(line=line):
                self.assertNotEqual(_slug_topic(line), "claim")

    def test_latin_and_paths_are_unchanged(self):
        self.assertEqual(
            _topic("Ship ClaimKeep package Friday"), "ship-claimkeep-package-friday"
        )
        self.assertIn(
            "/tmp/claimkeep/brief.json",
            _slug_topic("Use /tmp/claimkeep/brief.json now"),
        )
        # English still routes through the atomic key, which is what makes
        # supersession chain for it.
        self.assertEqual(_topic("The retry ceiling is 5"), "retry|ceil")


class NoFalseSupersession(unittest.TestCase):
    def test_unrelated_russian_claims_do_not_retract_each_other(self):
        lines = [f"{line} [C:90%]" for line in RUSSIAN]
        brief = Brief(claims=CalibrationHarvester().harvest(lines, Config()))
        self.assertEqual(len(brief.claims), 3, "no claim should be collapsed away")
        flagged = [c for c in brief.claims if c.superseded_by]
        self.assertEqual(flagged, [], "a true fact must not be reported as retracted")


if __name__ == "__main__":
    unittest.main()
