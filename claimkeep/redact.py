"""Best-effort secret / PII redaction, applied BEFORE text enters a brief.

ClaimKeep harvests an agent's own transcript, which can contain API keys,
tokens, or personal data. This pass masks well-known secret shapes before any
text is stored in a brief, so credentials never persist into memory or get
re-injected after compaction.

It is intentionally conservative — targeted patterns, not a guarantee. Treat it
as defense-in-depth, not a licence to paste secrets. Redaction is on by default
(`Config.redact = True`) and can be disabled per deployment via config.
"""

from __future__ import annotations

import re
from typing import List, Pattern, Tuple

# Each rule: (compiled pattern, replacement). Ordered most-specific first.
_RULES: List[Tuple[Pattern[str], str]] = [
    (
        re.compile(
            r"-----BEGIN[A-Z ]*PRIVATE KEY-----.*?-----END[A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED:private-key]",
    ),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"), "[REDACTED:api-key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED:github-token]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED:slack-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws-key]"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED:jwt]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer [REDACTED:token]"),
    # key = value / key: value, where the key name signals a secret.
    # The name may carry a prefix — DB_PASSWORD, OPENAI_API_KEY, AWS_SECRET_ACCESS_KEY —
    # which is how secrets are actually spelled in an env file. A leading \b alone does
    # not match those: "_" is a word character, so there is no boundary before PASSWORD
    # in DB_PASSWORD, and the rule silently skipped every prefixed name.
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_.\-]*"
            r"(?:api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key)"
            r"[A-Za-z0-9_.\-]*)(\s*[:=]\s*)\S{6,}"
        ),
        r"\1\2[REDACTED:secret]",
    ),
    # A high-entropy blob introduced by a secret word, with no "=" to anchor on:
    # "and secret wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY". An AWS secret access key
    # has no recognisable prefix, so the word in front of it is the only signal there
    # is. The 20-character floor keeps ordinary prose ("the secret sauce") out.
    #
    # The cue word has to exist in the language the session is written in. This rule
    # shipped English-only, so "секрет wJalr..." leaked in a Russian transcript while
    # the identical English sentence was masked — a redaction rule that depends on
    # the operator's language is not a redaction rule.
    (
        re.compile(
            r"(?i)\b(secret|token|password|passphrase|credential"
            r"|секрет|токен|пароль|ключ|креденшл)\w*\s+"
            r"([A-Za-z0-9+/_\-]{20,}={0,2})\b"
        ),
        r"\1 [REDACTED:secret]",
    ),
    # email (PII)
    (
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED:email]",
    ),
]


def redact(text: str) -> str:
    """Return ``text`` with well-known secret / PII shapes masked."""
    if not text:
        return text
    out = text
    for pattern, replacement in _RULES:
        out = pattern.sub(replacement, out)
    return out
