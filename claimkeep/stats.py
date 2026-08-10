"""What the memory layer actually did, counted from the briefs it wrote.

Why this exists
---------------
Every other part of this package answers "what do I remember?". This one
answers "is the thing working, and how well?" — a question you cannot settle
by reading a single brief, because a single brief looks fine even when the
layer has been silently degrading for a week.

Everything here is derived from files already on disk. Nothing new is
collected and nothing is inferred: if a number cannot be computed from a
stored brief it is absent rather than estimated.

Two counts deserve their names spelled out, because they are the ones that
tell you whether the layer is earning its keep:

- ``retractions`` — claims that overturn an earlier statement. This is the
  single most valuable line in a brief: a memory layer that keeps a refuted
  claim and drops its refutation is worse than no memory at all.
- ``marked`` — claims the agent had already tagged with a confidence marker.
  A falling share means the marker convention is eroding, and the calibration
  half of the package quietly stops having anything to read.
"""

from __future__ import annotations

import glob
import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional

from .config import Config
from .lessons import LessonStore


def _load_briefs(brief_dir: str) -> List[Dict[str, Any]]:
    """Every stored brief, oldest first. Unreadable files are skipped, not fatal.

    A corrupt brief must not make the whole report unavailable — the point of
    the report is to survive exactly the kind of day that produces one.
    """
    out: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(brief_dir, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        if isinstance(data, dict):
            data["_path"] = path
            out.append(data)
    return out


def collect(config: Config) -> Dict[str, Any]:
    """Compute the report. Pure read; never writes."""
    briefs = _load_briefs(config.expanded_brief_dir())

    claims: List[Dict[str, Any]] = []
    supplement_kinds: Counter = Counter()
    for brief in briefs:
        for claim in brief.get("claims", []):
            if isinstance(claim, dict):
                claims.append(claim)
        for item in brief.get("supplement", []):
            if isinstance(item, dict):
                supplement_kinds[item.get("kind", "?")] += 1

    harvesters: Counter = Counter()
    topics: Counter = Counter()
    marked: List[float] = []
    retractions = 0
    superseded = 0
    for claim in claims:
        harvester = str(claim.get("source_harvester", "?"))
        harvesters[harvester] += 1
        topic = str(claim.get("topic", ""))
        topics[topic] += 1
        # Two signals, because either alone can be absent: the retraction
        # harvester labels its own output, and the topic carries the label
        # through a round-trip that drops harvester names.
        if topic.startswith("retraction") or harvester == "retraction":
            retractions += 1
        if claim.get("superseded_by"):
            superseded += 1
        confidence = claim.get("confidence")
        if isinstance(confidence, (int, float)):
            marked.append(float(confidence))

    # A brief can come from a foreign collector (this project grew out of one).
    # Its claims are real, but they carry no harvester labels, so the counts
    # above that depend on labels — retractions above all — read as zero. That
    # zero means "not labelled here", not "did not happen", and the report has
    # to say so rather than let the reader guess.
    known = {"retraction", "atomic", "calibration", "regex_floor", "lessons"}
    labelled = sum(1 for c in claims if str(c.get("source_harvester", "")) in known)

    stamps = sorted(str(b.get("created_utc", "")) for b in briefs if b.get("created_utc"))
    chars = sum(len(str(c.get("text", ""))) for c in claims)

    lessons_total: Optional[int] = None
    if config.lessons_enabled:
        try:
            lessons_total = len(LessonStore(config.expanded_lessons_path()).load())
        except Exception:
            lessons_total = None

    return {
        "brief_dir": config.expanded_brief_dir(),
        "briefs": len(briefs),
        "first_brief_utc": stamps[0] if stamps else None,
        "last_brief_utc": stamps[-1] if stamps else None,
        "claims_total": len(claims),
        "claims_per_brief": round(len(claims) / len(briefs), 1) if briefs else 0.0,
        "claim_chars_total": chars,
        "retractions": retractions,
        "superseded": superseded,
        "labelled_claims": labelled,
        "marked_claims": len(marked),
        "marked_share": round(len(marked) / len(claims), 3) if claims else 0.0,
        "mean_confidence": round(sum(marked) / len(marked), 3) if marked else None,
        "by_harvester": dict(harvesters.most_common()),
        "supplement_by_kind": dict(supplement_kinds.most_common()),
        "top_topics": dict(topics.most_common(10)),
        "lessons_total": lessons_total,
    }


def render(report: Dict[str, Any]) -> str:
    """Human-readable form. Absent numbers stay absent — no zeros standing in
    for "not measured", because that is the confusion this package exists to
    prevent."""
    lines: List[str] = ["# ClaimKeep stats", ""]

    if not report["briefs"]:
        lines.append(f"No briefs stored yet in {report['brief_dir']}.")
        lines.append("Nothing has been compacted since the plugin was installed,")
        lines.append("or the hooks are not wired. Both look identical from here.")
        return "\n".join(lines) + "\n"

    lines.append(f"Briefs stored: {report['briefs']}")
    lines.append(f"Period: {report['first_brief_utc']} .. {report['last_brief_utc']}")
    lines.append("")
    lines.append(f"Claims kept: {report['claims_total']} ({report['claims_per_brief']} per brief)")
    if report["labelled_claims"]:
        lines.append(f"Retractions: {report['retractions']}")
    else:
        lines.append("Retractions: not measurable — no claim carries a harvester")
        lines.append("  label, so these briefs were written by a different collector.")
    lines.append(f"Superseded: {report['superseded']}")

    share = int(round(report["marked_share"] * 100))
    line = f"Confidence-marked: {report['marked_claims']} ({share}%)"
    if report["mean_confidence"] is not None:
        line += f", mean {report['mean_confidence']}"
    lines.append(line)

    if report["lessons_total"] is not None:
        lines.append(f"Lessons carried forward: {report['lessons_total']}")

    if report["by_harvester"]:
        lines.append("")
        lines.append("By harvester:")
        for name, count in report["by_harvester"].items():
            lines.append(f"  {name}: {count}")

    if report["supplement_by_kind"]:
        lines.append("")
        lines.append("Supplement:")
        for kind, count in report["supplement_by_kind"].items():
            lines.append(f"  {kind}: {count}")

    if report["top_topics"]:
        lines.append("")
        lines.append("Top topics:")
        for topic, count in report["top_topics"].items():
            label = topic or "(none)"
            if len(label) > 48:
                label = label[:45] + "..."
            lines.append(f"  {label}: {count}")

    return "\n".join(lines) + "\n"
