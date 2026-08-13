"""Two corrections about different things are two corrections.

Every external correction was filed under the single topic
`retraction:external`, and supersession treats one topic as one subject
restated over time. So the second correction in a session silently retired the
first: "the port is 4444, not 3333" went inactive because "the retry ceiling is
9, not 5" arrived after it. A correction is the highest-value line in a brief —
losing one to an unrelated correction is the same failure as never harvesting
it.
"""

import unittest

from claimkeep import cli


def brief_for(units):
    return cli._build_brief(
        units, "2026-08-13T00:00:00Z", {"agent": "t", "session": "s"}
    ).to_dict()


PORT = "Correction: the dashboard port is 4444, not 3333."
RETRY = "Correction: the retry ceiling is 9, not 5."


class TestIndependentCorrections(unittest.TestCase):
    def setUp(self):
        self.brief = brief_for(
            [
                ("assistant", "The dashboard port is 3333 [C:90%, basis: config]"),
                ("assistant", "The retry ceiling is 5 [C:70%, basis: memory]"),
                ("user", PORT),
                ("user", RETRY),
            ]
        )
        self.corrections = [
            c for c in self.brief["claims"] if c["source_harvester"] == "retraction"
        ]

    def test_both_corrections_are_kept(self):
        self.assertEqual(len(self.corrections), 2)

    def test_neither_correction_supersedes_the_other(self):
        for claim in self.corrections:
            self.assertIsNone(
                claim["superseded_by"], "a correction was retired by an unrelated one"
            )

    def test_corrections_do_not_share_a_topic(self):
        topics = {c["topic"] for c in self.corrections}
        self.assertEqual(len(topics), 2, "one topic means one subject restated")

    def test_each_correction_still_retires_its_own_claim(self):
        stale = [
            c
            for c in self.brief["claims"]
            if c["source_harvester"] != "retraction" and c["superseded_by"]
        ]
        texts = " ".join(c["text"] for c in stale)
        self.assertIn("3333", texts)
        self.assertIn("5", texts)


if __name__ == "__main__":
    unittest.main()
