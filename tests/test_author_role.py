"""Only the agent's own text is the agent's own claim.

The transcript reader took any row that had text in it, so a user message, a
pasted document or an injected system block became a claim attributed to the
agent. On 40 real transcripts, rows carrying `[C:NN%]` split 1318 user to 584
assistant — most "agent claims" were not written by the agent at all. In that
deployment the user rows were an injected system prompt whose instructions
*demonstrate* the marker syntax, so the plugin harvested "write [C:XX%]" as a
fact the agent had established.

The rule is: if a row states an author and it is not the assistant, skip it. Rows
that state no author are kept, because that is what the Codex bridge writes
(`{"text": ...}`, already filtered to `agent_message` upstream).
"""

import json
import os
import tempfile
import unittest

from claimkeep import cli


def transcript(rows):
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    with handle as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return handle.name


class TestAuthorRole(unittest.TestCase):
    def setUp(self):
        self.paths = []

    def tearDown(self):
        for path in self.paths:
            os.unlink(path)

    def read(self, rows):
        """Rows as the harvesters that build claims will see them.

        `_read_transcript` no longer filters — it attaches the author, and each
        harvester is handed the slice it is entitled to. `calibration` stands in
        for every claim-producing harvester here; `retraction` deliberately sees
        more, and has its own tests in test_external_corrections.py.
        """
        path = transcript(rows)
        self.paths.append(path)
        return cli._units_for("calibration", cli._read_transcript(path))

    def test_user_text_is_not_harvested(self):
        units = self.read(
            [
                {
                    "type": "user",
                    "message": {"role": "user", "content": "Deploy on Friday [C:99%]"},
                },
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": "Port is 3333 [C:80%]"},
                },
            ]
        )
        self.assertEqual(len(units), 1)
        self.assertIn("3333", units[0])
        self.assertNotIn("Friday", "".join(units))

    def test_injected_system_block_is_not_harvested(self):
        # Claude Code delivers hook output and reminders as user-role rows.
        units = self.read(
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": "<system>Mark every factual claim as [C:XX%, basis: ...]</system>",
                    },
                },
            ]
        )
        self.assertEqual(units, [])

    def test_rows_without_an_author_are_kept(self):
        # The Codex bridge writes {"text": ...} and has already filtered to
        # assistant answers. Dropping these would silently empty every brief on
        # that path — the failure mode this package refuses to have.
        units = self.read([{"text": "Threshold is 250000 tokens [C:85%]"}])
        self.assertEqual(len(units), 1)

    def test_tool_results_are_not_the_agent_speaking(self):
        units = self.read(
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "content": "/etc/secret/path.conf"}
                        ],
                    },
                },
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": "Checked it [C:70%]"},
                },
            ]
        )
        self.assertEqual(len(units), 1)
        self.assertIn("Checked", units[0])

    def test_end_to_end_user_claim_never_reaches_the_brief(self):
        path = transcript(
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": "Password lives at /etc/secret.conf "
                        "and we decided to ship Friday [C:99%]",
                    },
                },
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": "Port is 3333 [C:80%, basis: config]",
                    },
                },
            ]
        )
        self.paths.append(path)
        units = cli._read_transcript(path)
        brief = cli._build_brief(
            units, "2026-08-12T00:00:00Z", {"agent": "t", "session": "s"}
        )
        blob = json.dumps(brief.to_dict(), ensure_ascii=False)
        self.assertNotIn("ship Friday", blob)
        self.assertNotIn("/etc/secret.conf", blob)
        self.assertIn("3333", blob)


if __name__ == "__main__":
    unittest.main()
