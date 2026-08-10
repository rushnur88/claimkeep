"""Stream a LongMemEval JSON array one instance at a time (stdlib only).

The _s file is 277 MB; json.load on it is killed by the OOM reaper in a normal
container. The file is a flat array of objects, so raw_decode over a sliding
buffer yields instances without ever holding the whole array.
"""
import json


def iter_instances(path, chunk=1 << 20):
    decoder = json.JSONDecoder()
    with open(path, "r", encoding="utf-8") as handle:
        buf = ""
        # skip whitespace and the opening bracket
        while True:
            piece = handle.read(chunk)
            if not piece:
                return
            buf += piece
            start = buf.lstrip()
            if start.startswith("["):
                buf = start[1:]
                break
        while True:
            buf = buf.lstrip()
            while buf[:1] == ",":
                buf = buf[1:].lstrip()
            if buf[:1] == "]":
                return
            try:
                obj, end = decoder.raw_decode(buf)
            except ValueError:
                piece = handle.read(chunk)
                if not piece:
                    return
                buf += piece
                continue
            yield obj
            buf = buf[end:]


if __name__ == "__main__":
    import sys
    from collections import Counter
    path = sys.argv[1]
    n = 0
    types = Counter()
    sess_counts = []
    first = None
    for inst in iter_instances(path):
        n += 1
        types[inst["question_type"]] += 1
        sess_counts.append(len(inst["haystack_sessions"]))
        if first is None:
            first = inst
    print("instances:", n)
    print("fields:", sorted(first.keys()))
    print("types:", dict(types))
    sess_counts.sort()
    print("sessions per question: min %d median %d max %d" %
          (sess_counts[0], sess_counts[len(sess_counts)//2], sess_counts[-1]))
    print("example question:", first["question"][:110])
    print("example answer:", str(first["answer"])[:80])
    print("answer_session_ids:", first["answer_session_ids"])
    ev = sum(1 for s in first["haystack_sessions"] for t in s if t.get("has_answer"))
    print("evidence turns in example:", ev)
    print("sample turn keys:", sorted(first["haystack_sessions"][0][0].keys()))
