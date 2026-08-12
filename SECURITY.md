# Security

ClaimKeep reads your session transcript and writes part of it to disk, so the
interesting failures here are about what ends up in a brief that should not have.

## Reporting

Use GitHub's private reporting: **Security → Report a vulnerability** on
<https://github.com/rushnur88/claimkeep>. That keeps the report out of public
issues until there is a fix. If you would rather not use GitHub, open a public
issue saying only that you have something to report and asking for a contact —
no details in the issue itself.

Please include the input that triggers it. A transcript line, with the secret
replaced by an obviously fake value of the same shape, is worth more than a
description: every redaction bug found so far was found by running a real
transcript through the plugin and reading what reached the brief, not by reading
the regex.

Expect a first reply within a few days. This is a single-maintainer project, not
a vendor with an on-call rotation — that is the honest expectation to set.

## What counts

- A credential or personal datum reaching `claims`, `supplement`, `source_span`
  or the re-injected context.
- A brief written outside `CLAIMKEEP_BRIEF_DIR`, or readable by other users.
- Anything in a brief that survives into a fresh session without passing through
  redaction.
- A hook that blocks, hangs or crashes compaction. Both hooks exit `0` by design;
  a path that does not is a bug worth reporting even without a security angle.

## What does not

- Secrets you pasted into the session yourself and did not redact. Redaction is
  defense in depth, not a licence to paste credentials.
- Shapes the redactor does not know. It targets well-known ones — API keys,
  tokens, private-key blocks, JWTs, bearer tokens, `key=value` secrets whatever
  prefix the name carries, high-entropy blobs introduced by a secret word, and
  emails. A novel shape slipping through is a gap to close, not an exploit; open
  a normal issue with an example.
- Anything requiring an attacker who can already read your filesystem. If they
  can read `~/.claude/plugins/data/claimkeep/briefs`, they can read the
  transcript it came from.

## Scope of the redaction pass

It runs once over the whole transcript before any harvester sees it
(`claimkeep/cli.py`), so every field of a brief is covered by the same pass, not
just `claims`. It is regex-based and language-independent for shape rules; rules
that key on a cue word carry both English and Russian, and adding a language is a
one-line change in `claimkeep/redact.py`.

Known limits, stated plainly rather than discovered by a reader:

- An AWS **secret** access key has no recognisable prefix. It is caught only when
  a cue word introduces it or a `key=value` name signals it. Bare, alone on a
  line, it is not caught.
- Redaction is applied at harvest time. Briefs written by an earlier version are
  not re-scanned; delete them if an older version leaked into them.
- `Config.redact = False` disables the pass entirely. Nothing else changes
  behaviour silently.
