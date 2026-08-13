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


if __name__ == "__main__":
    unittest.main()
