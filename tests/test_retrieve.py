"""Tests for the read path."""

import os
import tempfile
import unittest

from claimkeep.brief import Brief, Claim, Supplement
from claimkeep.config import Config
from claimkeep.lessons import Lesson, LessonStore
from claimkeep.retrieve import Document, load_corpus, recall, score, tokenize


def _doc(text, kind="claim", ident=None, ts=None, superseded=False):
    return Document(text=text, kind=kind, id=ident or text[:16], ts=ts, superseded=superseded)


class ScoringTest(unittest.TestCase):
    def test_ranks_the_matching_document_first(self):
        docs = [
            _doc("the deploy pipeline runs on a schedule", ident="a"),
            _doc("token owner must be verified before a push", ident="b"),
            _doc("the cache is cleared nightly", ident="c"),
        ]
        top = score("push token", docs)[0]
        self.assertEqual(top["doc"].id, "b")

    def test_non_matching_documents_are_dropped_not_ranked_low(self):
        docs = [_doc("nothing relevant here at all", ident="a")]
        self.assertEqual(score("kubernetes", docs), [])

    def test_empty_query_or_corpus_is_empty(self):
        self.assertEqual(score("", [_doc("x")]), [])
        self.assertEqual(score("anything", []), [])

    def test_superseded_loses_to_the_claim_that_replaced_it(self):
        docs = [
            _doc("discover drives the traffic", ident="old", superseded=True),
            _doc("discover drives the traffic", ident="new"),
        ]
        ranked = score("discover traffic", docs)
        self.assertEqual(ranked[0]["doc"].id, "new")
        self.assertLess(ranked[1]["score"], ranked[0]["score"])

    def test_lesson_outranks_a_path_at_equal_lexical_match(self):
        docs = [
            _doc("verify the cache before measuring", kind="lesson", ident="l"),
            _doc("verify the cache before measuring", kind="path", ident="p"),
        ]
        ranked = score("verify cache", docs)
        self.assertEqual(ranked[0]["doc"].kind, "lesson")

    def test_newer_wins_when_everything_else_is_equal(self):
        docs = [
            _doc("identical text about tokens", ident="old", ts="2026-01-01T00:00:00Z"),
            _doc("identical text about tokens", ident="new", ts="2026-08-01T00:00:00Z"),
        ]
        self.assertEqual(score("tokens", docs)[0]["doc"].id, "new")

    def test_tokenizer_splits_paths_into_searchable_parts(self):
        self.assertIn("claimkeep", tokenize("/home/aria/claimkeep/select.py"))
        self.assertIn("select", tokenize("/home/aria/claimkeep/select.py"))


class CorpusTest(unittest.TestCase):
    def _config(self, tmp):
        config = Config()
        config.brief_dir = os.path.join(tmp, "briefs")
        config.lessons_path = os.path.join(tmp, "lessons.jsonl")
        os.makedirs(config.brief_dir, exist_ok=True)
        return config

    def _write_brief(self, config, name, brief):
        with open(os.path.join(config.expanded_brief_dir(), name), "w", encoding="utf-8") as handle:
            handle.write(brief.to_json())

    def test_corpus_spans_every_brief_not_only_the_newest(self):
        """The whole point of a read path: older sessions stay reachable."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            self._write_brief(config, "20260101-a.json", Brief(
                claims=[Claim("the vault broker denied the fatsecret key", None, "vault", "calibration")],
                created_utc="2026-01-01T00:00:00Z"))
            self._write_brief(config, "20260801-b.json", Brief(
                supplement=[Supplement("/home/aria/claimkeep/select.py", "path", "regex_floor")],
                created_utc="2026-08-01T00:00:00Z"))
            LessonStore(config.expanded_lessons_path()).append(
                [Lesson(text="squash checkpoint commits before publishing")])

            corpus = load_corpus(config)
            self.assertEqual(len(corpus), 3)
            self.assertEqual({doc.kind for doc in corpus}, {"claim", "path", "lesson"})

            hit = recall("vault broker", config)
            self.assertTrue(hit)
            self.assertIn("vault broker", hit[0]["doc"].text)

    def test_one_corrupt_brief_does_not_cost_the_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            self._write_brief(config, "good.json", Brief(
                claims=[Claim("a readable claim about tokens", None, "t", "calibration")]))
            with open(os.path.join(config.expanded_brief_dir(), "bad.json"), "w", encoding="utf-8") as h:
                h.write("{ not json")
            self.assertEqual(len(load_corpus(config)), 1)

    def test_budget_caps_the_result_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            self._write_brief(config, "a.json", Brief(claims=[
                Claim("token rotation policy number %d" % i, None, "topic-%d" % i, "calibration")
                for i in range(20)
            ]))
            rows = recall("token rotation", config, limit=20, budget_chars=100)
            used = sum(len(row["doc"].text) + 1 for row in rows)
            self.assertLessEqual(used, 100)
            self.assertTrue(rows)

    def test_missing_dirs_are_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config()
            config.brief_dir = os.path.join(tmp, "nope")
            config.lessons_path = os.path.join(tmp, "nope.jsonl")
            self.assertEqual(load_corpus(config), [])
            self.assertEqual(recall("anything", config), [])


if __name__ == "__main__":
    unittest.main()
