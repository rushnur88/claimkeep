"""A swallowed failure must still be visible on stderr.

The hooks exit 0 by design so compaction is never blocked. Every failure path
used to return silently as well, which made a broken install look exactly like a
working one with nothing to report — the same "a zero you cannot distinguish
from never happened" that `stats` refuses to produce. These tests fail against
that version.
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(payload, extra_env=None):
    env = dict(os.environ, PYTHONPATH=ROOT)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, "-m", "claimkeep", "precompact"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    return proc


class TestFailuresAreReported(unittest.TestCase):
    def test_unreadable_stdin_is_reported(self):
        proc = run("this is not json")
        self.assertEqual(proc.returncode, 0, "must stay fail-open")
        self.assertIn("claimkeep:", proc.stderr)

    def test_missing_transcript_is_reported(self):
        proc = run('{"transcript_path": "/nonexistent/transcript.jsonl"}')
        self.assertEqual(proc.returncode, 0, "must stay fail-open")
        self.assertIn("claimkeep:", proc.stderr)
        self.assertIn("no brief was written", proc.stderr)

    def test_the_reason_is_named(self):
        """A warning that does not say what broke is barely better than silence."""
        proc = run('{"transcript_path": "/nonexistent/transcript.jsonl"}')
        self.assertIn("FileNotFoundError", proc.stderr)


class TestQuietWhenNothingIsWrong(unittest.TestCase):
    def test_empty_stdin_is_not_an_error(self):
        """Claude Code can invoke the hook with no payload; that is not a fault."""
        proc = run("")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")

    def test_successful_run_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = os.path.join(tmp, "t.jsonl")
            with open(transcript, "w", encoding="utf-8") as handle:
                handle.write('{"text": "The retry ceiling is 4 [C:90%]"}\n')
            proc = run(
                '{"transcript_path": "%s", "session_id": "quiet"}' % transcript,
                {"CLAIMKEEP_BRIEF_DIR": os.path.join(tmp, "briefs")},
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr.strip(), "")
            self.assertTrue(
                proc.stdout.strip(), "a successful run prints the brief path"
            )


class TestPartiallyBrokenTranscript(unittest.TestCase):
    def test_all_rows_unparsable_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = os.path.join(tmp, "junk.jsonl")
            with open(transcript, "w", encoding="utf-8") as handle:
                handle.write("not json\nalso not json\n")
            proc = run(
                '{"transcript_path": "%s"}' % transcript,
                {"CLAIMKEEP_BRIEF_DIR": os.path.join(tmp, "briefs")},
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("no usable rows", proc.stderr)

    def test_a_few_bad_rows_do_not_spam_one_line_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = os.path.join(tmp, "mixed.jsonl")
            with open(transcript, "w", encoding="utf-8") as handle:
                handle.write('{"text": "The retry ceiling is 4 [C:90%]"}\n')
                for _ in range(5):
                    handle.write("junk\n")
            proc = run(
                '{"transcript_path": "%s"}' % transcript,
                {"CLAIMKEEP_BRIEF_DIR": os.path.join(tmp, "briefs")},
            )
            warnings = [
                ln for ln in proc.stderr.splitlines() if ln.startswith("claimkeep:")
            ]
            self.assertEqual(len(warnings), 1, "one summary line, not one per row")
            self.assertIn("skipped 5 of 6", warnings[0])


if __name__ == "__main__":
    unittest.main()
