"""Why does a question miss, when the evidence turn was kept?

Evidence coverage is ~98% but R@10 is 0.936, so the losses are no longer in
collection — they are in ranking. This splits the remaining misses into the two
causes that call for opposite fixes:

  lexical   the question's terms are present in the raw gold session but absent
            from what was harvested. Selection threw away the matching words;
            fixing this means keeping more, or keeping different text.
  ranking   the terms survived harvesting and the gold session still lost to ten
            others. Keeping more will not help; the scorer or the document
            granularity is what needs to change.

    python3 diag_misses.py --limit 120 --harvesters atomic
"""

import argparse
import json
import pathlib
import sys

# Run from a clone: resolve the package relative to this file instead of an
# absolute path from the machine the benchmark was first written on.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from claimkeep.config import default_config
from claimkeep.harvesters import get_harvester
from claimkeep.retrieve import Document, score, tokenize
from stream_lme import iter_instances

STOP = {
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "did", "do", "does", "is", "are", "was", "were", "the", "a", "an", "of",
    "to", "in", "on", "at", "for", "with", "and", "or", "my", "i", "me", "you",
    "it", "that", "this", "have", "has", "had", "be", "been", "am", "s", "t",
}


def content_terms(question):
    return {t for t in tokenize(question) if t not in STOP and len(t) > 2}


def run(path, limit, names, group):
    config = default_config()
    if names:
        config.harvesters = list(names)

    misses = {"lexical": 0, "ranking": 0}
    by_type = {}
    examples = []
    scored = 0

    for index, inst in enumerate(iter_instances(path)):
        if limit and index >= limit:
            break
        gold = set(str(x) for x in inst.get("answer_session_ids") or [])
        if not gold:
            continue
        scored += 1

        docs, owner, gold_kept, gold_raw = [], {}, [], []
        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            units = [str(turn.get("content", "")) for turn in session]
            kept = []
            for name in config.harvesters:
                kept.extend(item.text for item in get_harvester(name)().harvest(units, config))
            if str(sid) in gold:
                gold_kept.extend(kept)
                gold_raw.extend(units)
            if group:
                if kept:
                    docs.append(Document(text="\n".join(kept), kind="claim", id=str(sid)))
                    owner[str(sid)] = str(sid)
            else:
                for seq, text in enumerate(kept):
                    doc_id = f"{sid}#h{seq}"
                    docs.append(Document(text=text, kind="claim", id=doc_id))
                    owner[doc_id] = str(sid)

        if not docs:
            continue
        ranked = score(inst["question"], docs)
        seen = []
        for row in ranked:
            sid = owner[row["doc"].id]
            if sid not in seen:
                seen.append(sid)
        if gold & set(seen[:10]):
            continue

        qtype = str(inst.get("question_type", "unknown"))
        terms = content_terms(inst["question"])
        raw_terms = terms & set(tokenize(" ".join(gold_raw)))
        kept_terms = terms & set(tokenize(" ".join(gold_kept)))
        lost = raw_terms - kept_terms
        cause = "lexical" if lost else "ranking"
        misses[cause] += 1
        bucket = by_type.setdefault(qtype, {"lexical": 0, "ranking": 0})
        bucket[cause] += 1
        if len(examples) < 10:
            examples.append(
                {
                    "type": qtype,
                    "cause": cause,
                    "question": inst["question"][:160],
                    "terms_lost_from_gold": sorted(lost)[:8],
                    "gold_items_kept": len(gold_kept),
                }
            )

    total = misses["lexical"] + misses["ranking"]
    return {
        "questions_scored": scored,
        "misses_at_10": total,
        "cause": misses,
        "cause_share": {
            k: round(v / total, 3) if total else 0.0 for k, v in misses.items()
        },
        "by_question_type": by_type,
        "examples": examples,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data",
        required=True,
        help="Path to longmemeval_s.json (download it; see benchmark/README.md).",
    )
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--harvesters", default="atomic")
    ap.add_argument("--group", action="store_true")
    args = ap.parse_args()
    names = [n.strip() for n in args.harvesters.split(",") if n.strip()]
    print(json.dumps(run(args.data, args.limit, names, args.group), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
