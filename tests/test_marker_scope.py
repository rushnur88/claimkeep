"""One marker, one claim — and nothing else riding along.

The harvester used to run `search` for the first marker and `sub` to strip them
all, so an entire message became a single claim carrying the first marker's
confidence. Measured on 40 real transcripts, 45% of marked assistant messages
carry two or more markers, so this was not an edge case: it was almost half the
input. Worse than the averaging, unmarked text inside the same message — asides,
open questions, an explicit "this is not a fact" — inherited that confidence.
"""

import unittest

from claimkeep.config import default_config
from claimkeep.harvesters import get_harvester


def harvest(*units):
    return get_harvester("calibration")().harvest(list(units), default_config())


class TestMarkerScope(unittest.TestCase):
    def test_each_marker_becomes_its_own_claim(self):
        claims = harvest(
            "Dashboard port is 3333 [C:90%, basis: read the config].\n"
            "The retry ceiling is 5 [C:70%, basis: memory]."
        )
        self.assertEqual(len(claims), 2)
        self.assertEqual([c.confidence for c in claims], [0.9, 0.7])
        self.assertIn("3333", claims[0].text)
        self.assertNotIn("retry ceiling", claims[0].text)
        self.assertIn("retry ceiling", claims[1].text)

    def test_unmarked_text_is_not_claimed(self):
        # The tail carries no marker. Storing it as a claim — at the confidence
        # of a different sentence — is the failure this package exists to avoid.
        claims = harvest(
            "Port is 3333 [C:90%, basis: config].\n"
            "I also speculated a bit here and this is explicitly not a fact."
        )
        self.assertEqual(len(claims), 1)
        self.assertNotIn("speculated", claims[0].text)

    def test_two_markers_on_one_line(self):
        # Real transcripts put two marked statements in one paragraph, separated
        # by a comma rather than a newline.
        claims = harvest(
            "Lesson saved as observation #63550 [C:97%, basis: tool confirmed id], "
            "and the relay delivered the final line [C:95%, basis: relay ok]."
        )
        self.assertEqual(len(claims), 2)
        self.assertEqual([c.confidence for c in claims], [0.97, 0.95])
        self.assertIn("63550", claims[0].text)
        self.assertIn("relay", claims[1].text)

    def test_marker_leading_the_statement(self):
        # "[C:80%] the thing" is rarer than "the thing [C:80%]" but must not
        # silently vanish.
        claims = harvest("[C:80%, basis: docs] The bridge threshold is 250000 tokens.")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].confidence, 0.8)
        self.assertIn("250000", claims[0].text)

    def test_distinct_topics_so_supersession_does_not_collide(self):
        # One claim per message produced a topic slug fused from two subjects,
        # which made unrelated facts look like restatements of each other.
        claims = harvest(
            "Dashboard port is 3333 [C:90%, basis: config].\n"
            "The retry ceiling is 5 [C:70%, basis: memory]."
        )
        self.assertNotEqual(claims[0].topic, claims[1].topic)

    def test_marker_text_never_survives_into_the_claim(self):
        for claim in harvest("Port is 3333 [C:90%, basis: config]. Host is x [C:60%]."):
            self.assertNotIn("[C:", claim.text)

    def test_source_span_still_points_at_the_whole_unit(self):
        # The span is provenance: it must remain the message as written, so a
        # reader can see the claim in context.
        unit = "Port is 3333 [C:90%, basis: config].\nRetry ceiling is 5 [C:70%]."
        for claim in harvest(unit):
            self.assertEqual(claim.source_span, unit)



class TestSentenceBoundary(unittest.TestCase):
    """A marker annotates its sentence, not everything sharing the line.

    Scoping to the last line fixed the multi-marker case and left this one: an
    unmarked sentence sitting in front of a marked one on the same line still
    inherited the confidence. "This is explicitly unmarked. Port is 3333 [C:90%]"
    was stored whole, at 90%.
    """

    def test_preceding_sentence_on_the_same_line_is_dropped(self):
        claims = harvest("This is explicitly unmarked. Port is 3333 [C:90%]")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].confidence, 0.9)
        self.assertIn("3333", claims[0].text)
        self.assertNotIn("explicitly unmarked", claims[0].text)

    def test_leading_marker_takes_only_its_own_sentence(self):
        claims = harvest("[C:80%, basis: docs] Port is 3333. An unrelated remark follows.")
        self.assertEqual(len(claims), 1)
        self.assertIn("3333", claims[0].text)
        self.assertNotIn("unrelated remark", claims[0].text)

    def test_two_marked_sentences_on_one_line_stay_separate(self):
        claims = harvest("Port is 3333 [C:90%]. The retry ceiling is 5 [C:70%].")
        self.assertEqual(len(claims), 2)
        self.assertEqual([c.confidence for c in claims], [0.9, 0.7])
        self.assertNotIn("retry", claims[0].text)
        self.assertNotIn("3333", claims[1].text)

    def test_question_and_exclamation_also_end_a_sentence(self):
        claims = harvest("Did that work? The port is 3333 [C:90%]")
        self.assertNotIn("Did that work", claims[0].text)

    def test_a_decimal_point_does_not_end_a_sentence(self):
        # "1.2.3" must not be read as three sentences.
        claims = harvest("We shipped version 1.2.3 to production [C:85%]")
        self.assertIn("1.2.3", claims[0].text)

    def test_multi_line_statement_keeps_its_own_line(self):
        claims = harvest("Checked three things:\n- the port is 3333 [C:90%]")
        self.assertIn("3333", claims[0].text)
        self.assertNotIn("Checked three things", claims[0].text)

if __name__ == "__main__":
    unittest.main()
