"""Open one question and show what survived collection in its gold session.

Aggregate diagnostics say which category is losing; this says why, for one
question, in the author's own words: every turn of the evidence session, whether
it was kept, and which of the question's terms it carried.

    python3 diag_one.py --type single-session-preference --index 0
"""

import argparse
import json
import sys

sys.path.insert(0, "/home/aria/.aria/agent-stream/shared/claimkeep")

from claimkeep.config import default_config
from claimkeep.harvesters import get_harvester
from claimkeep.retrieve import tokenize
from stream_lme import iter_instances

STOP = {
    "what", "when", "where", "which", "who", "why", "how", "did", "do", "does",
    "is", "are", "was", "were", "the", "a", "an", "of", "to", "in", "on", "at",
    "for", "with", "and", "or", "my", "i", "me", "you", "it", "that", "this",
    "have", "has", "had", "be", "can", "some", "any",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/state/agent/home/lme/data/longmemeval_s.json")
    ap.add_argument("--type", default="single-session-preference")
    ap.add_argument("--index", type=int, default=0, help="nth question of that type")
    ap.add_argument("--harvesters", default="atomic")
    args = ap.parse_args()

    config = default_config()
    config.harvesters = [n.strip() for n in args.harvesters.split(",") if n.strip()]

    found = 0
    for inst in iter_instances(args.data):
        if str(inst.get("question_type", "")) != args.type:
            continue
        if found < args.index:
            found += 1
            continue

        gold = set(str(x) for x in inst.get("answer_session_ids") or [])
        terms = {t for t in tokenize(inst["question"]) if t not in STOP and len(t) > 2}
        print("QUESTION:", inst["question"])
        print("TYPE:", inst.get("question_type"), "| terms:", sorted(terms))
        print()

        for sid, session in zip(inst["haystack_session_ids"], inst["haystack_sessions"]):
            if str(sid) not in gold:
                continue
            for turn in session:
                content = str(turn.get("content", ""))
                kept = []
                for name in config.harvesters:
                    kept.extend(i.text for i in get_harvester(name)().harvest([content], config))
                hit = terms & set(tokenize(content))
                kept_hit = terms & set(tokenize(" ".join(kept)))
                mark = "EVIDENCE" if turn.get("has_answer") else "        "
                print(f"[{mark}] {turn.get('role','?'):9} kept={len(kept)} "
                      f"terms_in_turn={sorted(hit)} terms_kept={sorted(kept_hit)}")
                if hit - kept_hit:
                    print("     LOST TERMS:", sorted(hit - kept_hit))
                    print("     TURN:", content.replace("\n", " ")[:300])
                for text in kept[:4]:
                    print("     KEPT:", text[:150])
        return
    print(json.dumps({"error": "no question of that type at that index"}))


if __name__ == "__main__":
    main()
