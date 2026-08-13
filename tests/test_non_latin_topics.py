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
        # "ceiling" ends in -ing but is the subject here; the copula decides
        # the split, so the key is the whole subject against "be".
        self.assertEqual(_topic("The retry ceiling is 5"), "retry ceiling|be")


class NoFalseSupersession(unittest.TestCase):
    def test_unrelated_russian_claims_do_not_retract_each_other(self):
        lines = [f"{line} [C:90%]" for line in RUSSIAN]
        brief = Brief(claims=CalibrationHarvester().harvest(lines, Config()))
        self.assertEqual(len(brief.claims), 3, "no claim should be collapsed away")
        flagged = [c for c in brief.claims if c.superseded_by]
        self.assertEqual(flagged, [], "a true fact must not be reported as retracted")


if __name__ == "__main__":
    unittest.main()


class TestDegenerateSlugsDoNotGroup(unittest.TestCase):
    """A topic made of punctuation is not a topic, and must not group anything.

    `_SLUG_WORD` accepted runs of pure punctuation, so a sentence whose leading
    tokens were "." or "—" produced topics like `.` and `.-.`. On a real corpus
    of 271 briefs that put 39 unrelated statements under `.-.` and 26 under `.`.
    While supersession only ran inside one brief this was nearly invisible; once
    it settled topics across the whole corpus, those groups started marking each
    other as corrections — 1% of claims superseded became 18.4%, almost all of
    it wrong.
    """

    def test_punctuation_is_not_part_of_the_slug(self):
        topic = _slug_topic(". Генерация завершена успешно.")
        self.assertNotIn(".", topic)
        self.assertIn("генерация", topic)

    def test_two_unrelated_punctuation_only_texts_get_different_topics(self):
        first = _slug_topic("...")
        second = _slug_topic("—— ——")
        self.assertNotEqual(first, second,
                            "unrelated statements share a topic and will supersede")

    def test_identical_text_still_shares_a_topic(self):
        # Same statement restated is the one case that should collapse.
        self.assertEqual(_slug_topic("..."), _slug_topic("..."))

    def test_a_real_sentence_is_unaffected(self):
        self.assertEqual(_slug_topic("Проверяю живой статус задачи"),
                         "проверяю-живой-статус-задачи")
