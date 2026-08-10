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
python3 run_recall.py --arm raw       --granularity turn      # finer granularity
python3 run_recall.py --arm harvested                         # shipped pipeline
```

`stream_lme.py` parses the 277 MB array incrementally. `json.load` on it is
killed by the OOM reaper in a normal container — the streaming reader is not an
optimisation, it is the difference between running and not running.

## Results, 2026-08-10, all 500 questions

Session-level recall: does the top-k contain a session from `answer_session_ids`?

| arm | granularity | R@1 | R@3 | R@5 | R@10 |
|---|---|---|---|---|---|
| raw | session | 0.862 | 0.942 | 0.968 | 0.982 |
| raw | turn | 0.864 | 0.922 | 0.952 | 0.976 |
| harvested | session | 0.216 | 0.314 | 0.370 | 0.456 |

`raw` scores the BM25 read path directly over the haystack. `harvested` scores
the shipped pipeline: the same sessions after ClaimKeep's harvesters decide what
is worth keeping.

## What the gap means

The retriever is not the bottleneck. The harvesters are.

Diagnostic over the first 25 questions (12,594 turns):

- 1,482 items kept, 11.8% of turns
- by harvester: `regex_floor` 1,465, `lessons` 17, `calibration` **0**
- by kind: path 945, decision 448, id 72, claim 17
- of 26 evidence turns, **0** produced a harvested item

Three failures, all specific:

1. **Calibration harvests nothing off human chat.** It needs `[C:NN%]` markers,
   which only an instructed agent emits. On a human corpus that harvester is
   dead weight, and on our own transcripts it was flattering us.
2. **The path recogniser fires on prose.** `1/2` and `Indie/Alternative` are
   stored as paths. `PATH_RE` matches any `word/word`, which is harmless in a
   terminal transcript and pure noise in a conversation.
3. **The decision recogniser fires on any sentence containing a choice verb**,
   including "there are many destinations that would be perfect for a romantic
   getaway".

So the 45.6% R@10 of the harvested arm is not the pipeline finding answers — it
is accidental lexical overlap with noise, because the evidence itself was never
kept. The honest reading is that ClaimKeep currently has a strong reader bolted
to a harvester that only works on agent-shaped text.

Atomic fact extraction is therefore not the next nice-to-have. It is the blocker.
