"""Tests for the atomic fact harvester.

Each case here is a sentence class that the LongMemEval run either mishandled
before this harvester existed, or that the harvester had to be tightened to get
right. They are regression tests for measured failures, not invented examples.
"""

import unittest

from claimkeep.config import default_config
from claimkeep.harvesters.atomic import (
    AtomicFactHarvester,
    extract_triple,
    factual_parts,
    is_factual,
    split_sentences,
)


class SelectionTest(unittest.TestCase):
    def test_keeps_first_person_statements(self):
        for sentence in (
            "I bought a Fitbit Inspire HR on February 15th.",
            "My daughter started third grade this year.",
            "I have been tracking my blood pressure with an Omron monitor.",
        ):
            self.assertTrue(is_factual(sentence), sentence)

    def test_drops_assistant_advice(self):
        """The register that flooded the first run: instructions, not facts."""
        for sentence in (
            "Aim for a 30-minute brisk walk, 3-4 times a week.",
            "Hold for 5-10 breaths on each side.",
            "You can take the stairs instead of the elevator.",
            "There are many destinations that would be perfect for a romantic getaway.",
            "I'm happy to help you with workout recommendations.",
            "Now, let's get moving!",
            "**Stair Climbing**: Find a staircase at your local gym.",
            "Radiation sources: photons, electrons, protons, and heavy ions",
        ):
            self.assertFalse(is_factual(sentence), sentence)

    def test_drops_questions_and_hypotheticals(self):
        for sentence in (
            "What kind of workout would you recommend?",
            "If I had more time I would run every morning.",
            "Maybe I will start yoga at some point.",
        ):
            self.assertFalse(is_factual(sentence), sentence)

    def test_impersonal_sentence_needs_something_concrete(self):
        self.assertFalse(is_factual("The weather has been quite pleasant lately."))
        self.assertTrue(is_factual("The Boston Marathon takes place in April."))


class QuestionCarryingAFactTest(unittest.TestCase):
    """Most of the remaining LongMemEval recall loss was this one shape."""

    def test_fact_survives_the_question_it_was_asked_with(self):
        parts = factual_parts(
            "I'm visiting my sister Emily in Denver soon, and I was wondering "
            "if you knew any kid-friendly attractions there?"
        )
        self.assertTrue(parts)
        self.assertIn("Emily", parts[0])
        self.assertNotIn("attractions", " ".join(parts))

    def test_a_pure_question_still_yields_nothing(self):
        self.assertEqual(factual_parts("What kind of workout would you recommend?"), [])
        self.assertEqual(factual_parts("Can you recommend a show to watch tonight?"), [])

    def test_a_plain_statement_is_unchanged(self):
        self.assertEqual(
            factual_parts("I bought a Fitbit on February 15th."),
            ["I bought a Fitbit on February 15th."],
        )


class TripleTest(unittest.TestCase):
    def test_splits_at_the_finite_verb(self):
        subject, predicate, obj = extract_triple("My car is a Subaru Outback")
        self.assertEqual(subject, "My car")
        self.assertIn("is", predicate)
        self.assertIn("Subaru", obj)

    def test_absorbs_the_auxiliary_chain(self):
        subject, predicate, _ = extract_triple("I have been working at Centene since March")
        self.assertEqual(subject, "I")
        self.assertEqual(predicate.split()[0], "have")
        self.assertIn("working", predicate)

    def test_third_person_s_of_a_known_verb_is_finite(self):
        """`plays` must count as a verb without letting `photons` count as one."""
        triple = extract_triple("My daughter plays piano every Tuesday")
        self.assertIsNotNone(triple)
        self.assertEqual(triple[0], "My daughter")
        self.assertEqual(triple[1], "plays")
        self.assertFalse(is_factual("Radiation sources: photons, electrons, protons"))

    def test_imperative_has_no_subject_and_is_rejected(self):
        self.assertIsNone(extract_triple("Take the stairs instead of the elevator"))


class TopicTest(unittest.TestCase):
    def test_same_subject_and_verb_share_a_topic_across_tenses(self):
        """`worked` and `works` must land on one topic or supersession cannot chain."""
        harvester = AtomicFactHarvester()
        config = default_config()
        first = harvester.harvest(["I worked at Centene as a data engineer."], config)
        second = harvester.harvest(["I work at a startup now, since June."], config)
        self.assertEqual(first[0].topic, second[0].topic)

    def test_non_functional_relations_do_not_pretend_to_be_corrections(self):
        """Two interests are two facts. Collapsing them hid a quarter of the claims."""
        harvester = AtomicFactHarvester()
        config = default_config()
        first = harvester.harvest(["I am interested in the French Resistance."], config)
        second = harvester.harvest(["I am interested in astronomy."], config)
        self.assertNotEqual(first[0].topic, second[0].topic)

    def test_silent_e_is_restored_in_the_verb_root(self):
        """`moved` must stem to `move`, or the topic will not match its own infinitive."""
        harvester = AtomicFactHarvester()
        config = default_config()
        past = harvester.harvest(["I moved to Boston in 2019."], config)
        present = harvester.harvest(["I move to Austin next month."], config)
        self.assertEqual(past[0].topic, present[0].topic)

    def test_different_subjects_do_not_collide(self):
        harvester = AtomicFactHarvester()
        config = default_config()
        items = harvester.harvest(
            ["My dog is a spaniel. My car is a Subaru."], config
        )
        self.assertEqual(len({item.topic for item in items}), 2)


class ContextAnchorTest(unittest.TestCase):
    """44% of long assistant turns yielded nothing, and the questions whose
    answer lives in one were the worst-scoring category. One opening line per
    otherwise-empty long turn took that category from 0.821 to 0.929 R@10."""

    ADVICE = (
        "Yoga is an excellent way to start the day! Here are some poses that can "
        "help you sleep better. Try Child's Pose to calm your mind. Hold for 5-10 "
        "breaths on each side. Avoid vigorous practices close to bedtime, and end "
        "your practice with a relaxing Savasana to quiet your mind and body before "
        "you go to sleep for the night."
    )

    def test_a_long_turn_with_no_assertion_keeps_one_topical_line(self):
        items = AtomicFactHarvester().harvest([self.ADVICE], default_config())
        self.assertEqual(len(items), 1)
        self.assertIn("Yoga", items[0].text)
        self.assertTrue(items[0].topic.startswith("context|"))

    def test_a_short_turn_with_no_assertion_keeps_nothing(self):
        items = AtomicFactHarvester().harvest(["Try the stairs instead."], default_config())
        self.assertEqual(items, [])


class HarvestTest(unittest.TestCase):
    def test_returns_claims_and_dedupes_repeats(self):
        harvester = AtomicFactHarvester()
        config = default_config()
        items = harvester.harvest(
            [
                "I adopted a rescue dog last month.",
                "I adopted a rescue dog last month.",
            ],
            config,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_harvester, "atomic")
        self.assertIsNone(items[0].confidence)

    def test_sentence_splitting_survives_abbreviations(self):
        parts = split_sentences("I saw Dr. Patel on March 3rd. He renewed my prescription.")
        self.assertEqual(len(parts), 2)
        self.assertIn("Dr. Patel", parts[0])


if __name__ == "__main__":
    unittest.main()
