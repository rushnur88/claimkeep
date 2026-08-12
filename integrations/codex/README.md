# ClaimKeep for Codex CLI

ClaimKeep is written for Claude Code, which fires `PreCompact` and `SessionStart` hooks. Codex CLI
has neither, so this bridge supplies the two halves itself: it decides when to harvest, and it
injects the brief where Codex will read it.

The package is used **unchanged** — the bridge shells out to `claimkeep precompact` and
`claimkeep postcompact` exactly as the Claude Code hooks do. No fork, no vendored copy, so every
fix to the package reaches this path for free.

Stdlib only, like the package. Three files and a test.

## How the two halves are supplied

**When to harvest.** Claude Code tells a plugin that compaction is about to happen. Codex does not,
so context size is the proxy: after each run the bridge appends the turn to a rolling transcript and
checks `turn.completed.usage.input_tokens`. Above the threshold (default 250,000) it harvests a
brief and rotates the transcript, so the next thread starts clean.

**Where to inject.** Codex reads `AGENTS.md` on every run, which makes it the `SessionStart`
equivalent. The bridge renders the newest brief into a managed block in that file. `--stdout` is
available if you would rather prepend it to a prompt yourself.

## Install

```bash
git clone https://github.com/rushnur88/claimkeep
cd claimkeep/integrations/codex
python3 -m unittest test_codex_adapter -v      # expect 7 OK, none skipped
```

The tests find the package by walking up from their own location, so a clone needs no setup. If you
copy these files somewhere else, set `CLAIMKEEP_HOME` to the repository root — the bridge prepends
it to `PYTHONPATH` when it calls `python3 -m claimkeep`. With `pip install .` the CLI is on your
PATH and the variable is unnecessary.

If the run says `skipped=1`, the end-to-end test could not find the package and the most valuable
check did not happen. Treat that as a failure, not a pass.

## Wire it into your Codex runner

Both call sites are one function each. Gate them on an env flag so rollback is unsetting a variable.

After a `codex exec --json` run returns, hand it the stdout:

```python
from codex_claimkeep_write import on_run_complete

on_run_complete(
    codex_stdout,                                  # the full --json stdout of the run
    transcript_path="~/.claimkeep/codex/transcript.jsonl",
    brief_dir="~/.claimkeep/briefs",
    threshold=250_000,
)
```

Before a run, put the newest brief where Codex will see it:

```python
from codex_claimkeep_read import head_brief_markdown, update_agents_md

markdown = head_brief_markdown("~/.claimkeep/briefs")   # newest brief, rendered
if markdown:
    update_agents_md("AGENTS.md", markdown)             # into a managed block
```

Redaction is on by default, as in the package: secrets are masked before anything reaches a brief or
`AGENTS.md`. See [SECURITY.md](../../SECURITY.md) for what that does and does not cover.

**The subprocess needs to find the package.** `on_run_complete` shells out to `python3 -m claimkeep`,
so unless you ran `pip install .` you must export `CLAIMKEEP_HOME=/path/to/claimkeep` for the
process that calls it. Without it the harvest returns

```python
{"crossed_threshold": True, "harvested": False,
 "harvest_error": "No module named claimkeep"}
```

which reads as "nothing to harvest yet" if you only look at `harvested`. Check `harvest_error` on
every call and log it — that field is the difference between a threshold not reached and a bridge
that cannot run at all.

## Why `--json` is required

Plain `codex exec` prints a flat text log that cannot be parsed back into turns. With `--json` the
run is an event stream, and the assistant's answer arrives as:

```json
{"type":"item.completed","item":{"type":"agent_message","text":"..."}}
```

There is no `response.output_text.delta` event — the text is only in `item.completed`. Token usage
comes from `turn.completed.usage.input_tokens`, which is what the threshold reads.

Verified against **Codex CLI 0.145.0**. If a later version changes the event names, the adapter is
where to look: it is the only file that knows the schema, and `test_codex_adapter.py` pins it.

## Status

Running in production on one deployment since 22 July 2026: 267 briefs harvested, 249 of them
carrying facts forward. That is telemetry, not a controlled comparison — the measured lift in the
main [README](../../README.md) was done on Claude Code transcripts, where a native summary exists to
compare against. Codex writes no summary of its own, so there is no control arm to score here.
