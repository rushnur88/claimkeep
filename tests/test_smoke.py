import json
import subprocess
import sys
import unittest

from claimkeep.brief import Brief, Claim, Supplement, make_id
from claimkeep.config import default_config
from claimkeep.harvesters.calibration import CalibrationHarvester
from claimkeep.harvesters.regex_floor import RegexFloorHarvester
from claimkeep.rehydrate import postcompact_payload


class ClaimKeepSmokeTest(unittest.TestCase):
    def test_zero_markers_valid_brief_with_floor(self):
        transcript = ["Use /tmp/claimkeep.json not /tmp/other.json."]
        supplement = RegexFloorHarvester().harvest(transcript, default_config())
        brief = Brief(claims=[], supplement=supplement)
        self.assertEqual(brief.claims, [])
        self.assertGreater(len(brief.supplement), 0)

    def test_plain_sentence_has_no_floor_supplement(self):
        supplement = RegexFloorHarvester().harvest(["This is a plain sentence with nothing special."], default_config())
        self.assertEqual(supplement, [])

    def test_roundtrip_json(self):
        brief = Brief(
            claims=[Claim("Ship Friday", 0.8, "ship-friday", "calibration")],
            supplement=[Supplement("/tmp/ck.json", "path", "regex_floor")],
        )
        parsed = Brief.from_json(brief.to_json())
        self.assertEqual([c.to_dict() for c in brief.claims], [c.to_dict() for c in parsed.claims])
        self.assertEqual([s.to_dict() for s in brief.supplement], [s.to_dict() for s in parsed.supplement])

    def test_id_determinism_and_punctuation(self):
        a = make_id("regex_floor", "path", " /TMP/ClaimKeep.JSON  ")
        b = make_id("regex_floor", "path", "/tmp/claimkeep.json")
        c = make_id("regex_floor", "path", "/tmp/claimkeep-json")
        self.assertEqual(a, b)
        self.assertNotEqual(b, c)

    def test_calibration_marker(self):
        claims = CalibrationHarvester().harvest(["Ship Friday [C:80%]"], default_config())
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].confidence, 0.8)
        self.assertEqual(claims[0].text, "Ship Friday")

    def test_supersede_by_topic_keeps_last(self):
        first = Claim("Ship Friday", 0.8, "ship", "calibration")
        second = Claim("Ship Monday", 0.9, "ship", "calibration")
        brief = Brief(claims=[first, second], supplement=[])
        self.assertEqual(len(brief.claims), 1)
        self.assertEqual(brief.claims[0].text, "Ship Monday")

    def test_supersede_by_topic_respects_late_duplicate_id(self):
        first = Claim("Ship Friday", 0.8, "ship", "calibration")
        second = Claim("Ship Monday", 0.9, "ship", "calibration")
        brief = Brief(claims=[first, second, first], supplement=[])
        self.assertEqual(len(brief.claims), 1)
        self.assertEqual(brief.claims[0].text, "Ship Friday")

    def test_from_dict_requires_claims_and_supplement(self):
        with self.assertRaises(ValueError):
            Brief.from_dict({"schema_version": 1, "claims": []})
        with self.assertRaises(ValueError):
            Brief.from_dict({"schema_version": 1, "supplement": []})

    def test_postcompact_payload(self):
        payload = postcompact_payload(Brief(), "SessionStart")
        self.assertIn("hookSpecificOutput", payload)
        self.assertTrue(payload["hookSpecificOutput"]["additionalContext"])
        json.dumps(payload)

    def test_postcompact_missing_explicit_brief_is_nonblocking(self):
        result = subprocess.run(
            [sys.executable, "-m", "claimkeep", "postcompact", "--brief", "/nonexistent.json", "--event", "SessionStart"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(result.returncode, 0)


    def test_redaction_masks_secrets(self):
        from claimkeep.redact import redact

        self.assertIn("REDACTED", redact("openai key sk-abcdEFGH0123456789ijklmnop"))
        self.assertIn("REDACTED", redact("ghp_ABCDEFGHIJ0123456789ABCDEFGHIJ012345"))
        self.assertIn("REDACTED", redact("AKIAABCDEFGHIJKLMNOP"))
        self.assertNotIn("ABCDEFGHIJ123456", redact("token = ABCDEFGHIJ123456"))
        self.assertEqual(redact("a normal sentence with no secrets."), "a normal sentence with no secrets.")

    def test_redaction_in_build_brief(self):
        from claimkeep.cli import _build_brief

        brief = _build_brief(
            ["We decided to use the key sk-abcdEFGH0123456789ijklmnop now."],
            "2026-01-01T00:00:00Z",
            {"agent": "x", "session": "s"},
        )
        self.assertNotIn("sk-abcdEFGH0123456789ijklmnop", brief.to_json())


if __name__ == "__main__":
    unittest.main()
