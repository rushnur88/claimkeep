# Changelog

## Unreleased

Atomic fact harvesting. Measured on LongMemEval, all 500 questions.

- **Added: the `atomic` harvester.** Selection now asks whether a person asserted
  something, instead of whether a regex matched. First-person and named-entity
  anchors keep the sentence; questions, hedges, imperatives, advice lists and
  headings are dropped. Each kept sentence carries a `subject|predicate-root`
  topic, so the supersession chain added in 0.3 finally has something to chain.
- **Measured: R@10 0.456 → 0.936, R@1 0.216 → 0.734**, at 12.9% of the haystack
  stored. The previous score was not retrieval working: of the 26 turns holding
  the answer, the old harvesters produced items for **zero** of them, so the
  number came from lexical overlap with noise. Evidence coverage is now 25/26.
- **Fixed: a hedge swallowed the fact riding inside it.** "I'm wondering if I
  should repot my snake plant, which I got from my sister last month" was dropped
  whole. A hedged sentence is now kept when it is the speaker's own and carries
  something concrete; bare speculation is still dropped. Worth 1.0 point of R@10
  and 1.6 of R@1 for 0.4 points of volume.
- **Fixed: the verb root dropped a silent `-e`.** `moved` stemmed to `mov`, which
  never matched its own infinitive, so "I moved to Boston" could not supersede
  "I move to Austin".
- **Fixed: a marked sentence was harvested twice.** A sentence carrying a
  `[C:NN%]` marker now belongs to the calibration harvester alone — collecting it
  in both spent brief budget on one fact and dropped the stated confidence from
  the copy.
- **Changed: rule-extracted claims rank below marked ones in the budget.** The
  atomic harvester is far more prolific than the others; at equal weight it
  would crowd paths, ids and decisions out of a 12k brief on agent transcripts.
- **Fixed: supersession fired on non-functional relations.** "I'm interested in
  the French Resistance" and "I'm interested in astronomy" share a subject and a
  verb but are two facts, not a correction; a quarter of harvested claims were
  being flagged superseded on first contact with real data. Only relations where
  a person has one value at a time (work, live, own, drive, attend, …) supersede
  on a new object.
- **Added: kept-volume reporting in the benchmark.** `run_recall.py` now prints
  harvested characters as a share of the haystack, because a recall figure with
  no compression figure next to it can always be gamed by keeping everything.
- **Added: `diag_evidence.py`.** Scores the thing R@k hides — what fraction of
  the turns that carry the answer survive collection at all.
- `atomic` runs first in the default harvester list; the other three stay for
  agent transcripts, where markers, paths and ids are the substance.

## 0.2.0 — 2026-08-10

Installation fix. `claude plugin install claimkeep` now actually works on its own.

- **Fixed: plugin install was a silent no-op.** The plugin was declared as the `plugins/claimkeep`
  subdirectory while the Python package lived at the repository root, so the installed plugin had
  nothing to run. The hooks printed `No module named claimkeep`, exited `0`, and wrote no brief —
  a green install that did nothing. The repository root is now the plugin itself: manifest at
  `.claude-plugin/plugin.json`, hooks at `hooks/hooks.json`, scripts at `scripts/`.
- **Fixed: hooks required a separate `pip install`.** They now export `PYTHONPATH` from
  `CLAUDE_PLUGIN_ROOT` and run the bundled package in place. An installed `claimkeep` binary is
  still preferred when present.
- Removed the `plugins/` tree; `package.json` `files` updated accordingly.
- README rewritten to three blocks — what it is, how to install, how to verify — with production
  numbers and a copy-paste verification that exercises both hooks.

## 0.1.0 — 2026-06-21

Initial release: brief schema, calibration and regex-floor harvesters, redaction, rehydration,
CLI, benchmark scorer, and control/treatment probe logging.
