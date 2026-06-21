"""ClaimKeep benchmark — retention scorer (consumer side of docs/BRIEF_SCHEMA.md v1).

Scores how much of a pre-registered *frozen probe set* survives in a brief.

Contract conformance (BRIEF_SCHEMA.md §5):
  - Scores ONLY claims[] + supplement[].
  - open_threads / last_user_ask / narrative are rehydration UX — NOT scored.
  - Retention is reported split by source_harvester (calibration vs floor) —
    that split is the headline result (does calibration discipline = memory,
    and how strong is the marker-free floor).

Rubric (automated CI proxy for the blind human/LLM gold rubric):
  EXACT  — normalize(probe) == normalize(item)            (1.0)
  PARA   — token Jaccard(probe, item) >= PARA_THRESHOLD   (paraphrase survived)
  LOST   — no item reaches PARA_THRESHOLD                 (fact dropped)
The blind human/LLM rubric is the gold standard for the paper; this mechanical
scorer is the reproducible pre-registration / CI proxy. Stdlib-only, no wall clock.

CLI:  python score.py <brief.json> <probes.json>   ->  JSON report on stdout
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

PARA_THRESHOLD = 0.5


def _norm(text: str) -> str:
    """Same normalization the producer uses for id hashing (BRIEF_SCHEMA §4)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold().strip())


def _tokens(text: str) -> Set[str]:
    return set(re.findall(r"[a-z0-9]+", _norm(text)))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _brief_items(brief: Dict[str, Any]) -> List[Dict[str, str]]:
    """Flatten the ONLY two scored arrays into (text, harvester) items."""
    items: List[Dict[str, str]] = []
    for claim in brief.get("claims", []):
        items.append({"text": claim["text"],
                      "harvester": claim.get("source_harvester", "calibration")})
    for supp in brief.get("supplement", []):
        items.append({"text": supp["text"],
                      "harvester": supp.get("source_harvester", "regex_floor")})
    return items


def score(brief: Dict[str, Any], probes: List[Dict[str, Any]]) -> Dict[str, Any]:
    prepared: List[Tuple[str, Set[str], str]] = [
        (_norm(i["text"]), _tokens(i["text"]), i["harvester"]) for i in _brief_items(brief)
    ]
    results: List[Dict[str, Any]] = []
    for probe in probes:
        pn, pt = _norm(probe["text"]), _tokens(probe["text"])
        verdict, best, matched = "LOST", 0.0, None
        for n, toks, harv in prepared:
            if n == pn:
                verdict, best, matched = "EXACT", 1.0, harv
                break
        if verdict != "EXACT":
            for n, toks, harv in prepared:
                j = _jaccard(pt, toks)
                if j > best:
                    best, matched = j, harv
            verdict = "PARA" if best >= PARA_THRESHOLD else "LOST"
            if verdict == "LOST":
                matched = None
        results.append({
            "id": probe["id"],
            "verdict": verdict,
            "score": round(best, 3),
            "matched_harvester": matched,
            # expected_harvester lets us attribute LOST probes to the arm that
            # SHOULD have caught them (a LOST probe has no matched_harvester).
            "expected_harvester": probe.get("harvester"),
        })
    return _aggregate(results)


def _aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {"EXACT": 0, "PARA": 0, "LOST": 0}
    by_harv: Dict[str, Dict[str, int]] = {}
    for r in results:
        counts[r["verdict"]] += 1
        arm = r.get("expected_harvester") or r.get("matched_harvester") or "unknown"
        bucket = by_harv.setdefault(arm, {"EXACT": 0, "PARA": 0, "LOST": 0, "n": 0})
        bucket[r["verdict"]] += 1
        bucket["n"] += 1
    total = len(results)
    retained = counts["EXACT"] + counts["PARA"]
    for arm, b in by_harv.items():
        b["retention_rate"] = round((b["EXACT"] + b["PARA"]) / b["n"], 3) if b["n"] else 0.0
    return {
        "total": total,
        "retained": retained,
        "retention_rate": round(retained / total, 3) if total else 0.0,
        "counts": counts,
        "by_harvester": by_harv,
        "per_probe": results,
        "para_threshold": PARA_THRESHOLD,
        "rubric": "automated CI proxy (EXACT/PARA/LOST); blind human|LLM rubric is the paper gold",
    }


def _load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: List[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: python score.py <brief.json> <probes.json>\n")
        return 2
    brief = _load(argv[1])
    probes_doc = _load(argv[2])
    probes = probes_doc["probes"] if isinstance(probes_doc, dict) else probes_doc
    report = score(brief, probes)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
