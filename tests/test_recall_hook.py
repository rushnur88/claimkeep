"""Older sessions are searchable, but nothing was searching them.

`recall` indexes every brief and lesson the plugin ever wrote — on one
deployment, 4,165 documents — and it was reachable only by typing
`claimkeep recall` by hand. The agent, which is who needs it, never called it.
Meanwhile the automatic path (SessionStart / PostCompact) injects exactly one
brief: the newest. Anything established two sessions ago was on disk and out of
reach.

This hook closes that: on each user turn, search the corpus for what was just
asked and add the few best matches. The design is deliberately timid, because a
memory layer that interrupts every message with three guesses is worse than one
that stays quiet:

  * a score floor, since a greeting matches something in a large corpus;
  * a hard cap of a few items and a small character budget;
  * superseded claims never surface — the corpus keeps history, but a live turn
    should not be answered with a value that was corrected;
  * fail-open and switchable off, like every other hook here.

The floor cannot separate the two cases perfectly. Measured on a production
corpus, real questions scored 13.7 to 30.1 and small talk 0 to 16.2 — they
overlap. That is why the cap matters more than the floor: when a marginal query
does slip through, it costs three lines.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest


def write_brief(brief_dir, name, claims):
    os.makedirs(brief_dir, exist_ok=True)
    payload = {
        "schema_version": 1,
        "created_utc": "2026-08-13T00:00:00Z",
        "source": {"agent": "test", "session": name},
        "claims": claims,
        "supplement": [],
    }
    path = os.path.join(brief_dir, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


def claim(text, cid, topic="t", superseded=None):
    return {
        "id": cid,
        "text": text,
        "confidence": 0.9,
        "topic": topic,
        "source_harvester": "calibration",
        "ts": None,
        "source_span": text,
        "superseded_by": superseded,
        "supersedes": None,
    }


def run_hook(brief_dir, prompt, extra_env=None):
    env = dict(os.environ, CLAIMKEEP_BRIEF_DIR=brief_dir)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, "-m", "claimkeep", "recall-hook"],
        input=json.dumps({"prompt": prompt, "session_id": "s"}),
        text=True,
        capture_output=True,
        env=env,
    )
    return proc


def context_of(proc):
    if not proc.stdout.strip():
        return ""
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


class TestRecallHook(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.briefs = os.path.join(self.dir, "briefs")
        # Distinct topics on purpose: same-topic claims supersede each other,
        # and the hook deliberately never surfaces a superseded claim.
        write_brief(
            self.briefs,
            "old",
            [
                claim(
                    "The dashboard port is 3333 and the tunnel forwards it",
                    "a1",
                    "port",
                ),
                claim("The retry ceiling for the watcher is 5 attempts", "a2", "retry"),
                claim(
                    "Supabase service key rotates every ninety days", "a3", "supabase"
                ),
            ],
        )

    def test_a_relevant_question_gets_context(self):
        ctx = context_of(run_hook(self.briefs, "what is the dashboard port"))
        self.assertIn("3333", ctx)

    def test_small_talk_gets_nothing(self):
        for prompt in ("hi", "ok", "thanks"):
            self.assertEqual(context_of(run_hook(self.briefs, prompt)), "", prompt)

    def test_the_block_says_where_it_came_from(self):
        ctx = context_of(run_hook(self.briefs, "what is the dashboard port"))
        self.assertIn("ClaimKeep", ctx)
        self.assertIn("earlier session", ctx.lower())

    def test_output_is_capped(self):
        ctx = context_of(
            run_hook(
                self.briefs,
                "dashboard port retry ceiling supabase key",
                {"CLAIMKEEP_RECALL_BUDGET": "200"},
            )
        )
        self.assertLessEqual(len(ctx), 400)

    def test_superseded_claims_do_not_surface(self):
        # A value that was corrected must not answer a live turn. Uses its own
        # vocabulary so nothing in setUp can satisfy the query instead.
        write_brief(
            self.briefs,
            "newer",
            [
                claim("The webhook endpoint moved to 8888", "b1", "webhook"),
                claim(
                    "The webhook endpoint is 7777", "b2", "webhook-old", superseded="b1"
                ),
            ],
        )
        ctx = context_of(run_hook(self.briefs, "which webhook endpoint do we use"))
        self.assertIn("8888", ctx)
        self.assertNotIn("7777", ctx)

    def test_the_hook_can_be_switched_off(self):
        proc = run_hook(
            self.briefs, "what is the dashboard port", {"CLAIMKEEP_RECALL_HOOK": "0"}
        )
        self.assertEqual(context_of(proc), "")
        self.assertEqual(proc.returncode, 0)

    def test_a_missing_brief_dir_is_not_an_error(self):
        proc = run_hook(os.path.join(self.dir, "absent"), "what is the dashboard port")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(context_of(proc), "")

    def test_broken_stdin_exits_clean(self):
        env = dict(os.environ, CLAIMKEEP_BRIEF_DIR=self.briefs)
        proc = subprocess.run(
            [sys.executable, "-m", "claimkeep", "recall-hook"],
            input="not json at all",
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0)

    def test_an_empty_prompt_is_not_a_search(self):
        self.assertEqual(context_of(run_hook(self.briefs, "")), "")


class TestRecalledLinesCarryProvenance(unittest.TestCase):
    """A recalled line needs its date more than a brief line does.

    The brief states its recording time once in a header, and everything under
    it shares that time. Recall has no such header: it reaches across every
    stored brief, so a claim from six weeks ago and one from this morning arrive
    side by side, looking identical. Without a date the older one reads as
    current — which is the exact failure this marking exists to prevent.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.briefs = os.path.join(self.dir, "briefs")
        write_brief(
            self.briefs,
            "old",
            [
                claim(
                    "The dashboard port is 3333 and the tunnel forwards it",
                    "a1",
                    "port",
                ),
                claim("We picked sqlite for the watcher write pattern", "a2", "sqlite"),
            ],
        )

    def line_for(self, prompt):
        ctx = context_of(run_hook(self.briefs, prompt))
        lines = [l for l in ctx.splitlines() if l.startswith("- ")]
        self.assertTrue(lines, "recall returned nothing for %r" % prompt)
        return lines[0]

    def test_a_recalled_line_says_when_it_was_recorded(self):
        self.assertIn("2026-08-13", self.line_for("what is the dashboard port"))

    def test_a_live_state_claim_is_marked_in_recall_too(self):
        self.assertIn("VERIFY CURRENT", self.line_for("what is the dashboard port"))

    def test_a_settled_decision_is_not_marked(self):
        line = self.line_for("why did we pick sqlite for the watcher")
        self.assertIn("2026-08-13", line)
        self.assertNotIn("VERIFY CURRENT", line)


if __name__ == "__main__":
    unittest.main()
