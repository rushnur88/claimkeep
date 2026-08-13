"""A value that changed must not stay current in two places at once.

Two defects, one symptom. `BRIEF_SCHEMA.md` calls supersession-by-topic the
mechanism that keeps a corrected fact from being restated, and it was failing on
exactly the case it exists for.

**The topic key carried the value.** "the dashboard port is 3333" and "the
dashboard port is 4444" hashed to `dashboard port|be|3333` and
`dashboard port|be|4444`, so the two readings were different subjects and
neither superseded the other. Including the object head is right for
descriptions — "my dog is friendly" and "my dog is brown" are both true — and
wrong for measurements, where a subject has one value at a time.

**Supersession stopped at the file boundary.** Each brief resolved its own
claims and knew nothing of the ones before it, so a value corrected in a later
session left the earlier reading live in the corpus, and recall offered both
with no sign which one still held.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from claimkeep import cli
from claimkeep.harvesters.atomic import _topic, extract_triple


def topic_of(sentence):
    triple = extract_triple(sentence)
    assert triple, "no triple extracted from %r" % sentence
    return _topic(*triple)


class TestTopicKeyForMeasurements(unittest.TestCase):
    def test_a_changed_number_keeps_the_topic(self):
        self.assertEqual(
            topic_of("The dashboard port is 3333"),
            topic_of("The dashboard port is 4444"),
        )

    def test_a_changed_hash_keeps_the_topic(self):
        self.assertEqual(
            topic_of("The commit is a1b2c3d4e5f"),
            topic_of("The commit is 9f8e7d6c5b4"),
        )

    def test_a_changed_path_keeps_the_topic(self):
        self.assertEqual(
            topic_of("The config lives at /etc/aria/a.conf"),
            topic_of("The config lives at /etc/aria/b.conf"),
        )

    def test_descriptions_still_get_their_own_topics(self):
        # The reason the object head is in the key at all: these do not correct
        # each other and must not supersede each other.
        self.assertNotEqual(topic_of("My dog is friendly"), topic_of("My dog is brown"))


class TestSupersessionWithinOneBrief(unittest.TestCase):
    def test_the_older_reading_is_marked(self):
        units = [
            ("assistant", "The dashboard port is 3333 [C:90%, basis: config]"),
            ("assistant", "The dashboard port is 4444 [C:95%, basis: rechecked]"),
        ]
        brief = cli._build_brief(
            units, "2026-08-13T00:00:00Z", {"agent": "t", "session": "s"}
        ).to_dict()
        stale = [c for c in brief["claims"] if "3333" in c["text"]]
        current = [c for c in brief["claims"] if "4444" in c["text"]]
        self.assertTrue(stale and current)
        self.assertTrue(all(c["superseded_by"] for c in stale))
        self.assertTrue(all(c["superseded_by"] is None for c in current))


class TestSupersessionAcrossBriefs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.briefs = os.path.join(self.dir, "briefs")
        self.env = dict(
            os.environ,
            CLAIMKEEP_BRIEF_DIR=self.briefs,
            CLAIMKEEP_LESSONS_PATH=os.path.join(self.dir, "lessons.jsonl"),
        )

    def session(self, text, name):
        path = os.path.join(self.dir, name + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": text},
                    }
                )
                + "\n"
            )
        subprocess.run(
            [sys.executable, "-m", "claimkeep", "precompact"],
            input=json.dumps({"transcript_path": path, "session_id": name}),
            text=True,
            capture_output=True,
            env=self.env,
            check=True,
        )

    def corpus(self):
        from claimkeep.config import default_config
        from claimkeep.retrieve import load_corpus

        old = os.environ.get("CLAIMKEEP_BRIEF_DIR")
        os.environ["CLAIMKEEP_BRIEF_DIR"] = self.briefs
        try:
            return load_corpus(default_config())
        finally:
            if old is None:
                del os.environ["CLAIMKEEP_BRIEF_DIR"]
            else:
                os.environ["CLAIMKEEP_BRIEF_DIR"] = old

    def two_sessions(self):
        self.session("The dashboard port is 3333 [C:90%, basis: config]", "s1")
        time.sleep(1.1)  # brief filenames are second-resolution
        self.session("The dashboard port is 4444 [C:95%, basis: rechecked]", "s2")

    def test_the_earlier_brief_is_marked_superseded_in_the_corpus(self):
        self.two_sessions()
        docs = {d.text: d for d in self.corpus() if d.kind == "claim"}
        stale = [d for t, d in docs.items() if "3333" in t]
        current = [d for t, d in docs.items() if "4444" in t]
        self.assertTrue(stale and current)
        self.assertTrue(all(d.superseded for d in stale), "stale reading still live")
        self.assertTrue(all(not d.superseded for d in current))

    def test_recall_puts_the_current_value_first(self):
        from claimkeep.config import default_config
        from claimkeep.retrieve import recall

        self.two_sessions()
        old = os.environ.get("CLAIMKEEP_BRIEF_DIR")
        os.environ["CLAIMKEEP_BRIEF_DIR"] = self.briefs
        try:
            rows = [
                r
                for r in recall("dashboard port", default_config(), limit=5)
                if r["doc"].kind == "claim"
            ]
        finally:
            if old is None:
                del os.environ["CLAIMKEEP_BRIEF_DIR"]
            else:
                os.environ["CLAIMKEEP_BRIEF_DIR"] = old
        self.assertTrue(rows)
        self.assertIn("4444", rows[0]["doc"].text)

    def test_unrelated_facts_across_briefs_stay_live(self):
        self.session("The dashboard port is 3333 [C:90%, basis: config]", "s1")
        time.sleep(1.1)
        self.session("The retry ceiling is 5 [C:70%, basis: memory]", "s2")
        docs = [d for d in self.corpus() if d.kind == "claim"]
        self.assertTrue(docs)
        self.assertFalse(
            any(d.superseded for d in docs),
            "unrelated facts marked as corrections of each other",
        )



class TestOnlyPreciseTopicsSettleAcrossBriefs(unittest.TestCase):
    """Phrasing-based topics must not resolve claims against each other.

    The fallback topic is the sentence's first six words. Inside one brief that
    is fine — the claims come from one session. Across a corpus it groups by how
    a sentence opens, not by what it is about. Measured on 271 production
    briefs, settling every topic marked 18.4% of claims superseded against 1.0%
    before, and the additions were unrelated statements that happened to start
    alike. Limiting it to the parsed `subject|predicate` key brought that to
    1.1%: the corrections it was built for, and nothing else.
    """

    def test_the_atomic_key_settles(self):
        from claimkeep.retrieve import _settles_across_briefs

        self.assertTrue(_settles_across_briefs("dashboard port|be"))

    def test_a_phrasing_slug_does_not(self):
        from claimkeep.retrieve import _settles_across_briefs

        self.assertFalse(_settles_across_briefs("проверяю-живой-статус-задачи"))
        self.assertFalse(_settles_across_briefs(".-."))
        self.assertFalse(_settles_across_briefs(""))

if __name__ == "__main__":
    unittest.main()
