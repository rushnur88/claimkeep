"""One unreadable brief must not cost the session its memory.

`postcompact` loaded the newest brief and, if that file was truncated or
half-written, the hook caught the error, exited 0 and injected nothing at all —
every earlier brief sitting right there, readable. The corpus loader has always
skipped an unreadable brief and carried on; the re-injection path had not.

Nothing is deleted or repaired here. The bad file stays where it is, the reason
goes to stderr, and the newest brief that can actually be read is used instead.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest


class TestCorruptBriefFallback(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.briefs = os.path.join(self.dir, "briefs")
        os.makedirs(self.briefs)
        self.env = dict(os.environ, CLAIMKEEP_BRIEF_DIR=self.briefs)

    def write_good_brief(self, session):
        path = os.path.join(self.dir, session + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                "content": "The dashboard port is 3333 [C:90%, basis: config]"}}) + "\n")
        subprocess.run([sys.executable, "-m", "claimkeep", "precompact"],
                       input=json.dumps({"transcript_path": path, "session_id": session}),
                       text=True, capture_output=True, env=self.env, check=True)

    def corrupt_newest(self, name="20990101T000000Z-broken.json"):
        path = os.path.join(self.briefs, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"schema_version": 1, "claims": [ truncated')
        return path

    def postcompact(self):
        return subprocess.run([sys.executable, "-m", "claimkeep", "postcompact"],
                              input="{}", text=True, capture_output=True,
                              env=dict(self.env, CLAUDE_HOOK_EVENT_NAME="SessionStart"))

    def context(self, proc):
        if not proc.stdout.strip():
            return ""
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_falls_back_to_the_last_readable_brief(self):
        self.write_good_brief("good")
        time.sleep(1.1)
        self.corrupt_newest()
        proc = self.postcompact()
        self.assertIn("3333", self.context(proc), "memory lost to one bad file")

    def test_the_reason_is_reported(self):
        self.write_good_brief("good")
        time.sleep(1.1)
        self.corrupt_newest()
        self.assertIn("broken", self.postcompact().stderr)

    def test_the_bad_file_is_left_alone(self):
        self.write_good_brief("good")
        time.sleep(1.1)
        path = self.corrupt_newest()
        self.postcompact()
        self.assertTrue(os.path.exists(path))

    def test_all_briefs_unreadable_still_exits_cleanly(self):
        self.corrupt_newest("20990101T000001Z-a.json")
        self.corrupt_newest("20990101T000002Z-b.json")
        proc = self.postcompact()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.context(proc), "")

    def test_a_readable_newest_brief_is_still_preferred(self):
        self.write_good_brief("older")
        time.sleep(1.1)
        self.write_good_brief("newer")
        proc = self.postcompact()
        self.assertIn("3333", self.context(proc))


if __name__ == "__main__":
    unittest.main()
