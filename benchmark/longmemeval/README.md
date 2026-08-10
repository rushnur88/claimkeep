# LongMemEval — retrieval arm (no judge, no paid call)

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) (ICLR 2025) ships its own
evidence labels: `answer_session_ids` names the sessions holding the answer, and
evidence turns carry `has_answer: true`. That makes retrieval accuracy scorable
offline — no answering model, no LLM judge, no API key. It is also the axis
competing memory plugins quote as R@k, so the number is directly comparable.

The QA arm (feed retrieved context to a model, grade with the official
`evaluate_qa.py` judge on gpt-4o) is a separate, paid step and is not run here.

## Running it

```
mkdir -p data && cd data
wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json -O longmemeval_s.json
cd ..
python3 run_recall.py --arm raw       --granularity session   # retriever alone
python3 run_recall.py --arm harvested                         # shipped pipeline
python3 run_recall.py --arm harvested --harvesters atomic     # one harvester
python3 diag_evidence.py --limit 25 --harvesters atomic       # evidence coverage
```

`stream_lme.py` parses the 277 MB array incrementally. `json.load` on it is
killed by the OOM reaper in a normal container — the streaming reader is not an
optimisation, it is the difference between running and not running.

## Results, all 500 questions

Session-level recall: does the top-k contain a session from `answer_session_ids`?
`kept` is harvested characters as a share of the haystack — recall alone would
reward a memory layer that keeps everything and saves nobody any context, so the
two columns are read together.

| arm | R@1 | R@3 | R@5 | R@10 | kept |
|---|---|---|---|---|---|
| raw, session granularity | 0.862 | 0.942 | 0.968 | 0.982 | 100% |
| raw, turn granularity | 0.864 | 0.922 | 0.952 | 0.976 | 100% |
| **harvested, `atomic`** | **0.734** | **0.852** | **0.892** | **0.936** | **12.9%** |
| harvested, `atomic` + `regex_floor` | 0.738 | 0.852 | 0.888 | 0.926 | 20.2% |
| harvested, pre-`atomic` harvesters (2026-08-10 baseline) | 0.216 | 0.314 | 0.370 | 0.456 | 7.9% |

The hybrid row was measured before the hedge rule was relaxed. It bought 2 points
of R@1 for 8 points of volume, so it is not the default.

`raw` scores the BM25 read path directly over the haystack, so it is the ceiling
this retriever can reach and not a configuration anyone would ship: it stores the
entire conversation. The harvested rows are what ClaimKeep actually keeps.

## What changed, and why the earlier number was worse than it looked

The baseline row is the pipeline as it stood on the morning of 2026-08-10. Its
R@10 of 0.456 was not the pipeline finding answers. A per-turn diagnostic over
the first 25 questions (12,594 turns) showed:

- 1,482 items kept, 11.8% of turns
- by harvester: `regex_floor` 1,465, `lessons` 17, `calibration` **0**
- of 26 turns carrying the answer, **0** produced a harvested item

Zero evidence coverage with a non-trivial R@10 means the score came from
accidental lexical overlap with noise. Three concrete faults, all in selection:

1. **Calibration harvested nothing off human chat.** It needs `[C:NN%]` markers,
   which only an instructed agent emits. On a human corpus it is dead weight,
   and on our own transcripts it had been flattering us.
2. **The path recogniser fired on prose.** `PATH_RE` matches any `word/word`, so
   `1/2` and `Indie/Alternative` were stored as paths.
3. **The decision recogniser fired on any sentence containing a choice verb**,
   including "there are many destinations that would be perfect for a romantic
   getaway".

`atomic` replaces the selection step. It keeps a sentence when a person asserts
something — first-person anchor, or a named entity or dated quantity — and drops
questions, hedges, imperatives, advice lists and headings. Each kept sentence
gets a `subject|predicate-root` topic so a later statement on a functional
relation supersedes the earlier one instead of sitting beside it. Same diagnostic
after the change: evidence coverage **25 of 26** on the first 25 questions, and
**50 of 51** over the first 50 (25,024 turns, 59.4% of turns kept).

## Reading the gap that is left

The retriever ceiling is 0.982 R@10 with the whole haystack in the index.
`atomic` reaches 0.936 while storing 12.9% of it — roughly 8x compression for
4.6 points of recall. Whether that trade is right depends on what the memory is for: a
brief that has to fit back into a freshly compacted context cannot store the
haystack, which is the entire reason the budget exists.

Two honest caveats on comparability. First, published R@k figures from other
projects (Cortex quotes 97.8% on LongMemEval) do not usually state what fraction
of the corpus they index, so a like-for-like reading needs their compression
number too. Second, retrieval accuracy is not answer accuracy — the QA arm with
the official judge is the number that settles that, and it has not been run.

Where the remaining 4.6 points sit is measurable rather than guessable: run
`diag_evidence.py` and look at `sample_missed_evidence`. At 50 questions exactly
one evidence turn is missed, and it is the known class — verbless assertion
("Congratulations on your degree in Business Administration!"), which the triple
extractor rejects for having no finite verb. Note that near-total evidence
coverage does not imply near-total recall: keeping the turn is necessary for the
session to be findable, not sufficient for it to outrank 40 other sessions.
