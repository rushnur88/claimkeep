"""Redaction rules, with the prefixed-variable regression pinned down.

The rule used to start with `\\b(password|token|...)`. Underscore is a word
character, so there is no boundary before PASSWORD inside DB_PASSWORD, and every
prefixed name — the way secrets are actually written in an env file — slipped
through untouched. These tests fail against that version.
"""

import unittest

from claimkeep.redact import redact


class TestPrefixedSecrets(unittest.TestCase):
    """A secret must be masked whatever prefix its variable name carries."""

    PREFIXED = [
        "DB_PASSWORD=hunter2SuperSecret",
        "GITHUB_TOKEN=abc123def456",
        "OPENAI_API_KEY=abc123def456",
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENG",
        "ARIA_PROXY_TOKEN=abc123def456",
        "TOKEN_FOR_CI=abc123def456",
        "my.service.token = abc123def456",
    ]

    def test_prefixed_names_are_redacted(self):
        for line in self.PREFIXED:
            with self.subTest(line=line):
                self.assertIn("[REDACTED:secret]", redact(line))

    def test_secret_value_never_survives(self):
        for line in self.PREFIXED:
            with self.subTest(line=line):
                value = (
                    line.split("=", 1)[1].strip()
                    if "=" in line
                    else line.split(":", 1)[1].strip()
                )
                self.assertNotIn(value, redact(line))

    def test_variable_name_is_preserved(self):
        """Masking the value must not eat the name — the brief loses its meaning."""
        self.assertEqual(
            redact("OPENAI_API_KEY=abc123def456"), "OPENAI_API_KEY=[REDACTED:secret]"
        )
        self.assertEqual(
            redact("DB_PASSWORD=hunter2SuperSecret"), "DB_PASSWORD=[REDACTED:secret]"
        )

    def test_bare_names_still_work(self):
        for line in (
            "password=hunter2SuperSecret",
            "token=abc123def456",
            "api_key: abc123def456",
        ):
            with self.subTest(line=line):
                self.assertIn("[REDACTED:secret]", redact(line))


class TestNoFalsePositives(unittest.TestCase):
    """Ordinary prose that merely mentions a secret word must pass through."""

    def test_prose_is_untouched(self):
        for line in (
            "the token path is wrong",
            "password rotation is due",
            "/etc/aria/proxy.env",
            "Ship Friday [C:80%]",
            "port=8769",
        ):
            with self.subTest(line=line):
                self.assertEqual(redact(line), line)


class TestSecretWordThenBlob(unittest.TestCase):
    """A secret named in prose, with no "=" to anchor on.

    An AWS secret access key carries no recognisable prefix, so the word in front
    of it is the only signal available. The length floor is what keeps ordinary
    prose out of the rule.
    """

    def test_blob_after_secret_word_is_masked(self):
        line = "AWS creds and secret wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        out = redact(line)
        self.assertIn("[REDACTED:secret]", out)
        self.assertNotIn("wJalrXUtnFEMI", out)

    def test_short_words_after_secret_word_are_left_alone(self):
        for line in (
            "the secret sauce is simplicity",
            "secret handshake",
            "the token path is wrong",
        ):
            with self.subTest(line=line):
                self.assertEqual(redact(line), line)

    def test_a_path_is_not_a_secret(self):
        line = "rotate the key stored at /etc/aria/secrets.env"
        self.assertEqual(redact(line), line)


class TestKnownShapes(unittest.TestCase):
    """The shape-based rules the README lists by name."""

    CASES = [
        ("sk-proj-FAKE1234567890abcdefFAKE1234567890", "[REDACTED:api-key]"),
        ("ghp_FAKEtoken1234567890abcdefghijklmnop", "[REDACTED:github-token]"),
        ("AKIAIOSFODNN7EXAMPLE", "[REDACTED:aws-key]"),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
            "[REDACTED:jwt]",
        ),
        ("admin@patechlabs.com", "[REDACTED:email]"),
    ]

    def test_each_shape_is_masked(self):
        for raw, marker in self.CASES:
            with self.subTest(raw=raw[:20]):
                self.assertIn(marker, redact("value " + raw + " end"))

    def test_private_key_block(self):
        block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
        self.assertIn("[REDACTED:private-key]", redact(block))
        self.assertNotIn("MIIEow", redact(block))

    def test_empty_input(self):
        self.assertEqual(redact(""), "")


if __name__ == "__main__":
    unittest.main()
