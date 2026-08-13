#!/usr/bin/env python3
"""Unit + end-to-end tests for the codex<->ClaimKeep bridge.

Pure-adapter tests need nothing installed. The end-to-end tests drive the PUBLISHED
`claimkeep` package: they locate the sibling checkout and expose it via CLAIMKEEP_HOME so
the `-m claimkeep` subprocess resolves without a pip install.

Run:  python3 -m unittest test_codex_adapter -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# Point the harvest/render subprocesses at the sibling claimkeep checkout.
# The package sits two levels up when this lives in integrations/codex/, and one
# level up when the bridge is copied next to a checkout. Try both, then the env,
# so the end-to-end test runs instead of silently skipping.
_CANDIDATES = [
    os.path.abspath(os.path.join(_HERE, "..", "..")),
    os.path.abspath(os.path.join(_HERE, "..", "claimkeep")),
    os.environ.get("CLAIMKEEP_HOME", ""),
]
_CLAIMKEEP_HOME = next(
    (c for c in _CANDIDATES if c and os.path.isdir(os.path.join(c, "claimkeep"))),
    "",
)
if os.path.isdir(_CLAIMKEEP_HOME):
    os.environ["CLAIMKEEP_HOME"] = _CLAIMKEEP_HOME

import codex_claimkeep_adapter as adapter  # noqa: E402
import codex_claimkeep_read as reader  # noqa: E402
import codex_claimkeep_write as writer  # noqa: E402

# Verified Codex CLI 0.145.0 event stream (2026-07-22). The agent_message carries a
# calibration marker and a path so we can prove the harvesters fire downstream.
VERIFIED_LINES = [
    '{"type":"thread.started","thread_id":"th_abc123"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"type":"reasoning","text":"internal thinking, must be dropped"}}',
    '{"type":"item.completed","item":{"type":"agent_message",'
    '"text":"Store briefs under /opt/aria-video/.env area. Ship it [C:80%]"}}',
    '{"type":"turn.completed","usage":{"input_tokens":123,"cached_input_tokens":10,"output_tokens":42}}',
]
AGENT_ANSWER = "Store briefs under /opt/aria-video/.env area. Ship it [C:80%]"


class AdapterTests(unittest.TestCase):
    def test_agent_message_only(self):
        events = list(adapter.iter_events(VERIFIED_LINES))
        msgs = list(adapter.iter_agent_messages(events))
        self.assertEqual(msgs, [AGENT_ANSWER])  # reasoning item dropped

    def test_parse_run_shape(self):
        res = adapter.parse_run(VERIFIED_LINES)
        self.assertEqual(res["units"], [{"role": "assistant", "text": AGENT_ANSWER}])
        self.assertEqual(res["thread_id"], "th_abc123")
        self.assertEqual(res["usage"].get("input_tokens"), 123)
        self.assertEqual(res["events"], 5)

    def test_last_usage_takes_latest_turn(self):
        lines = VERIFIED_LINES + [
            '{"type":"turn.completed","usage":{"input_tokens":999,"output_tokens":1}}'
        ]
        self.assertEqual(
            adapter.last_usage(adapter.iter_events(lines))["input_tokens"], 999
        )

    def test_bad_lines_skipped(self):
        lines = ["not json", "", "{}", VERIFIED_LINES[3]]
        self.assertEqual(len(adapter.parse_run(lines)["units"]), 1)

    def test_content_list_fallback(self):
        line = (
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"content":[{"text":"a"},{"text":"b"}]}}'
        )
        self.assertEqual(
            list(adapter.iter_agent_messages(adapter.iter_events([line]))), ["a\nb"]
        )


class WriteAppendTests(unittest.TestCase):
    def test_append_below_threshold_no_harvest(self):
        with tempfile.TemporaryDirectory() as d:
            tpath = os.path.join(d, "transcript.jsonl")
            info = writer.on_run_complete(
                "\n".join(VERIFIED_LINES),
                transcript_path=tpath,
                brief_dir=os.path.join(d, "briefs"),
                threshold=10**9,
            )
            self.assertEqual(info["units_appended"], 1)
            self.assertFalse(info["crossed_threshold"])
            self.assertFalse(info["harvested"])
            with open(tpath, encoding="utf-8") as fh:
                rows = [json.loads(x) for x in fh if x.strip()]
            self.assertEqual(rows, [{"role": "assistant", "text": AGENT_ANSWER}])


@unittest.skipUnless(os.path.isdir(_CLAIMKEEP_HOME), "claimkeep checkout not found")
class EndToEndHarvestTests(unittest.TestCase):
    def test_threshold_harvest_and_render(self):
        with tempfile.TemporaryDirectory() as d:
            tpath = os.path.join(d, "transcript.jsonl")
            bdir = os.path.join(d, "briefs")

            info = writer.on_run_complete(
                "\n".join(VERIFIED_LINES),
                transcript_path=tpath,
                brief_dir=bdir,
                threshold=100,  # 123 >= 100 -> harvest
            )
            self.assertTrue(info["crossed_threshold"])
            self.assertTrue(
                info["harvested"], msg=f"harvest failed: {info.get('harvest_error')}"
            )
            self.assertTrue(info["brief_path"] and os.path.exists(info["brief_path"]))
            # transcript rotated away after harvest
            self.assertTrue(
                info["archived_transcript"]
                and os.path.exists(info["archived_transcript"])
            )
            self.assertFalse(os.path.exists(tpath))

            with open(info["brief_path"], encoding="utf-8") as fh:
                brief = json.load(fh)
            # calibration harvester turned [C:80%] into a 0.80 claim
            confidences = [c.get("confidence") for c in brief.get("claims", [])]
            self.assertIn(0.8, confidences)
            # regex_floor harvester captured the path
            paths = [
                s["text"]
                for s in brief.get("supplement", [])
                if s.get("kind") == "path"
            ]
            self.assertTrue(
                any("/opt/aria-video/.env" in p for p in paths), msg=f"paths={paths}"
            )

            # READ side: render the HEAD brief and inject into AGENTS.md idempotently
            md = reader.head_brief_markdown(bdir)
            self.assertIn("ClaimKeep Brief", md)
            agents = os.path.join(d, "AGENTS.md")
            with open(agents, "w", encoding="utf-8") as fh:
                fh.write("# Codex agent\n\nExisting instructions.\n")
            reader.update_agents_md(agents, md)
            reader.update_agents_md(agents, md)  # second call must not duplicate
            with open(agents, encoding="utf-8") as fh:
                body = fh.read()
            self.assertEqual(body.count(reader.BEGIN), 1)
            self.assertEqual(body.count(reader.END), 1)
            self.assertIn("Existing instructions.", body)  # untouched
            self.assertIn("ClaimKeep Brief", body)


class TestStdoutBlobAccepted(unittest.TestCase):
    """`on_run_complete` takes the whole stdout blob, so `parse_run` must too.

    It used to take only a sequence of lines. Handed the blob, it iterated
    characters, parsed none of them, and returned units=0, thread_id=None,
    usage={} — no exception, no warning, just a run that looked like it had
    nothing in it. Caught against a live 0.147.0 stream.
    """

    STREAM = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "t-1"}),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "agent_message",
                        "text": "The dashboard port is 3333.",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 26264, "output_tokens": 12},
                }
            ),
        ]
    )

    def test_blob_and_lines_agree(self):
        from_blob = adapter.parse_run(self.STREAM)
        from_lines = adapter.parse_run(self.STREAM.splitlines())
        self.assertEqual(from_blob, from_lines)

    def test_blob_is_actually_parsed(self):
        run = adapter.parse_run(self.STREAM)
        self.assertEqual(len(run["units"]), 1)
        self.assertEqual(run["thread_id"], "t-1")
        self.assertEqual(run["usage"]["input_tokens"], 26264)
        self.assertIn("3333", run["units"][0]["text"])


if __name__ == "__main__":
    unittest.main()


class TestHarvestSuccessIsVerified(unittest.TestCase):
    """A harvest counts as done only if a readable brief is on disk.

    `claimkeep precompact` is fail-open by design — a memory layer must never
    block compaction, so it exits 0 even when it wrote nothing and says so on
    stderr. The bridge read that exit code as success, reported a `brief_path`
    for a file that did not exist, and then rotated the live transcript away
    because it believed the contents were safely harvested. That is not a
    misleading status line; that is losing the memory it exists to keep.
    """

    STREAM = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "Port is 3333 [C:90%]"},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 999_999}}),
        ]
    )

    def test_missing_transcript_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as d:
            res = writer._harvest(
                os.path.join(d, "absent.jsonl"), os.path.join(d, "briefs")
            )
            self.assertFalse(res["ok"])
            self.assertTrue(res.get("stderr"), "the reason must not be swallowed")

    def test_no_brief_path_is_reported_when_no_brief_exists(self):
        with tempfile.TemporaryDirectory() as d:
            res = writer._harvest(
                os.path.join(d, "absent.jsonl"), os.path.join(d, "briefs")
            )
            # No path at all, rather than a path to a file that was never written.
            self.assertIsNone(res["brief_path"])

    def test_transcript_is_not_rotated_when_the_harvest_produced_nothing(self):
        # The transcript is the only copy of what has not been harvested yet.
        with tempfile.TemporaryDirectory() as d:
            transcript = os.path.join(d, "live.jsonl")
            with open(transcript, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"text": "Port is 3333 [C:90%]"}) + "\n")
            original = open(transcript, encoding="utf-8").read()

            def failed_harvest(_transcript, _brief_dir):
                return {
                    "ok": False,
                    "brief_path": None,
                    "returncode": 0,
                    "stderr": "precompact failed; no brief was written",
                }

            real = writer._harvest
            writer._harvest = failed_harvest
            try:
                info = writer.on_run_complete(
                    self.STREAM,
                    transcript_path=transcript,
                    brief_dir=os.path.join(d, "briefs"),
                )
            finally:
                writer._harvest = real
            self.assertFalse(info["harvested"])
            self.assertIsNone(info["archived_transcript"])
            self.assertTrue(
                os.path.exists(transcript), "live transcript was rotated away"
            )
            self.assertIn("3333", open(transcript, encoding="utf-8").read())
            self.assertTrue(info["harvest_error"])

    def test_unparsable_stdout_is_reported_not_silently_empty(self):
        # Non-empty stdout that yields no events is a broken pipe or a changed
        # schema, not a quiet turn.
        with tempfile.TemporaryDirectory() as d:
            info = writer.on_run_complete(
                "not json at all\nstill not json\n",
                transcript_path=os.path.join(d, "t.jsonl"),
                brief_dir=os.path.join(d, "briefs"),
            )
            self.assertEqual(info["units_appended"], 0)
            self.assertTrue(info.get("parse_error"), "silent zero on unparsable stdout")


class TestUnitsStateTheirAuthor(unittest.TestCase):
    """The bridge knows these are assistant answers, so it should say so.

    ClaimKeep treats a row with no stated author as the agent's, which is what
    kept this path working when author filtering arrived. Relying on that
    default is still a bet on someone else's fallback: the adapter has already
    filtered to `agent_message`, so it can state the role outright.
    """

    def test_units_carry_the_assistant_role(self):
        units = adapter.parse_run(VERIFIED_LINES)["units"]
        self.assertEqual([u.get("role") for u in units], ["assistant"])
        self.assertEqual(units[0]["text"], AGENT_ANSWER)


class TestManagedBlockIsNotInjectable(unittest.TestCase):
    """Brief content must never be able to close the block it lives in.

    The writer split on the first END, so a brief whose text happened to contain
    the marker ended the block early: the rest of the old block survived, the
    next update appended another, and the file grew a marker each time. On the
    production AGENTS.md that had reached one BEGIN and three ENDs — one of them
    inside a claim that quoted the marker while describing this very defect, so
    the plugin was corrupting the file with a sentence about the corruption. A
    reader taking the first END then loads a truncated, stale brief.
    """

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_a_marker_in_the_brief_does_not_leak_into_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            agents = os.path.join(d, "AGENTS.md")
            with open(agents, "w", encoding="utf-8") as fh:
                fh.write("# Project\n")
            reader.update_agents_md(agents, "## brief\nquoting " + reader.END + " here\n")
            body = self.read(agents)
            self.assertEqual(body.count(reader.BEGIN), 1)
            self.assertEqual(body.count(reader.END), 1)

    def test_repeated_updates_keep_exactly_one_pair(self):
        with tempfile.TemporaryDirectory() as d:
            agents = os.path.join(d, "AGENTS.md")
            with open(agents, "w", encoding="utf-8") as fh:
                fh.write("# Project\n\nExisting instructions.\n")
            for i in range(4):
                reader.update_agents_md(agents, "## brief %d\nmentions %s\n" % (i, reader.END))
            body = self.read(agents)
            self.assertEqual(body.count(reader.BEGIN), 1)
            self.assertEqual(body.count(reader.END), 1)
            self.assertIn("Existing instructions.", body)
            self.assertIn("brief 3", body)
            self.assertNotIn("brief 2", body)

    def test_an_already_corrupted_file_is_repaired(self):
        # The production file is in this state; the next write has to fix it
        # rather than add to it.
        with tempfile.TemporaryDirectory() as d:
            agents = os.path.join(d, "AGENTS.md")
            with open(agents, "w", encoding="utf-8") as fh:
                fh.write("# Project\n\n%s\nold brief %s\nleftover\n%s\n\nTail instructions.\n"
                         % (reader.BEGIN, reader.END, reader.END))
            reader.update_agents_md(agents, "## fresh brief\n")
            body = self.read(agents)
            self.assertEqual(body.count(reader.BEGIN), 1)
            self.assertEqual(body.count(reader.END), 1)
            self.assertIn("fresh brief", body)
            self.assertNotIn("old brief", body)
            self.assertNotIn("leftover", body)
            self.assertIn("Tail instructions.", body)


class TestTranscriptIsPrivate(unittest.TestCase):
    """The rolling transcript is the same session text as the briefs."""

    STREAM = "\n".join([
        json.dumps({"type": "item.completed",
                    "item": {"type": "agent_message", "text": "Port is 3333 [C:90%]"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5}}),
    ])

    def test_new_transcript_and_directory_are_owner_only(self):
        import stat as _stat
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "codex", "transcript.jsonl")
            writer.on_run_complete(self.STREAM, transcript_path=path,
                                   brief_dir=os.path.join(d, "briefs"), threshold=10**9)
            self.assertEqual(_stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(_stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)

    def test_a_transcript_from_an_older_release_is_tightened(self):
        import stat as _stat
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "transcript.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"role": "assistant", "text": "old turn"}) + "\n")
            os.chmod(path, 0o644)
            writer.on_run_complete(self.STREAM, transcript_path=path,
                                   brief_dir=os.path.join(d, "briefs"), threshold=10**9)
            self.assertEqual(_stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(len(fh.read().strip().split("\n")), 2)


class TestAgentsWriteIsAtomic(unittest.TestCase):
    """AGENTS.md is the agent's own instructions; a half-write truncates them.

    The managed block was written with a plain truncating open, the same shape
    the package fixed for briefs. An interrupted write leaves the file short —
    and unlike a brief, this file also holds instructions ClaimKeep did not put
    there.
    """

    def test_a_failed_write_leaves_the_original_intact(self):
        with tempfile.TemporaryDirectory() as d:
            agents = os.path.join(d, "AGENTS.md")
            original = "# Project\n\nExisting instructions.\n"
            with open(agents, "w", encoding="utf-8") as fh:
                fh.write(original)

            def boom(_src, _dst):
                raise RuntimeError("disk went away")

            real = reader.os.replace
            reader.os.replace = boom
            try:
                with self.assertRaises(RuntimeError):
                    reader.update_agents_md(agents, "## brief\n")
            finally:
                reader.os.replace = real
            with open(agents, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), original)
            self.assertEqual(os.listdir(d), ["AGENTS.md"])

    def test_a_normal_write_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            agents = os.path.join(d, "AGENTS.md")
            with open(agents, "w", encoding="utf-8") as fh:
                fh.write("# Project\n")
            reader.update_agents_md(agents, "## brief\n")
            with open(agents, encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("brief", body)
            self.assertIn("# Project", body)
