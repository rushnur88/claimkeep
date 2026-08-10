"""Free arm of LongMemEval: does ClaimKeep's read path retrieve the evidence?

No judge, no answering model, no paid call. The dataset ships its own labels -
`answer_session_ids` marks the sessions holding the evidence - so retrieval
accuracy can be scored offline. This is the same axis competing memory plugins
quote as R@k, which makes the number directly comparable.

Two arms, because they answer different questions:

  raw        documents are the haystack sessions/turns verbatim. Measures the
             BM25 read path purely as a retriever.
  harvested  documents are what ClaimKeep's harvesters extract from the same
             sessions. Measures the shipped pipeline end to end.

The gap between them is the point. A retriever can only find what the harvester
kept, and the harvesters were built for agent transcripts, not human chat.
"""

import argparse
import json
import sys

sys.path.insert(0, "/home/aria/.aria/agent-stream/shared/claimkeep")

from claimkeep.config import default_config
from claimkeep.harvesters import get_harvester
from claimkeep.retrieve import Document, score
from stream_lme import iter_instances

KS = (1, 3, 5, 10)


def session_text(session):
    return "\n".join(f"{turn.get('role', '')}: {turn.get('content', '')}" for turn in session)


def build_raw_docs(inst, granularity):
    """One document per session, or one per turn, tagged with its session id."""
    docs, owner = [], {}
    for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
        if granularity == "session":
            doc_id = str(sid)
            docs.append(Document(text=session_text(session), kind="claim", id=doc_id))
            owner[doc_id] = str(sid)
        else:
            for index, turn in enumerate(session):
                doc_id = f"{sid}#{index}"
                docs.append(Document(text=str(turn.get("content", "")), kind="claim", id=doc_id))
                owner[doc_id] = str(sid)
    return docs, owner


def build_harvested_docs(inst, config):
    """Documents are whatever ClaimKeep's harvesters keep from the same sessions."""
    docs, owner = [], {}
    for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
        units = [str(turn.get("content", "")) for turn in session]
        seq = 0
        for name in config.harvesters:
            for item in get_harvester(name)().harvest(units, config):
                doc_id = f"{sid}#h{seq}"
                seq += 1
                kind = getattr(item, "kind", "claim")
                docs.append(Document(text=item.text, kind=kind, id=doc_id))
                owner[doc_id] = str(sid)
    return docs, owner


def evaluate(path, arm, granularity, limit, harvesters=None):
    config = default_config()
    if harvesters:
        config.harvesters = list(harvesters)
    hits = {k: 0 for k in KS}
    scored = skipped_abstention = empty_corpus = zero_result = 0
    doc_counts = []
    # Recall alone is only half the claim. A memory layer that keeps everything
    # scores like the haystack and saves nobody any context, so kept volume is
    # reported next to recall and the two are read together.
    kept_chars, haystack_chars = [], []

    for index, inst in enumerate(iter_instances(path)):
        if limit and index >= limit:
            break
        gold = set(str(x) for x in inst.get("answer_session_ids") or [])
        if not gold:
            # Abstention questions have no evidence session; recall is undefined.
            skipped_abstention += 1
            continue
        if arm == "raw":
            docs, owner = build_raw_docs(inst, granularity)
        else:
            docs, owner = build_harvested_docs(inst, config)
        doc_counts.append(len(docs))
        kept_chars.append(sum(len(d.text) for d in docs))
        haystack_chars.append(sum(len(session_text(sess)) for sess in inst["haystack_sessions"]))
        if not docs:
            empty_corpus += 1
            scored += 1
            continue
        ranked = score(inst["question"], docs)
        if not ranked:
            zero_result += 1
            scored += 1
            continue
        seen_sessions = []
        for row in ranked:
            sid = owner[row["doc"].id]
            if sid not in seen_sessions:
                seen_sessions.append(sid)
        scored += 1
        for k in KS:
            if gold & set(seen_sessions[:k]):
                hits[k] += 1

    doc_counts.sort()
    total_kept, total_hay = sum(kept_chars), sum(haystack_chars)
    return {
        "harvesters": list(config.harvesters) if arm == "harvested" else None,
        "kept_chars_share_of_haystack": round(total_kept / total_hay, 4) if total_hay else 0.0,
        "median_kept_chars_per_question": sorted(kept_chars)[len(kept_chars) // 2] if kept_chars else 0,
        "arm": arm,
        "granularity": granularity,
        "scored_questions": scored,
        "skipped_abstention": skipped_abstention,
        "questions_with_empty_corpus": empty_corpus,
        "questions_with_zero_lexical_match": zero_result,
        "median_docs_per_question": doc_counts[len(doc_counts) // 2] if doc_counts else 0,
        "recall": {f"R@{k}": round(hits[k] / scored, 4) if scored else 0.0 for k in KS},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/longmemeval_s.json")
    ap.add_argument("--arm", choices=("raw", "harvested"), default="raw")
    ap.add_argument("--granularity", choices=("session", "turn"), default="session")
    ap.add_argument("--limit", type=int, default=0, help="0 = all 500")
    ap.add_argument("--harvesters", default="", help="comma-separated override, harvested arm only")
    args = ap.parse_args()
    names = [n.strip() for n in args.harvesters.split(",") if n.strip()]
    report = evaluate(args.data, args.arm, args.granularity, args.limit, names)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
