"""The budget must bound what actually reaches the context window.

`apply_budget` counted `len(text) + 1` per item, but an item does not reach the
agent as bare text: it is rendered with a heading, its confidence, its topic and
markdown around it, and at SessionStart the marker instruction rides along too.
Measured on a real run, a brief reporting 2,870 used characters produced 7,799
characters of `additionalContext` — 2.7x what the accounting claimed.

A budget that is only advisory defeats the purpose. The brief exists to fit back
into the window compaction just cleared; overshooting it by a factor of three is
the failure it was introduced to prevent. So the cap is enforced against the
rendered payload, and items are dropped in the same deterministic priority order
until it fits.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from claimkeep.brief import Brief, Claim, Supplement
from claimkeep.rehydrate import postcompact_payload


def big_brief(n=200):
    claims = [
        Claim(
            text="Fact number %d: the service port is %d" % (i, 4000 + i),
            confidence=0.9,
            topic="port-%d" % i,
            source_harvester="calibration",
            source_span="Fact number %d [C:90%%]" % i,
        )
        for i in range(n)
    ]
    supplement = [
        Supplement(
            text="/etc/service/%d.conf" % i, kind="path", source_harvester="regex_floor"
        )
        for i in range(n)
    ]
    return Brief(
        created_utc="2026-08-13T00:00:00Z",
        source={"agent": "t", "session": "s"},
        claims=claims,
        supplement=supplement,
    )


def context_of(payload):
    return payload["hookSpecificOutput"]["additionalContext"]


class TestBudgetIsAHardCap(unittest.TestCase):
    def test_postcompact_context_respects_the_budget(self):
        from claimkeep.select import apply_budget

        budget = 2000
        trimmed = apply_budget(big_brief(), budget)
        context = context_of(postcompact_payload(trimmed, "PostCompact", budget))
        self.assertLessEqual(len(context), budget)

    def test_session_start_counts_the_marker_instruction_too(self):
        from claimkeep.select import apply_budget

        budget = 2000
        trimmed = apply_budget(big_brief(), budget)
        context = context_of(postcompact_payload(trimmed, "SessionStart", budget))
        self.assertLessEqual(len(context), budget)

    def test_trimming_is_deterministic(self):
        from claimkeep.select import apply_budget

        budget = 1500
        first = context_of(
            postcompact_payload(
                apply_budget(big_brief(), budget), "PostCompact", budget
            )
        )
        second = context_of(
            postcompact_payload(
                apply_budget(big_brief(), budget), "PostCompact", budget
            )
        )
        self.assertEqual(first, second)

    def test_a_tight_budget_still_returns_something_useful(self):
        from claimkeep.select import apply_budget

        budget = 1200
        context = context_of(
            postcompact_payload(
                apply_budget(big_brief(), budget), "PostCompact", budget
            )
        )
        self.assertTrue(context.strip(), "trimmed to nothing")
        self.assertIn("Fact number", context)

    def test_unbounded_budget_is_left_alone(self):
        brief = big_brief(5)
        bounded = context_of(postcompact_payload(brief, "PostCompact", 0))
        self.assertIn("Fact number 0", bounded)

    def test_end_to_end_hook_output_respects_the_configured_budget(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = os.path.join(d, "t.jsonl")
            with open(transcript, "w", encoding="utf-8") as fh:
                for i in range(300):
                    fh.write(
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "content": "Fact %d: port is %d [C:90%%, basis: checked]"
                                    % (i, 4000 + i),
                                },
                            }
                        )
                        + "\n"
                    )
            budget = 3000
            env = dict(
                os.environ,
                CLAIMKEEP_BRIEF_DIR=os.path.join(d, "briefs"),
                CLAIMKEEP_BUDGET_CHARS=str(budget),
            )
            subprocess.run(
                [sys.executable, "-m", "claimkeep", "precompact"],
                input=json.dumps({"transcript_path": transcript, "session_id": "s"}),
                text=True,
                capture_output=True,
                env=env,
                check=True,
            )
            out = subprocess.run(
                [sys.executable, "-m", "claimkeep", "postcompact"],
                input="{}",
                text=True,
                capture_output=True,
                env=dict(env, CLAUDE_HOOK_EVENT_NAME="SessionStart"),
                check=True,
            )
            context = context_of(json.loads(out.stdout))
            self.assertTrue(context.strip())
            self.assertLessEqual(len(context), budget)


if __name__ == "__main__":
    unittest.main()


class TestBudgetReportIsHonest(unittest.TestCase):
    """The budget report must describe the brief that exists, not a smaller one.

    `used_chars` summed item texts, so a brief occupying 7,917 characters once
    reported 2,925. Everything else in this package refuses to print a number it
    cannot stand behind; the budget report was printing one.
    """

    def test_report_states_the_rendered_size(self):
        from claimkeep.rehydrate import render
        from claimkeep.select import apply_budget

        trimmed = apply_budget(big_brief(40), 4000)
        reported = trimmed.source["budget"]["rendered_chars"]
        self.assertEqual(reported, len(render(trimmed)))

    def test_the_rendered_brief_fits_the_budget(self):
        from claimkeep.rehydrate import render
        from claimkeep.select import apply_budget

        budget = 3000
        trimmed = apply_budget(big_brief(200), budget)
        self.assertLessEqual(len(render(trimmed)), budget)
