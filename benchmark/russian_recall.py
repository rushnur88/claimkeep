"""Does the read path work in Russian? A known-answer probe on a real corpus.

Why this exists
---------------
LongMemEval is English. The tokenizer shipped by this package matched
``[a-z0-9]+``, so on a Russian corpus every document tokenized to nothing and
every query returned zero results. That is not a weak score — it is a dead
function, and it was invisible because an empty result set is indistinguishable
from an honest "nothing matches".

The fix is one character class. This measures whether the fix restored the
function, on the corpus that actually matters: an agent fleet whose operators
speak Russian.

Result, 300 real lesson records (74% Cyrillic by character):

    tokenizer      R@1     R@3     R@5     R@10    queries returning nothing
    [a-z0-9]       0.513   0.657   0.713   0.757   15.3%
    +Cyrillic      0.893   0.963   0.967   0.980    0.0%

Note the honest shape of the "before" column: it is not zero. A corpus written
by engineers is never purely Russian — commit hashes, version numbers, English
technical terms — and the latin-only tokenizer found documents through those
fragments. So the failure was partial blindness, not death: queries phrased
entirely in Russian returned nothing, queries carrying an identifier survived.
The first draft of this note said "every Russian query returned zero", and the
measurement corrected it. That is what the measurement is for.

Method, stated plainly because the proxy matters
-----------------------------------------------
There is no Russian LongMemEval, and building one would need a model we do not
want as a dependency. So this uses a known-answer protocol over real lesson
records: the body of each lesson is a document, its title is the query, and a
hit means the lesson's own body came back in the top k.

Title and body are written separately — the title compresses, the body narrates
— so the overlap is partial rather than trivial. It is a proxy for recall, not a
substitute for a labelled benchmark, and it is honest about which one it is.
Both arms run over the identical corpus and queries; only the tokenizer differs.

    python3 russian_recall.py --limit 300
"""

import argparse
import json
import re
import sqlite3
import pathlib
import sys

# Run from a clone: resolve the package relative to this file instead of an
# absolute path from the machine the benchmark was first written on.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from claimkeep import retrieve
from claimkeep.retrieve import Document

KS = (1, 3, 5, 10)
LATIN_ONLY = re.compile(r"[a-z0-9]+")
WITH_CYRILLIC = re.compile(r"[a-z0-9Ѐ-ӿ]+")

# Strip the scaffolding every lesson title carries, so the query is the topic
# rather than the format.
_TITLE_NOISE = re.compile(r"(?i)ARIA-LESSON|\[?\d{4}-\d{2}-\d{2}[T\d:Z ]*\]?|\(.*?\)")


def load_lessons(db_path, limit):
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=5.0)
    rows = con.execute(
        # The body lives in `narrative`; `text` is empty on manually-saved
        # records. Reading the wrong column returns zero rows and looks exactly
        # like an empty corpus — the same silent-zero trap this file is about.
        "SELECT title, narrative FROM observations "
        "WHERE title LIKE '%ARIA-LESSON%' AND length(narrative) > 400 "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    out = []
    for index, (title, text) in enumerate(rows):
        query = _TITLE_NOISE.sub(" ", title or "").strip()
        if len(query) < 25 or not text:
            continue
        out.append({"id": "L%d" % index, "query": query, "body": text[:4000]})
    return out


def cyrillic_share(items):
    cyr = sum(len(re.findall(r"[Ѐ-ӿ]", i["body"])) for i in items)
    total = sum(len(re.findall(r"\w", i["body"])) for i in items) or 1
    return round(cyr / total, 3)


def measure(items, pattern):
    """Recall@k with the given token pattern, everything else identical."""
    previous = retrieve.TOKEN_RE
    retrieve.TOKEN_RE = pattern
    try:
        docs = [Document(text=i["body"], kind="claim", id=i["id"]) for i in items]
        hits = {k: 0 for k in KS}
        empty = 0
        for item in items:
            ranked = retrieve.score(item["query"], docs)
            if not ranked:
                empty += 1
                continue
            order = [row["doc"].id for row in ranked]
            for k in KS:
                if item["id"] in order[:k]:
                    hits[k] += 1
        n = len(items) or 1
        return {
            "R@%d" % k: round(hits[k] / n, 4) for k in KS
        }, round(empty / n, 4)
    finally:
        retrieve.TOKEN_RE = previous


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db",
        required=True,
        help="SQLite store holding the corpus. Required: this used to default to an "
        "absolute path on the author's machine, so the script ran nowhere else.",
    )
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    items = load_lessons(args.db, args.limit)
    if not items:
        print(json.dumps({"error": "no lessons found"}))
        return
    before, before_empty = measure(items, LATIN_ONLY)
    after, after_empty = measure(items, WITH_CYRILLIC)
    print(
        json.dumps(
            {
                "corpus": "real ARIA lesson records (title = query, body = document)",
                "documents": len(items),
                "cyrillic_share_of_body_chars": cyrillic_share(items),
                "latin_only_tokenizer": {"recall": before, "queries_with_zero_results": before_empty},
                "with_cyrillic_tokenizer": {"recall": after, "queries_with_zero_results": after_empty},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
