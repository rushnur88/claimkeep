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
        self.assertEqual(res["units"], [{"text": AGENT_ANSWER}])
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
            self.assertEqual(rows, [{"text": AGENT_ANSWER}])


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
