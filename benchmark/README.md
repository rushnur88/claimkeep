# ClaimKeep Benchmark — compaction-survival harness

Measures how much high-signal context survives a compaction round when ClaimKeep
is on — and, critically, **splits retention by harvester** so the headline claim
can be tested honestly: *does an agent's own calibration discipline (`[C:NN%]`
markers) double as memory, and how strong is the marker-free floor?*

This is the **consumer** side of [`../docs/BRIEF_SCHEMA.md`](../docs/BRIEF_SCHEMA.md)
(v1, frozen). It scores **only** `claims[] + supplement[]`. `open_threads`,
`last_user_ask`, and `narrative` are rehydration UX and are **not** scored (§5).

## Method (pre-registered)

1. **Frozen probe set** — write the probes (`probes.example.json` shape) *before*
   the run. Each probe is one fact whose survival is scored. Freezing first is
   what makes the result pre-registered rather than fit after the fact.
2. **Control arm** — run the same transcript+probes with ClaimKeep OFF (no brief
   / empty brief) to get the baseline retention the hook must beat.
3. **Score** — `python score.py <brief.json> <probes.json>`:
   - `EXACT` — normalized probe == normalized brief item
   - `PARA`  — token Jaccard ≥ `PARA_THRESHOLD` (paraphrase survived)
   - `LOST`  — nothing reached the threshold (fact dropped)
4. **Headline** — `by_harvester` retention (calibration vs regex_floor).

### Rubric honesty

The automated EXACT/PARA/LOST scorer is the reproducible **CI proxy**. The
**blind human/LLM rubric** is the gold standard for the paper — `score.py` is the
mechanical pre-registration harness, not a replacement for blind judging. State
this in any write-up (Law 1: don't overclaim the automated number as the gold).

## v2 — multi-corpus replication

n=1 is the paper's main weakness. The harness ships so anyone can run the
pre-registered measure on **their own** corpus; v2 aggregates N runs into a
retention distribution (mean ± CI) and a pre-registered generalization test.
Open the benchmark, keep the fleet orchestration.

## The natural experiment (README numbers)

`natural_experiment.py` is where both headline figures come from. It needs no
probe file and no control run of its own, because Claude Code already writes a
compaction summary into every transcript — so the naive arm is on disk, produced
by the same model on the same context, and the comparison is against what you
actually get today rather than against an empty brief.

```bash
python natural_experiment.py ~/.claude/projects/<your-project-dir>
```

Both arms are truncated to the same character budget the native summary spent on
that compaction. It prints two tables: retention over all probe families, and the
marker-free arms — the same transcripts with every `[C:NN%]` stripped before
harvesting, which is what a fresh install sees. Probes are frozen from the
original text in both cases, so stripping markers cannot change which facts are
being scored.

## Files

- `natural_experiment.py` — the three-arm harness behind the README numbers.
- `score.py` — stdlib-only scorer (no third-party deps, no wall clock).
- `probes.example.json` — example frozen probe set + shape.

_Part of the ClaimKeep open core. The benchmark consumes the brief schema defined in [../docs/BRIEF_SCHEMA.md](../docs/BRIEF_SCHEMA.md)._
