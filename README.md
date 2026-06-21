# ClaimKeep

ClaimKeep is a narrow continuous-memory plugin for Claude Code. Before compaction it harvests an agent's own high-signal claims into a schema-stable brief, and after compaction it re-injects that brief as additional context.

The hook mechanism is ordinary Claude Code plugin plumbing. The useful idea here is calibration markers as memory, backed by a marker-free floor for ids, paths, and decisions. The frozen brief contract is documented in [docs/BRIEF_SCHEMA.md](docs/BRIEF_SCHEMA.md).

## Install

Python package:

```bash
pip install .
claimkeep version
```

Claude Code plugin:

```bash
claude plugin marketplace add rushnur88/claimkeep
claude plugin install claimkeep
```

npm shim:

```bash
npm install -g .
claimkeep version
```

## Quickstart

Create a compact brief from a transcript:

```bash
python3 -m claimkeep precompact --transcript examples/sample_transcript.jsonl --out /tmp/ck_brief.json --now 2026-06-21T00:00:00Z
```

Render the payload used by `SessionStart` or `PostCompact` hooks:

```bash
python3 -m claimkeep postcompact --brief /tmp/ck_brief.json --event SessionStart
```

Hook mode reads Claude Code hook JSON on stdin. `PreCompact` expects `transcript_path`; `SessionStart` and `PostCompact` load the newest brief from `~/.claude/plugins/data/claimkeep/briefs` unless `CLAIMKEEP_BRIEF_DIR` points elsewhere.

## Markers and Floor

Calibration claims use the default configurable marker:

```text
Ship Friday [C:80%]
```

The marker is stripped from stored claim text, confidence becomes `0.8`, and the original line is retained as `source_span`. Transcripts with no calibration markers still produce valid briefs when the regex floor finds paths, ids, or decision lines.

## Security

A memory layer reads your transcript, so it could capture secrets or personal data. ClaimKeep runs a **secret / PII redaction pass before any text enters a brief** — API keys, tokens, private-key blocks, JWTs, bearer tokens, `key=value` secrets, and emails are masked, so credentials never persist into memory or get re-injected after compaction. It is on by default (`Config.redact = True`) and can be disabled per deployment.

Redaction is conservative defense-in-depth, not a guarantee: it targets well-known shapes and will not catch every secret. Do not rely on it as a reason to paste credentials into a session.

## Measuring the effect (control vs treatment)

To A/B the layer over one corpus, run two passes over the same transcripts:

- **treatment** — harvesting on (default),
- **control** — harvesting off (`CLAIMKEEP_HARVEST=0`), which yields an empty/naive brief.

Set `CLAIMKEEP_PROBE_LOG=<path>` (and optionally `CLAIMKEEP_CORPUS_ID`). Each
`precompact` then appends one JSONL record — the full reinjected brief plus a
`harvest_enabled` flag and a `session_id` / `corpus_id` / `ts` header — so a
scorer can compare the two arms on the same frozen probes. The hot harvest path
is untouched; this is logging only.

---

Developed at [PATech Labs](https://patechlabs.com).
