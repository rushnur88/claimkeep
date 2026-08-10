"""Does the harvester keep the turn that actually holds the answer?

R@k tells you whether the right session ranked highly. It does not tell you
whether the evidence survived collection at all — a pipeline can score a
non-trivial R@10 purely on lexical overlap with noise it kept by accident. That
is exactly what the 2026-08-10 baseline turned out to be doing: 45.6% R@10 with
**zero** items harvested from the 26 turns carrying the answer.

So this measures the thing R@k hides: of the turns LongMemEval marks
`has_answer: true`, what fraction produced at least one harvested item.

    python3 diag_evidence.py --limit 25 --harvesters atomic
"""

import argparse
import json
import sys

sys.path.insert(0, "/home/aria/.aria/agent-stream/shared/claimkeep")

from claimkeep.config import default_config
from claimkeep.harvesters import get_harvester
from stream_lme import iter_instances


def run(path, limit, names):
    config = default_config()
    if names:
        config.harvesters = list(names)

    turns = evidence_turns = evidence_covered = kept_items = 0
    kept_turns = 0
    by_harvester, by_kind = {}, {}
    misses = []

    for index, inst in enumerate(iter_instances(path)):
        if limit and index >= limit:
            break
        for session in inst["haystack_sessions"]:
            for turn in session:
                content = str(turn.get("content", ""))
                turns += 1
                items = []
                for name in config.harvesters:
                    items.extend(get_harvester(name)().harvest([content], config))
                if items:
                    kept_turns += 1
                    kept_items += len(items)
                for item in items:
                    src = getattr(item, "source_harvester", "?")
                    by_harvester[src] = by_harvester.get(src, 0) + 1
                    kind = getattr(item, "kind", "claim")
                    by_kind[kind] = by_kind.get(kind, 0) + 1
                if turn.get("has_answer"):
                    evidence_turns += 1
                    if items:
                        evidence_covered += 1
                    elif len(misses) < 12:
                        misses.append(content[:220])

    return {
        "questions": limit or "all",
        "harvesters": list(config.harvesters),
        "turns_seen": turns,
        "turns_kept": kept_turns,
        "turns_kept_share": round(kept_turns / turns, 4) if turns else 0.0,
        "items_kept": kept_items,
        "by_harvester": by_harvester,
        "by_kind": by_kind,
        "evidence_turns": evidence_turns,
        "evidence_turns_covered": evidence_covered,
        "evidence_coverage": round(evidence_covered / evidence_turns, 4) if evidence_turns else 0.0,
        "sample_missed_evidence": misses,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/longmemeval_s.json")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--harvesters", default="")
    args = ap.parse_args()
    names = [n.strip() for n in args.harvesters.split(",") if n.strip()]
    print(json.dumps(run(args.data, args.limit, names), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
