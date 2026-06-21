# Single Agent Quickstart

Generate a brief from the sample transcript:

```bash
python3 -m claimkeep precompact --transcript examples/sample_transcript.jsonl --out /tmp/ck_brief.json --now 2026-06-21T00:00:00Z
```

Render the post-compaction hook payload:

```bash
python3 -m claimkeep postcompact --brief /tmp/ck_brief.json --event SessionStart
```
