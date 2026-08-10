"""Tests for the shipped marker instruction and the durable lesson store."""

import json
import os
import tempfile
import unittest

from claimkeep.brief import Brief, Claim
from claimkeep.config import default_config
from claimkeep.harvesters.lessons import LessonHarvester
from claimkeep.lessons import Lesson, LessonStore
from claimkeep.prompt import marker_instruction
from claimkeep.rehydrate import postcompact_payload


class MarkerInstructionTest(unittest.TestCase):
    def test_instruction_matches_the_harvested_marker_shape(self):
        """The shipped convention must be the one the harvester can read.

        Shipping an instruction whose example the plugin cannot parse would be
        worse than shipping none: it looks installed and harvests nothing.
        """
        import re

        text = marker_instruction()
        pattern = re.compile(default_config().calibration_marker_regex)
        self.assertTrue(pattern.search("Deployed to prod [C:82%, basis: checked the dashboard]"))
        self.assertIn("[C:", text)
        self.assertIn("basis", text)

    def test_session_start_ships_the_instruction_and_postcompact_does_not(self):
        brief = Brief(claims=[], supplement=[])
        start = postcompact_payload(brief, "SessionStart")["hookSpecificOutput"]["additionalContext"]
        later = postcompact_payload(brief, "PostCompact")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Confidence markers", start)
        self.assertNotIn("Confidence markers", later)


class LessonHarvestTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        self.harvester = LessonHarvester()

    def test_labelled_lesson_is_harvested(self):
        found = self.harvester.harvest(
            ["LESSON: check the token owner before pushing, not after the failure"], self.config
        )
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].topic.startswith("lesson:"))
        self.assertIn("check the token owner", found[0].text)

    def test_timestamped_label_is_harvested(self):
        """`LESSON [stamp] (local): body` must not be missed.

        Measured on a real transcript: agents that stamp their lessons put the
        stamp between the label and the colon, and the first recogniser skipped
        every one of them.
        """
        found = self.harvester.harvest(
            ["ARIA-LESSON [2026-08-10T14:22:40Z] (2026-08-10 10:22 EDT): "
             "verify the token owner before attempting a push"],
            self.config,
        )
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].text.startswith("verify the token owner"))

    def test_gate_boilerplate_is_not_a_lesson(self):
        """A prompt that merely names a lesson rule is not itself a lesson.

        A real transcript held 253 lines mentioning the word; none was a lesson.
        A recogniser that swallowed them would fill the store with prompt text.
        """
        noise = [
            "- Add to BEHAVIORAL GATES: 'AUTO-LESSON-AFTER-TASK GATE - record a lesson after every task'",
            "done 4, failed 0, lessons 4x",
        ]
        self.assertEqual(self.harvester.harvest(noise, self.config), [])

    def test_outcome_plus_rule_is_harvested_without_a_label(self):
        found = self.harvester.harvest(
            ["The push failed on permissions, so next time verify the account before attempting it"],
            self.config,
        )
        self.assertEqual(len(found), 1)

    def test_ordinary_prose_is_not_a_lesson(self):
        noise = [
            "I ran the tests and they passed.",
            "The file lives at /tmp/output.json and is 4 KB.",
            "So I opened the dashboard.",
        ]
        self.assertEqual(self.harvester.harvest(noise, self.config), [])

    def test_lessons_do_not_supersede_each_other(self):
        """Two lessons are two lessons — neither replaces the other."""
        found = self.harvester.harvest(
            [
                "LESSON: always verify the account before a push attempt",
                "LESSON: squash checkpoint commits before publishing a branch",
            ],
            self.config,
        )
        brief = Brief(claims=found)
        self.assertEqual(len(brief.active_claims), 2)

    def test_disabled_by_config(self):
        config = default_config()
        config.lessons_enabled = False
        self.assertEqual(self.harvester.harvest(["LESSON: this should not be picked up at all"], config), [])


class LessonStoreTest(unittest.TestCase):
    def test_append_dedupes_and_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lessons.jsonl")
            first = LessonStore(path)
            written = first.append([Lesson(text="verify the account before pushing")])
            self.assertEqual(len(written), 1)
            again = first.append([Lesson(text="verify the account before pushing")])
            self.assertEqual(again, [], "the same lesson must not be stored twice")

            reopened = LessonStore(path)
            self.assertEqual(len(reopened.load()), 1)

    def test_recent_is_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LessonStore(os.path.join(tmp, "lessons.jsonl"))
            store.append([Lesson(text="older lesson about tokens and pushes")])
            store.append([Lesson(text="newer lesson about squashing commits")])
            recent = store.recent(2)
            self.assertIn("newer", recent[0].text)

    def test_one_corrupt_line_does_not_lose_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lessons.jsonl")
            store = LessonStore(path)
            store.append([Lesson(text="a real lesson that must survive corruption")])
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("{not json at all\n")
            self.assertEqual(len(store.load()), 1)

    def test_lessons_survive_into_a_later_brief(self):
        """The whole point: a rule learned earlier is present in a later brief."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lessons.jsonl")
            os.environ["CLAIMKEEP_LESSONS_PATH"] = path
            try:
                from claimkeep.cli import _carry_lessons

                config = default_config()
                config.lessons_in_brief = 5
                LessonStore(path).append([Lesson(text="a rule learned in an earlier session")])
                carried = _carry_lessons([], config, "2026-08-10T00:00:00Z", {"session": "s2"})
                self.assertTrue(any("earlier session" in claim.text for claim in carried))
            finally:
                os.environ.pop("CLAIMKEEP_LESSONS_PATH", None)


if __name__ == "__main__":
    unittest.main()
