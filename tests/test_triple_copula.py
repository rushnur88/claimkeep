"""A noun that looks like a verb must not decide where the subject ends.

`extract_triple` splits at the first token that looks verbal. Two ways that
misfires, both common in engineering prose:

  "The pinned version is 1.2.3"  -> nothing parsed at all. "pinned" opens the
  noun phrase, the parser reads a sentence-initial verb as an imperative, and
  gives up. The statement gets no topic, so supersession cannot touch it.

  "The retry ceiling is 5"       -> ("retry", "ceiling is", "5"). "ceiling" ends
  in -ing, so it is taken for the verb and half the subject lands in the
  predicate.

The fix is to look for the copula first: when a sentence contains "is", "are",
"has" and so on, that is the verb, and everything before it is the subject —
whatever those words look like on their own.
"""

import unittest

from claimkeep.harvesters.atomic import _topic, extract_triple


class TestCopulaWins(unittest.TestCase):
    def test_participle_in_the_subject_parses(self):
        triple = extract_triple("The pinned version is 1.2.3")
        self.assertIsNotNone(triple, "sentence still unparsed")
        subject, predicate, obj = triple
        self.assertIn("version", subject)
        self.assertIn("is", predicate)
        self.assertIn("1", obj)

    def test_ing_noun_stays_in_the_subject(self):
        subject, predicate, obj = extract_triple("The retry ceiling is 5")
        self.assertIn("ceiling", subject)
        self.assertNotIn("ceiling", predicate)
        self.assertEqual(obj, "5")

    def test_such_a_sentence_supersedes_its_own_restatement(self):
        # The point of parsing it at all.
        first = extract_triple("The pinned version is 1.2.3")
        second = extract_triple("The pinned version is 1.3.0")
        self.assertEqual(_topic(*first), _topic(*second))

    def test_descriptions_with_a_participle_subject_also_parse(self):
        triple = extract_triple("The pinned version is stable")
        self.assertIsNotNone(triple)
        self.assertIn("version", triple[0])

    def test_a_real_imperative_is_still_rejected(self):
        # "Run the migration before deploying" is an instruction, not a claim.
        self.assertIsNone(extract_triple("Run the migration before deploying"))

    def test_ordinary_verbs_are_unaffected(self):
        subject, predicate, obj = extract_triple("We pinned the version to 1.2.3")
        self.assertEqual(subject.casefold(), "we")
        self.assertIn("pin", predicate)

    def test_auxiliary_chain_still_absorbed(self):
        subject, predicate, _obj = extract_triple(
            "The worker has been running since noon"
        )
        self.assertIn("worker", subject)
        self.assertIn("has", predicate)


if __name__ == "__main__":
    unittest.main()
