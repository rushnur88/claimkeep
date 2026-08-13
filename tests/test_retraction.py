"""Tests for the retraction / external-correction harvester.

The cases are the fleet's, not invented: each one is a shape that the fleet hook
had to grow a rule for after losing a real fact to it.
"""

import unittest

from claimkeep.brief import Claim
from claimkeep.config import default_config
from claimkeep.harvesters.retraction import (
    RetractionHarvester,
    entity_signature,
    refutes,
)
from claimkeep.select import score_claim


class RetractionTest(unittest.TestCase):
    def setUp(self):
        self.harvester = RetractionHarvester()
        self.config = default_config()

    def test_the_agents_own_correction_is_kept(self):
        items = self.harvester.harvest(
            [("assistant", "Ты прав, я ошиблась: R@10 не 0.936, а 0.958 — перезамерила")],
            self.config,
        )
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].topic.startswith("retraction"), items[0].topic)
        self.assertFalse(items[0].topic.startswith("retraction:external"))

    def test_a_correction_from_another_speaker_is_kept_and_marked(self):
        """A sister's correction arrives as a user turn. An assistant-only pass
        loses it, and with it the fact that a conclusion was overturned."""
        items = self.harvester.harvest(
            [("user", "Поправка от сестры: коммитов было 10, а не 9, и дерево было грязное")],
            self.config,
        )
        self.assertEqual(len(items), 1)
        # The topic now carries which value was corrected, so that two
        # unrelated corrections do not retire each other.
        self.assertTrue(items[0].topic.startswith("retraction:external"), items[0].topic)

    def test_english_and_russian_both_match(self):
        items = self.harvester.harvest(
            [
                ("user", "Correction: the branch was 10 commits ahead, not 9, tree dirty"),
                ("user", "Поправка: веток было десять, а не девять, дерево грязное"),
            ],
            self.config,
        )
        self.assertEqual(len(items), 2)

    def test_a_bare_signal_word_is_not_substance(self):
        """"снял" or "scratch that" alone carries no fact worth a budget slot."""
        self.assertEqual(self.harvester.harvest([("user", "снял")], self.config), [])
        self.assertEqual(
            self.harvester.harvest([("assistant", "scratch that")], self.config), []
        )

    def test_plain_strings_still_work(self):
        """The package has always passed plain strings; roles widen the interface
        rather than break it."""
        items = self.harvester.harvest(
            ["Ты прав, я ошиблась — дело было в отборе, а не в форме извлечения"],
            self.config,
        )
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].topic.startswith("retraction"), items[0].topic)
        self.assertFalse(items[0].topic.startswith("retraction:external"))

    def test_ordinary_statements_are_left_alone(self):
        items = self.harvester.harvest(
            [("assistant", "Коммит 379ec48 прошёл, 71 тест зелёный, ветка запушена")],
            self.config,
        )
        self.assertEqual(items, [])


class CrossPhrasingTest(unittest.TestCase):
    def test_a_shared_identifier_links_differently_worded_lines(self):
        """Two lines about one fact rarely share wording — they share the hash."""
        self.assertTrue(
            refutes(
                "Correction: commit 379ec48 did not include the benchmark",
                "379ec48 shipped the benchmark and the harvester",
            )
        )

    def test_shared_content_tokens_link_them_too(self):
        self.assertTrue(
            refutes(
                "я ошиблась: индексация дат ухудшила многосессионные вопросы",
                "индексация дат поднимет многосессионные вопросы",
            )
        )

    def test_unrelated_lines_do_not_link(self):
        self.assertFalse(
            refutes("Correction: the tree was dirty", "The dog is a King Charles Spaniel")
        )

    def test_entity_signature_picks_up_ids_and_numbers(self):
        sig = entity_signature("commit 379ec48 raised R@10 to 0.958")
        self.assertIn("379ec48", sig)
        self.assertTrue(any("958" in s for s in sig))


class PriorityTest(unittest.TestCase):
    def test_a_retraction_outranks_a_marked_claim(self):
        """A refuted claim that outlives its refutation is the failure mode this
        whole harvester exists to prevent, so it wins the budget."""
        retraction = Claim(
            text="Ты прав, я ошиблась: R@10 не 0.936, а 0.958",
            confidence=None,
            topic="retraction",
            source_harvester="retraction",
        )
        marked = Claim(
            text="the bridge is warm",
            confidence=0.9,
            topic="bridge",
            source_harvester="calibration",
        )
        self.assertGreater(score_claim(retraction, 5, 10), score_claim(marked, 5, 10))


if __name__ == "__main__":
    unittest.main()
