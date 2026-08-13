"""Briefs are memory: private by default, and never half-written.

A brief is a verbatim slice of a session. Redaction removes the shapes it knows,
which is defence in depth, not a guarantee — so the file itself must not be
world-readable. Under the usual umask of 022 these landed as 0755 directories
and 0644 files, readable by every account on the machine.

The brief is also written in place with a plain `open(..., "w")`. A crash or a
full disk between truncate and write leaves a truncated file where the previous
brief used to be, and the next SessionStart reads that. Write to a temporary
file beside it, fsync, then rename: the reader sees either the old brief or the
new one.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest


def mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def write_transcript(directory):
    path = os.path.join(directory, "t.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": "Port is 3333 [C:90%, basis: config]",
                    },
                }
            )
            + "\n"
        )
    return path


def run_precompact(transcript, brief_dir, extra_env=None):
    env = dict(os.environ, CLAIMKEEP_BRIEF_DIR=brief_dir)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, "-m", "claimkeep", "precompact"],
        input=json.dumps({"transcript_path": transcript, "session_id": "s"}),
        text=True,
        capture_output=True,
        env=env,
    )
    return proc


class TestStoragePrivacy(unittest.TestCase):
    def test_brief_directory_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            brief_dir = os.path.join(d, "briefs")
            run_precompact(write_transcript(d), brief_dir)
            self.assertEqual(mode_of(brief_dir), 0o700)

    def test_brief_file_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            brief_dir = os.path.join(d, "briefs")
            run_precompact(write_transcript(d), brief_dir)
            briefs = [os.path.join(brief_dir, f) for f in os.listdir(brief_dir)]
            self.assertTrue(briefs, "no brief written")
            for path in briefs:
                self.assertEqual(mode_of(path), 0o600, path)

    def test_lessons_store_is_private(self):
        from claimkeep.lessons import Lesson, LessonStore

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "lessons.jsonl")
            store = LessonStore(path)
            store.append([Lesson(text="the retry ceiling is 5")])
            self.assertEqual(mode_of(path), 0o600)
            self.assertEqual(mode_of(os.path.dirname(path)), 0o700)

    def test_probe_log_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "probe", "probe.jsonl")
            run_precompact(
                write_transcript(d),
                os.path.join(d, "briefs"),
                {"CLAIMKEEP_PROBE_LOG": log},
            )
            self.assertTrue(os.path.exists(log), "probe log not written")
            self.assertEqual(mode_of(log), 0o600)
            self.assertEqual(mode_of(os.path.dirname(log)), 0o700)

    def test_brief_write_leaves_no_temp_files_behind(self):
        with tempfile.TemporaryDirectory() as d:
            brief_dir = os.path.join(d, "briefs")
            run_precompact(write_transcript(d), brief_dir)
            leftovers = [f for f in os.listdir(brief_dir) if not f.endswith(".json")]
            self.assertEqual(leftovers, [])

    def test_a_failed_write_does_not_destroy_the_previous_brief(self):
        from claimkeep import storage

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "brief.json")
            storage.write_private(path, '{"schema_version": 1}')

            def boom(_src, _dst):
                raise RuntimeError("disk went away")

            real_replace = storage.os.replace
            storage.os.replace = boom
            try:
                with self.assertRaises(RuntimeError):
                    storage.write_private(path, '{"schema_version": 999}')
            finally:
                storage.os.replace = real_replace
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["schema_version"], 1)
            self.assertEqual(os.listdir(d), ["brief.json"])


if __name__ == "__main__":
    unittest.main()


class TestExistingFilesAreHardened(unittest.TestCase):
    """Tightening permissions for new files leaves the archive wide open.

    The store is append-only and long-lived: on the deployment that prompted
    this, 270 of 272 briefs stayed 0644 after the fix, because only the two
    written afterwards went through the new path. The old ones hold the same
    kind of session text as the new ones.

    So the store is hardened, not just the write: every brief already there is
    brought to 0600 as well. Only files that are too permissive are touched, and
    a file owned by someone else is skipped rather than failing the harvest.
    """

    def test_pre_existing_briefs_are_tightened(self):
        from claimkeep import storage

        with tempfile.TemporaryDirectory() as d:
            legacy = os.path.join(d, "20260101T000000Z-old.json")
            with open(legacy, "w", encoding="utf-8") as fh:
                fh.write('{"schema_version": 1, "claims": [], "supplement": []}')
            os.chmod(legacy, 0o644)
            storage.harden_existing(d)
            self.assertEqual(mode_of(legacy), 0o600)
            self.assertEqual(mode_of(d), 0o700)

    def test_hardening_does_not_touch_content(self):
        from claimkeep import storage

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "brief.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"schema_version": 1}')
            os.chmod(path, 0o644)
            storage.harden_existing(d)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["schema_version"], 1)

    def test_a_harvest_hardens_the_store_it_writes_into(self):
        with tempfile.TemporaryDirectory() as d:
            brief_dir = os.path.join(d, "briefs")
            os.makedirs(brief_dir)
            legacy = os.path.join(brief_dir, "20260101T000000Z-old.json")
            with open(legacy, "w", encoding="utf-8") as fh:
                fh.write('{"schema_version": 1, "claims": [], "supplement": []}')
            os.chmod(legacy, 0o644)
            run_precompact(write_transcript(d), brief_dir)
            self.assertEqual(mode_of(legacy), 0o600)

    def test_missing_directory_is_not_an_error(self):
        from claimkeep import storage

        storage.harden_existing(os.path.join(tempfile.mkdtemp(), "absent"))


class TestAppendTightensExistingFiles(unittest.TestCase):
    """An append-only store predates every fix applied to it.

    `append_private` set 0600 only when it created the file, so a lesson store
    written by an earlier release kept its mode for good — on the deployment,
    `lessons.jsonl` was still 0664 while every brief beside it had been closed.
    The file is the same kind of memory either way.
    """

    def test_an_existing_loose_file_is_tightened_on_append(self):
        from claimkeep import storage

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "lessons.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"id": "1"}\n')
            os.chmod(path, 0o664)
            storage.append_private(path, '{"id": "2"}\n')
            self.assertEqual(mode_of(path), 0o600)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(len(fh.read().strip().split("\n")), 2)

    def test_the_parent_directory_is_tightened_too(self):
        from claimkeep import storage

        with tempfile.TemporaryDirectory() as d:
            store = os.path.join(d, "store")
            os.makedirs(store)
            os.chmod(store, 0o775)
            storage.append_private(os.path.join(store, "lessons.jsonl"), "{}\n")
            self.assertEqual(mode_of(store), 0o700)

    def test_harden_existing_covers_any_pattern(self):
        # Rotated transcripts are not *.json, and were left behind by a sweep
        # that only looked at briefs.
        from claimkeep import storage

        with tempfile.TemporaryDirectory() as d:
            archive = os.path.join(d, "transcript.jsonl.20260813T000000Z.harvested")
            with open(archive, "w", encoding="utf-8") as fh:
                fh.write("{}\n")
            os.chmod(archive, 0o644)
            storage.harden_existing(d)
            self.assertEqual(mode_of(archive), 0o600)
