# ClaimKeep

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![tests](https://github.com/rushnur88/claimkeep/actions/workflows/tests.yml/badge.svg)](https://github.com/rushnur88/claimkeep/actions/workflows/tests.yml)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](pyproject.toml)
[![Paper](https://img.shields.io/badge/paper-Zenodo-1682D4.svg)](https://doi.org/10.5281/zenodo.21921441)

Continuous memory for Claude Code. When the context window compacts, the summary keeps the gist
and drops the specifics — numbers, paths, ids, and decisions that were later reversed. ClaimKeep
runs before compaction, takes the agent's own confidence-marked statements **verbatim** instead of
paraphrasing them, and re-injects them afterwards. It augments native compaction rather than
replacing it: in use you keep the summary and get the brief as well. The measurement below is the
harder question — brief *instead of* summary, at the same size — and there it wins on some kinds of
fact and loses on others.

https://github.com/user-attachments/assets/a0a6700e-8643-48a9-bc45-15a7f6c327fa

The idea it rests on: a calibration marker such as `Ship Friday [C:80%]` turns any factual sentence
into a claim the agent already selected and already rated. No guessing what mattered. A marker-free
regex floor still catches paths, ids, and decision lines when a transcript has no markers at all,
in English or Russian — the harvesters, the tokenizer and the redaction cues all work outside Latin.
The brief contract is frozen and documented in [docs/BRIEF_SCHEMA.md](docs/BRIEF_SCHEMA.md).

![A real run: the claim is harvested before compaction and comes back verbatim afterwards](docs/claimkeep-demo.gif)

The failure this addresses is specific. Compaction rarely forgets the topic; it forgets the exact
path, the port, the commit sha, the version that was ruled out. Those are the parts an agent cannot
reconstruct by reasoning, and the parts that turn a resumed session into a re-investigation. If your
sessions are short, you will never notice this. If you run long refactors, multi-day debugging, or
agent pipelines that compact several times a day, you have paid for it repeatedly.

**Against the real control, at equal budget: 18.0% → 33.9% of frozen probes recovered, +15.9
points** — and on the family built to be unwinnable, 7.3% → 29.4%.

The control is not a simulation. Claude Code writes its own compaction summary to the transcript
(`compact_boundary`, `isCompactSummary`), so the naive arm was already on disk — 69 real compactions,
1,491 probes frozen before any result was seen. Each arm was given exactly the number of characters
the native summary spent on that same compaction, because an unbounded brief is not a comparison.
Both arms run the shipped code: the full harvester set, supersession, the budget, and the renderer
that produces what the agent actually receives.

By probe family, at equal budget:

| family | native | ClaimKeep | |
|---|---|---|---|
| `fact` (bare number + word) | 7.3% | **29.4%** | **adversarial** — nothing in the plugin targets these |
| `claim` (marked `[C:NN%]`) | 8.2% | 35.8% | the native summary barely carries these |
| `hash` | 57.5% | 52.7% | native summary ahead |
| `path` | 72.2% | 29.9% | native summary well ahead |

Per compaction: **54 wins, 6 draws, 9 losses** out of 69, median +16.7, worst −19.2.

**Read the losses before the total.** At equal budget this trades paths and hashes for statements and
prose facts, and the trade is not subtle: paths drop from 72.2% to 29.9%. A rendered brief spends
characters on structure — a heading, a confidence, a topic and an id around every item — so fewer
items fit than the same budget of raw summary text holds. If what your compactions cost you is file
paths, the native summary is better at keeping them than this is. If it is the reasoning, the
decisions and the measured values, this is better by a wide margin, and those are the parts an agent
cannot reconstruct by looking again.

**Earlier versions of this number were higher, and each was measured on something the plugin does
not do.** The first, +59 points, counted a match anywhere in the output rather than co-located in one
item, gave the arms different sizes, and extracted path probes with the harvester's own regex; fixing
those took it to +17.8. Later runs reached +31.7 while the harness called two of the five harvesters
by hand and scored a newline-joined string the plugin never emits — no `retraction`, no `atomic`, no
supersession, and none of the rendering that the budget actually pays for. Running the real pipeline
brought it to the table above and moved `path` from a small win to a large loss. Every figure
published before this correction is superseded; the history is in [CHANGELOG.md](CHANGELOG.md).

Limits, since they decide whether the number transfers: one corpus, one agent, so generalisation is
untested. Full method and per-compaction data: `benchmark/`, and the paper below.

### What a fresh install gets

Your transcripts carry no `[C:NN%]` markers, and these do, so the difference is measured rather than
assumed: markers stripped from the text the harvesters see, probes frozen from the original so the
arms stay comparable, three arms in one pass. The `claim` family is excluded throughout — it is
marker-defined by construction. The same 69 compactions.

| arm | overall | `fact` | `hash` | `path` |
|---|---|---|---|---|
| native summary | 21.4% | 7.3% | 57.5% | 72.2% |
| ClaimKeep, markers present | 33.3% | 29.4% | 52.7% | 29.9% |
| ClaimKeep, markers stripped | **34.1%** | 30.8% | 51.6% | 28.9% |

**+11.9 points with markers, +12.7 without.** A marker-free install is not the degraded case: on
these families the two arms are within a point of each other, 45 wins to 19 losses, median +12.5.

That is worth sitting with, because it says the markers are not what carries this result. Strip them
and `calibration` still finds nothing, but `atomic` and `regex_floor` between them keep almost as
much — the gain here is in `fact`, prose values that the native summary drops and both arms of this
plugin keep at roughly four times the rate. Markers buy the `claim` family in the table above (8.2%
against 35.8%), which is the agent's own reasoning rather than the values in it.

`path` is the other half of the same sentence: 72.2% in the native summary against 29.9% here, in
both arms. Rendering costs characters, and at a fixed budget those characters come out of how many
items fit. This is the trade the plugin makes, not a knob it is missing.

One limit this design cannot escape: the native summary was written by a model that could see the
markers. That arm cannot be re-run without them, so if markers helped the control, the marker-free
delta is understated.

Both tables come from one script, on your own sessions:

```bash
python benchmark/natural_experiment.py ~/.claude/projects/<your-project-dir>
```

It finds the compactions Claude Code already recorded, freezes the probes before scoring, and prints
the headline and the marker-free arms. Any transcript directory with a few compactions in it works.

Separately, as live telemetry rather than a controlled comparison: on a Codex deployment (see
[integrations/codex/](integrations/codex/)) the
plugin has written **267 briefs since 22 July, 249 of which carried facts forward (93.3%), 3,564
claims retained**. That says the mechanism runs and produces non-empty briefs in daily use. It says
nothing about what the native summary would have kept — only the measurement above does.

Method and defensible lift numbers are in the paper, *"Continuous Memory for Multi-Agent
Infrastructure: A Calibration-Density Law for Surviving Context Compaction"* (Ravshan Nuraliev,
2026, v0.11) — <https://doi.org/10.5281/zenodo.21921441>. Please cite the Zenodo record if you use ClaimKeep.

## How this differs from what you already have

`CLAUDE.md` and memory MCP servers store what **you** decided to write down, ahead of time. That is
curation, and it works well for stable facts — conventions, architecture, preferences.

ClaimKeep stores what the **agent** said during the session and is about to lose. Nobody types those
facts into a memory file: they are discovered mid-work, used for ten minutes, and dropped by the
summarizer — the port you just found, the hypothesis you ruled out, the path that turned out to be
the real one. The two layers do not compete; curated memory answers *how we do things here*, and
ClaimKeep answers *what did I just find out*.

Three properties follow from that scope, and they are the reasons to prefer it over rolling your own:

- **It augments, never replaces.** Native compaction still runs; the brief is added on top. The
  failure mode of "my memory layer summarized worse than the built-in one" cannot happen here.
- **It cannot stall your session.** Both hooks are fail-open by construction and always exit `0`.
- **It refuses to fake a zero.** If retractions cannot be measured, `stats` reports *not measurable*
  rather than `0`. A metric that cannot distinguish "clean" from "not instrumented" is the exact bug
  this package is built to avoid.

## Recall from older sessions

The hooks above carry the newest brief across a compaction. Everything before it
stays on disk, indexed, and until now nothing read it: `claimkeep recall` was a
command a human could type, and the agent is who needs it.

A `UserPromptSubmit` hook closes that. On each turn it searches every stored
brief and lesson for what was just asked, and adds at most three short lines.

It is deliberately quiet, because a memory layer that interrupts every message
with guesses is worse than one that says nothing. A match has to contain the
words the question is about — measured on a 4,165-document store, that keeps
"render preset passport" answered and leaves "thanks, all good" alone. Matching
is on word prefixes so an inflected language still works, superseded claims
never surface, and each line is cut to 200 characters.

The cost of the trade is silence on questions whose wording missed: it prefers a
false negative to a false positive. Tuning, if you want it:

| variable | default | |
|---|---|---|
| `CLAIMKEEP_RECALL_HOOK` | `1` | `0` turns the hook off entirely |
| `CLAIMKEEP_RECALL_MIN_OVERLAP` | `0.5` | share of the question a match must contain |
| `CLAIMKEEP_RECALL_LIMIT` | `3` | maximum lines added |
| `CLAIMKEEP_RECALL_BUDGET` | `600` | characters for the whole block |
| `CLAIMKEEP_RECALL_ITEM_CHARS` | `200` | characters per line |

## Install

```bash
claude plugin marketplace add rushnur88/claimkeep
claude plugin install claimkeep
```

Two commands, and that is the whole install — no `pip install` step, no build, no dependencies:
the hooks run the bundled package straight from the plugin directory. Requirements are Claude Code
and Python 3.9+.

If you would rather have the CLI on your PATH as well, `pip install .` or `npm install -g .` both
work, and the hooks will prefer the installed binary when they find one.

Note that a memory layer reads your transcript. ClaimKeep runs a secret and PII redaction pass
before any text enters a brief (API keys, tokens, private-key blocks, JWTs, bearer tokens,
`key=value` secrets whatever prefix the variable name carries — `DB_PASSWORD`, `OPENAI_API_KEY`,
`AWS_SECRET_ACCESS_KEY` — a high-entropy blob introduced by a secret word, and emails), on by
default via `Config.redact`. It targets well-known shapes and is defense in depth, not a
guarantee — it is not a reason to paste credentials into a session.

## Codex CLI

ClaimKeep is built for Claude Code, which fires `PreCompact` and `SessionStart`. Codex CLI has
neither hook, so [`integrations/codex/`](integrations/codex/) supplies both: it harvests when
`turn.completed.usage.input_tokens` crosses a threshold, and injects the newest brief into the
`AGENTS.md` block Codex reads on every run. The package itself is used unchanged — the bridge
shells out to the same `claimkeep precompact` the Claude Code hook does, so fixes reach both paths
at once.

Stdlib only, seven tests, verified against Codex CLI 0.145.0. Setup and the two call sites are in
[integrations/codex/README.md](integrations/codex/README.md).

## Verify it works

Run the hook by hand against the bundled sample transcript. This is exactly what Claude Code runs
on `PreCompact`:

```bash
CLAIMKEEP_BRIEF_DIR=/tmp/ck-check ./scripts/precompact.sh <<'EOF'
{"transcript_path": "examples/sample_transcript.jsonl", "session_id": "verify-001"}
EOF
```

It prints the path of the brief it wrote. Confirm the brief exists and holds a claim:

```bash
cat /tmp/ck-check/*.json
```

You should see a `claims` array with `Ship ClaimKeep package Friday` at confidence `0.8`, plus a
`supplement` section with the ids, paths, and decision lines the floor picked up.

Then check the other half — re-injection:

```bash
CLAIMKEEP_BRIEF_DIR=/tmp/ck-check CLAUDE_HOOK_EVENT_NAME=PostCompact ./scripts/postcompact.sh <<< '{}'
```

It emits the `hookSpecificOutput.additionalContext` payload Claude Code feeds back into the fresh
window. If both commands produce output, the plugin is wired correctly.

Both hooks are fail-open on purpose — a memory layer must never block compaction, so they always
exit `0`. That means a broken install cannot stall your session, but it also means you should run
the two checks above once rather than assume silence equals success. Errors go to stderr.

Full test suite: `python3 -m unittest discover -s tests` (148 tests, standard library only).

The benchmarks run from a clone too — `python3 benchmark/russian_recall.py --db <store>`
and the scripts under `benchmark/longmemeval/`. They used to carry absolute paths from the
machine they were written on and could not start anywhere else, which made the numbers above
unreproducible by anyone but the author. CI now starts every one of them on each push.

## See what it did

`stats` reports across every brief you have stored, not just the last one:

```bash
claimkeep stats          # human-readable
claimkeep stats --json   # same numbers, machine-readable
```

It answers the question a single brief cannot: is the layer still earning its keep. Two lines matter
most. **Retractions** counts claims that overturn an earlier statement — a memory layer that keeps a
refuted claim and drops its refutation is worse than no memory at all. **Confidence-marked** is the
share of claims that arrived already carrying a `[C:NN%]` marker; when that share falls, the
convention is eroding and the calibration harvester quietly runs out of input.

**Dropped by budget** appears whenever the brief did not fit `budget_chars`, with the share of the
harvest that survived. A long session can harvest twenty thousand claims and keep under two hundred
of them; "claims kept" alone reads as the whole harvest and hides that the budget, not the
transcript, decided what you get back.

If your briefs came from a different collector, `stats` reports retractions as *not measurable*
rather than as zero. A zero you cannot distinguish from "never happened" is the failure mode this
package is built around, and the report is not allowed to produce one.

That holds in `--json` too: `retractions` is `null` — never `0` — whenever the count is
unavailable, alongside an explicit `retractions_measurable` flag, and `lessons_total` is `null`
when there is no lesson store to read. The machine-readable output is where a false zero does the
most damage, because a dashboard will plot it as a clean result and nobody will ask again.

---

Developed by Ravshan Nuraliev. MIT licensed.
