"""Natural experiment: ClaimKeep vs the compaction summary Claude Code already wrote.

This is the harness behind the two numbers in the README. The control arm is not a
simulation — Claude Code writes its own summary into the transcript at every
compaction (`compact_boundary`, then a message with `isCompactSummary`), so the
naive arm is already on disk. Both arms get the same pre-boundary text, and the
brief is truncated to exactly the character budget the native summary spent on
that same compaction, because an unbounded brief is not a comparison.

Three arms, scored on identical probes in one pass:

    control     the native summary, as written
    marked      ClaimKeep on the transcript as-is
    markerfree  ClaimKeep with every [C:NN%] removed before harvesting

The third arm answers "what does a fresh install get", since a new user's
transcripts carry no calibration markers. Two details make it honest:

  * probes are frozen from the ORIGINAL text. Stripping markers first would
    change which lines `extract_probes` collects `fact` probes from, and the arms
    would no longer be comparable.
  * the `claim` family is excluded from the marker-free comparison — it is
    marker-defined by construction, so scoring it against a marker-free brief
    measures nothing.

The limit this design cannot escape: the native summary was written by a model
that could see the markers. That arm cannot be re-run without them, so if the
markers helped the control, the marker-free delta is understated.

Usage:

    python natural_experiment.py ~/.claude/projects/<project-dir>
    python natural_experiment.py <dir> --max-files 40 --json out.json

Requires the package: `pip install .` from the repository root, or pass
--claimkeep-home /path/to/claimkeep.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import statistics
import sys
import unicodedata

# How many probes of each family to freeze per compaction.
K_PATH, K_HASH, K_CLAIM, K_FACT = 15, 10, 15, 15
PARA = 0.5  # Jaccard threshold for "the claim survived as paraphrase"


def norm(t):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", t).casefold().strip())


def toks(t):
    return set(re.findall(r"[a-z0-9]+", norm(t)))


def jac(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def msg_text(obj):
    """Pull the text out of a transcript row, whatever shape it uses."""
    m = obj.get("message")
    if isinstance(m, str):
        return m
    if isinstance(m, dict):
        c = m.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts = []
            for it in c:
                if isinstance(it, str):
                    parts.append(it)
                elif isinstance(it, dict):
                    if isinstance(it.get("text"), str):
                        parts.append(it["text"])
                    elif isinstance(it.get("content"), str):
                        parts.append(it["content"])
                    elif isinstance(it.get("content"), list):
                        for s in it["content"]:
                            if isinstance(s, dict) and isinstance(s.get("text"), str):
                                parts.append(s["text"])
            if parts:
                return "\n".join(parts)
    for k in ("text", "content"):
        v = obj.get(k)
        if isinstance(v, str):
            return v
    return None


PATH_RE = re.compile(r"(?<![\w.])/(?:[A-Za-z0-9._-]+/){1,}[A-Za-z0-9._-]+")
HASH_RE = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}\b")
CLAIM_RE = re.compile(r"\[C:\s*(\d{1,3})\s*%[^\]]*\]")
NUMFACT_RE = re.compile(r"\b(\d[\d.,]{0,12})\s+([A-Za-z\u0400-\u04FF]{4,20})")


def extract_probes(assistant_texts):
    """Freeze the probe set from assistant-authored text, before any arm is inspected.

    The `fact` family is adversarial on purpose: bare "<number> <word>" in prose,
    which `regex_floor` explicitly skips and `calibration` cannot see without a
    marker. A benchmark whose every family favours the thing being measured is a
    press release.
    """
    paths, hashes, facts = (
        collections.Counter(),
        collections.Counter(),
        collections.Counter(),
    )
    claims, seen_claim = [], set()
    for t in assistant_texts:
        for m in PATH_RE.finditer(t):
            p = m.group(0).rstrip(".,;:)")
            if len(p) >= 12:
                paths[p] += 1
        for m in HASH_RE.finditer(t):
            hashes[m.group(0)] += 1
        for line in t.split("\n"):
            # Lines already carrying a marker, path or hash are covered by the
            # other families; taking facts from them too would double-count.
            if CLAIM_RE.search(line) or PATH_RE.search(line) or HASH_RE.search(line):
                continue
            for m in NUMFACT_RE.finditer(line):
                num, word = m.group(1).rstrip(".,"), m.group(2)
                if len(num) >= 2 and word.lower() not in (
                    "the",
                    "and",
                    "for",
                    "that",
                    "with",
                ):
                    facts[(num, word.casefold())] += 1
        if CLAIM_RE.search(t):
            for line in t.split("\n"):
                if CLAIM_RE.search(line):
                    stmt = CLAIM_RE.sub("", line).strip(" \t-•*—")
                    if 25 <= len(stmt) <= 400:
                        k = norm(stmt)
                        if k not in seen_claim:
                            seen_claim.add(k)
                            claims.append(stmt)

    probes = []
    for p, _ in sorted(paths.items(), key=lambda kv: (-kv[1], kv[0]))[:K_PATH]:
        probes.append({"id": "path:" + p, "family": "path", "needle": p, "text": p})
    for h, _ in sorted(hashes.items(), key=lambda kv: (-kv[1], kv[0]))[:K_HASH]:
        probes.append({"id": "hash:" + h, "family": "hash", "needle": h, "text": h})
    for (num, word), _ in sorted(facts.items(), key=lambda kv: (-kv[1], kv[0]))[
        :K_FACT
    ]:
        probes.append(
            {
                "id": "fact:%s-%s" % (num, word),
                "family": "fact",
                "needle": None,
                "needle_pair": [num, word],
                "text": "%s %s" % (num, word),
            }
        )
    for s in sorted(claims, key=lambda x: (-len(x), x))[:K_CLAIM]:
        probes.append(
            {
                "id": "claim:" + norm(s)[:60],
                "family": "claim",
                "needle": None,
                "text": s,
            }
        )
    return probes


def score_arm(probes, corpus_text, corpus_items):
    n_corpus = norm(corpus_text)
    n_items = [norm(i) for i in corpus_items if i.strip()]
    prepared = [(toks(i), i) for i in corpus_items if i.strip()]
    out = []
    for pr in probes:
        if pr["family"] == "fact":
            num, word = pr["needle_pair"]
            # Co-location required: number and word in the SAME item. Without this
            # a large corpus wins on accidental matches — "12" inside "2026-08-10".
            hit = any((num in it) and (word in it) for it in n_items)
            out.append(
                {
                    "id": pr["id"],
                    "family": "fact",
                    "verdict": "KEPT" if hit else "LOST",
                    "score": 1.0 if hit else 0.0,
                }
            )
        elif pr["family"] in ("path", "hash"):
            hit = norm(pr["needle"]) in n_corpus
            out.append(
                {
                    "id": pr["id"],
                    "family": pr["family"],
                    "verdict": "KEPT" if hit else "LOST",
                    "score": 1.0 if hit else 0.0,
                }
            )
        else:
            pt = toks(pr["text"])
            best = max((jac(pt, it) for it, _ in prepared), default=0.0)
            # Generous fallback: does the arm carry the probe's rare content words
            # anywhere at all? Credits the control for loose paraphrase.
            content = {w for w in pt if len(w) >= 5}
            corpus_words = set(re.findall(r"[a-z0-9]+", n_corpus))
            recall = (len(content & corpus_words) / len(content)) if content else 0.0
            out.append(
                {
                    "id": pr["id"],
                    "family": "claim",
                    "verdict": "KEPT" if best >= PARA else "LOST",
                    "score": round(best, 3),
                    "generous_recall": round(recall, 3),
                    "generous_kept": recall >= 0.6,
                }
            )
    return out


def build_arm(units, budget, api):
    """Build the arm the way production does, and score what it actually renders.

    This used to call `calibration` and `regex_floor` by hand and join their
    texts with newlines. That measured two harvesters out of five and a string
    the plugin never produces: `retraction`, `atomic` and `lessons` were absent,
    supersession never ran, and the brief the agent really receives is rendered
    markdown with headings, confidences and ids around each item.

    So the arm is `_build_brief` at the configured budget, then the shipped
    renderer. `units` carries roles, because that is what production passes and
    it is the only way `retraction` sees a correction at all.
    """
    brief = api["build_brief"](
        units, "2026-01-01T00:00:00Z", {"agent": "benchmark", "session": "arm"}
    )
    fitted = api["apply_budget"](brief, budget)
    items = [c.text for c in fitted.claims] + [s.text for s in fitted.supplement]
    return items, api["render"](fitted), len(fitted.claims), len(fitted.supplement)


def run_file(path, api):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    events = []
    for i, ln in enumerate(lines):
        if '"compact_boundary"' in ln or '"isCompactSummary":true' in ln.replace(
            " ", ""
        ):
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if obj.get("subtype") == "compact_boundary":
                events.append(("B", i, obj))
            elif obj.get("isCompactSummary"):
                events.append(("S", i, obj))

    out, start = [], 0
    for k in range(len(events)):
        if events[k][0] != "B":
            continue
        b_idx = events[k][1]
        s_obj = s_idx = None
        for kk in range(k + 1, len(events)):
            if events[kk][0] == "S":
                s_obj, s_idx = events[kk][2], events[kk][1]
                break
        if s_obj is None:
            continue
        summary = msg_text(s_obj) or ""
        if len(summary) < 200:
            continue

        units, assistant_texts = [], []
        for j in range(start, b_idx):
            try:
                obj = json.loads(lines[j])
            except Exception:
                continue
            t = msg_text(obj)
            if not t:
                continue
            # Feed the harvesters exactly what production feeds them. This calls
            # the shipped filter rather than a copy of it, so the measurement
            # cannot drift away from the behaviour it is supposed to describe.
            units.append((api["role_of"](obj), t))
            if obj.get("type") == "assistant":
                m = obj.get("message")
                if isinstance(m, dict) and m.get("role") == "assistant":
                    assistant_texts.append(t)
        start = s_idx + 1
        if len(units) < 20 or not assistant_texts:
            continue

        probes = extract_probes(assistant_texts)
        if len(probes) < 5:
            continue
        mf_probes = [p for p in probes if p["family"] != "claim"]

        budget = len(summary)
        stripped = [(role, CLAIM_RE.sub("", t)) for role, t in units]
        m_items, m_text, m_cl, m_su = build_arm(units, budget, api)
        f_items, f_text, f_cl, f_su = build_arm(stripped, budget, api)
        ctrl_items = [s for s in re.split(r"[\n.]+", summary) if s.strip()]

        out.append(
            {
                "file": os.path.basename(path),
                "boundary_line": b_idx,
                "pre_units": len(units),
                "summary_chars": len(summary),
                "n_probes": len(probes),
                "n_mf_probes": len(mf_probes),
                "marked_claims": m_cl,
                "marked_supps": m_su,
                "mf_claims": f_cl,
                "mf_supps": f_su,
                "probes": probes,
                "control": score_arm(probes, summary, ctrl_items),
                "treatment": score_arm(probes, m_text, m_items),
                # marker-free arms are scored on the claim-free probe set
                "mf_control": score_arm(mf_probes, summary, ctrl_items),
                "mf_marked": score_arm(mf_probes, m_text, m_items),
                "mf_markerfree": score_arm(mf_probes, f_text, f_items),
            }
        )
    return out


def tally(res, arm):
    fam = collections.defaultdict(lambda: {"k": 0, "n": 0})
    tot = {"k": 0, "n": 0}
    for r in res:
        for p in r[arm]:
            f = fam[p["family"]]
            f["n"] += 1
            tot["n"] += 1
            if p["verdict"] == "KEPT":
                f["k"] += 1
                tot["k"] += 1
    return tot, fam


def pct(d):
    return d["k"] / d["n"] * 100 if d["n"] else 0.0


def spread(res, arm, control_arm):
    w = d = l = 0
    deltas = []
    for r in res:
        c, t = r[control_arm], r[arm]
        if not c or not t:
            continue
        a = sum(1 for p in c if p["verdict"] == "KEPT") / len(c)
        b = sum(1 for p in t if p["verdict"] == "KEPT") / len(t)
        x = (b - a) * 100
        deltas.append(x)
        w, d, l = (
            (w + 1, d, l) if x > 0 else ((w, d + 1, l) if x == 0 else (w, d, l + 1))
        )
    deltas.sort()
    return w, d, l, deltas


def report(res):
    print(
        "compactions: %d   probes: %d\n" % (len(res), sum(r["n_probes"] for r in res))
    )

    print("=== headline: all probe families ===")
    for arm, label in (("control", "native summary"), ("treatment", "ClaimKeep")):
        tot, fam = tally(res, arm)
        by = "  ".join("%s %.1f%%" % (k, pct(fam[k])) for k in sorted(fam))
        print("  %-16s %5.1f%%   %s" % (label, pct(tot), by))
    c = pct(tally(res, "control")[0])
    t = pct(tally(res, "treatment")[0])
    w, d, l, ds = spread(res, "treatment", "control")
    print(
        "  delta %+.1f points | wins %d draws %d losses %d | worst %+.1f median %+.1f"
        % (t - c, w, d, l, ds[0] if ds else 0, statistics.median(ds) if ds else 0)
    )

    print("\n=== what a fresh install gets (claim family excluded) ===")
    rows = (
        ("mf_control", "native summary"),
        ("mf_marked", "markers present"),
        ("mf_markerfree", "markers stripped"),
    )
    print("  %-18s %8s %8s %8s %8s" % ("arm", "overall", "fact", "hash", "path"))
    for arm, label in rows:
        tot, fam = tally(res, arm)
        print(
            "  %-18s %7.1f%% %7.1f%% %7.1f%% %7.1f%%"
            % (label, pct(tot), pct(fam["fact"]), pct(fam["hash"]), pct(fam["path"]))
        )
    c = pct(tally(res, "mf_control")[0])
    m = pct(tally(res, "mf_marked")[0])
    f = pct(tally(res, "mf_markerfree")[0])
    print("  delta vs control: with markers %+.1f, marker-free %+.1f" % (m - c, f - c))
    if m > c:
        share = (f - c) / (m - c) * 100
        print(
            "  marker-free %s the marked arm (%.0f%% of its lift)"
            % ("exceeds" if share > 100 else "keeps", share)
        )
    for arm, label in (
        ("mf_marked", "markers present"),
        ("mf_markerfree", "marker-free   "),
    ):
        w, d, l, ds = spread(res, arm, "mf_control")
        print(
            "  %s per compaction: wins %d draws %d losses %d | worst %+.1f median %+.1f"
            % (label, w, d, l, ds[0] if ds else 0, statistics.median(ds) if ds else 0)
        )

    print(
        "\nbrief composition (mean items per compaction, after the budget cut):"
    )
    print(
        "  markers present: calibration %5.1f, regex_floor %6.1f"
        % (
            statistics.mean(r["marked_claims"] for r in res),
            statistics.mean(r["marked_supps"] for r in res),
        )
    )
    print(
        "  markers stripped: calibration %4.1f, regex_floor %6.1f"
        % (
            statistics.mean(r["mf_claims"] for r in res),
            statistics.mean(r["mf_supps"] for r in res),
        )
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "transcript_dir",
        help="a Claude Code project dir, e.g. ~/.claude/projects/<project>",
    )
    ap.add_argument(
        "--max-files",
        type=int,
        default=40,
        help="stop after this many transcripts that yielded compactions",
    )
    ap.add_argument("--json", metavar="PATH", help="write per-compaction results here")
    ap.add_argument(
        "--claimkeep-home",
        metavar="PATH",
        help="repository root, if the package is not installed",
    )
    args = ap.parse_args()

    if args.claimkeep_home:
        sys.path.insert(0, os.path.expanduser(args.claimkeep_home))
    try:
        from claimkeep.cli import _build_brief, _role_of
        from claimkeep.config import default_config
        from claimkeep.rehydrate import render
        from claimkeep.select import apply_budget
    except ImportError:
        sys.exit(
            "claimkeep not importable: run `pip install .` from the repo root, "
            "or pass --claimkeep-home /path/to/claimkeep"
        )

    d = os.path.expanduser(args.transcript_dir)
    files = sorted(glob.glob(os.path.join(d, "*.jsonl")), key=os.path.getsize)
    if not files:
        sys.exit("no .jsonl transcripts in %s" % d)

    # The brief is bounded per compaction against the control's own size, so the
    # configured cap must not bound it first — otherwise every arm is measured
    # against whichever of the two is smaller.
    os.environ["CLAIMKEEP_BUDGET_CHARS"] = "0"
    default_config()  # re-read with the override in place
    api = {
        "build_brief": _build_brief,
        "apply_budget": apply_budget,
        "render": render,
        "role_of": _role_of,
    }
    done, all_res = 0, []
    for p in files:
        if done >= args.max_files:
            break
        try:
            r = run_file(p, api)
        except Exception as e:
            print("ERR %s %r" % (os.path.basename(p), e), file=sys.stderr)
            continue
        if r:
            all_res.extend(r)
            done += 1

    if not all_res:
        sys.exit(
            "no compactions found: these transcripts have no compact_boundary rows yet"
        )

    report(all_res)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(all_res, f, ensure_ascii=False)
        print("\nper-compaction data: %s" % args.json)


if __name__ == "__main__":
    main()
