"""Command line interface for ClaimKeep."""

from __future__ import annotations

import argparse
import datetime as _datetime
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .brief import Brief, Claim, Supplement
from .config import default_config
from .harvesters import get_harvester
from .harvesters.lessons import LessonHarvester
from .harvesters.retraction import refutes
from .lessons import Lesson, LessonStore
from .prompt import marker_instruction
from .redact import redact
from .rehydrate import postcompact_payload
from .retrieve import recall
from .select import apply_budget
from .stats import collect as collect_stats
from .stats import render as render_stats
from .storage import append_private, private_dir, write_private


def _now_iso() -> str:
    return (
        _datetime.datetime.now(_datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# Row kinds that name an author. Anything else in `type` is a row kind, not a
# speaker, and must not be read as one.
_AUTHORS = frozenset({"assistant", "user", "human", "system", "tool", "function"})


def _extract_text(obj: Dict[str, Any]) -> Optional[str]:
    for key in ("text", "content"):
        value = obj.get(key)
        if isinstance(value, str):
            return value
    message = obj.get("message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts)
    return None


def _warn(what: str, exc: BaseException = None) -> None:
    """Report a swallowed failure on stderr.

    Every failure here is caught so the hook can exit 0 — compaction must never
    be blocked by a memory layer. Staying silent about it, though, makes a broken
    install indistinguishable from a working one that had nothing to say, which
    is the one thing this package refuses to do anywhere else.
    """
    detail = f": {type(exc).__name__}: {exc}" if exc is not None else ""
    print(f"claimkeep: {what}{detail}", file=sys.stderr)


def _author(obj: Dict[str, Any]) -> Optional[str]:
    """Who wrote this row, if it says. `None` means the format carries no author."""
    message = obj.get("message")
    if isinstance(message, dict) and isinstance(message.get("role"), str):
        return message["role"].lower()
    for key in ("role", "type"):
        value = obj.get(key)
        # `type` doubles as a row kind ("progress", "tool_use"); only treat it as
        # an author when it actually names one.
        if isinstance(value, str) and value.lower() in _AUTHORS:
            return value.lower()
    return None


def _role_of(obj: Dict[str, Any]) -> str:
    """Normalised author of a row. Rows that state no author are the agent's.

    A brief is meant to be what the agent established, and the reader used to
    take any row carrying text: user turns, pasted documents, tool results and
    injected system blocks all became claims attributed to the agent. On real
    transcripts the rows carrying `[C:NN%]` split 1318 user to 584 assistant —
    most "agent claims" had another author. In that deployment the user rows were
    an injected system prompt whose instructions demonstrate the marker syntax,
    so the plugin was harvesting "write [C:XX%]" as an established fact.

    Dropping those rows at the door fixed the attribution and broke something
    else: `retraction` is documented to keep corrections "from the agent and
    from anyone else", and it never saw them again. Memory that keeps the
    corrected value and throws away the correction is worse than memory that
    keeps neither. So the role travels with the text and each harvester decides
    what it is entitled to; see `_units_for`.

    Rows with no stated author are the agent's: that is what the Codex bridge
    writes (`{"text": ...}`), already filtered to assistant answers upstream.
    """
    author = _author(obj)
    return author or "assistant"


#: Roles whose text may correct the agent, but may never become its own claim.
_CORRECTION_ROLES = frozenset({"user", "human"})
#: Harvesters entitled to read corrections addressed to the agent.
_CORRECTION_AWARE = frozenset({"retraction"})


def _units_for(harvester: str, units: Sequence[Tuple[str, str]]) -> List:
    """The slice of the transcript one harvester is allowed to see.

    `retraction` gets the agent's text plus corrections, in original order and
    with roles attached, because "you were wrong" only means anything next to
    the thing it overturns. Everything else gets the agent's own words as plain
    strings — unchanged interface, and no way for another author's sentence to
    be stored as a fact the agent established. System and tool rows are claims
    for nobody and never appear here.
    """
    if harvester in _CORRECTION_AWARE:
        return [
            (role, text)
            for role, text in units
            if role == "assistant" or role in _CORRECTION_ROLES
        ]
    return [text for role, text in units if role == "assistant"]


def _read_transcript(path: str) -> List[Tuple[str, str]]:
    """Return `(role, text)` per usable row, newest last, roles normalised."""
    units: List[Tuple[str, str]] = []
    skipped = 0
    total = 0
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(obj, dict):
                skipped += 1
                continue
            text = _extract_text(obj)
            if text:
                units.append((_role_of(obj), text))
    if units and not any(role == "assistant" for role, _ in units):
        _warn(f"no assistant rows in {path} ({len(units)} rows by another author)")
    # One line, not one per row: a transcript can legitimately hold a few
    # unparsable rows, but a whole file of them means the wrong path was wired.
    if skipped and skipped == total:
        _warn(f"no usable rows in {path} ({total} unparsable)")
    elif skipped:
        _warn(f"skipped {skipped} of {total} unparsable rows in {path}")
    return units


def _read_hook_stdin() -> Dict[str, Any]:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        _warn("hook stdin was not a JSON object; ignoring it")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        _warn("could not read hook payload from stdin", exc)
        return {}


def _newest_brief(brief_dir: str) -> Optional[str]:
    paths = glob.glob(os.path.join(brief_dir, "*.json"))
    if not paths:
        return None
    return max(paths, key=os.path.getmtime)


def _carry_lessons(
    claims: List[Claim], config: Any, created_utc: str, source: Dict[str, Any]
) -> List[Claim]:
    """Persist lessons found this session, then carry the store's newest forward.

    Lessons are the one thing that must not be scoped to a single brief: a rule
    learned on Monday is worthless if it is gone by Friday. Everything else in
    the brief describes this session; lessons describe how to work in the next.
    Failure here is never fatal — a broken store must not cost the whole brief.
    """
    if not getattr(config, "lessons_enabled", True):
        return claims
    prefix = LessonHarvester.TOPIC + ":"
    fresh = [claim for claim in claims if claim.topic.startswith(prefix)]
    try:
        store = LessonStore(config.expanded_lessons_path())
        store.append(
            [
                Lesson(text=claim.text, ts=created_utc, session=source.get("session"))
                for claim in fresh
            ]
        )
        carried = store.recent(int(getattr(config, "lessons_in_brief", 0) or 0))
    except OSError as exc:
        _warn("lesson store unavailable; carrying no lessons forward", exc)
        return claims

    known = {claim.text.casefold() for claim in fresh}
    for lesson in carried:
        if lesson.text.casefold() in known:
            continue
        known.add(lesson.text.casefold())
        claims.append(
            Claim(
                text=lesson.text,
                confidence=None,
                topic=prefix + lesson.text.casefold()[:40],
                source_harvester=LessonHarvester.name,
                ts=lesson.ts,
            )
        )
    return claims


def _link_retractions(claims: List[Claim]) -> List[Claim]:
    """Mark every claim a retraction overturns, so both never read as live.

    `refutes()` has been in the retraction harvester from the start and was
    never called, so a brief could carry "the port is 3333" at 0.90 next to
    "correction: the port is 4444" with both rendered under Claims. After
    compaction the agent restates whichever it reads first and repeats something
    the transcript already overturned — the failure the harvester exists to
    prevent, reintroduced one layer up.

    Every match is linked, not just the first: one fact usually reaches the brief
    in more than one wording — `atomic` and `calibration` both harvest the
    sentence that states it — and leaving the second copy live would put the
    refuted value back in front of the agent through the other door.
    """
    retractions = [c for c in claims if c.source_harvester == "retraction"]
    if not retractions:
        return claims
    for retraction in retractions:
        for claim in claims:
            if claim is retraction or claim.source_harvester == "retraction":
                continue
            if claim.superseded_by or not claim.is_active:
                continue
            if refutes(retraction.text, claim.text):
                claim.superseded_by = retraction.id
                if retraction.supersedes is None:
                    retraction.supersedes = claim.id
    return claims


def _build_brief(
    transcript: List[str], created_utc: str, source: Dict[str, Any]
) -> Brief:
    config = default_config()
    # Accept both shapes: (role, text) pairs from `_read_transcript`, and plain
    # strings, which every caller passed before roles existed and which mean
    # "the agent said this".
    units: List[Tuple[str, str]] = [
        (str(u[0]), str(u[1]))
        if isinstance(u, (tuple, list)) and len(u) == 2
        else ("assistant", str(u))
        for u in transcript
    ]
    if getattr(config, "redact", True):
        units = [(role, redact(text)) for role, text in units]
    claims: List[Claim] = []
    supplements: List[Supplement] = []
    # harvest_enabled=False yields an empty (naive) brief — the control arm for
    # a control-vs-treatment evaluation.
    if getattr(config, "harvest_enabled", True):
        for name in config.harvesters:
            harvester = get_harvester(name)()
            for item in harvester.harvest(_units_for(name, units), config):
                if isinstance(item, Claim):
                    claims.append(item)
                elif isinstance(item, Supplement):
                    supplements.append(item)
        claims = _link_retractions(claims)
        claims = _carry_lessons(claims, config, created_utc, source)
    brief = Brief(
        created_utc=created_utc, source=source, claims=claims, supplement=supplements
    )
    # Bound the brief before it is written. Without this the brief is the whole
    # harvest and cannot be re-injected into the window it is meant to restore.
    return apply_budget(brief, int(getattr(config, "budget_chars", 0) or 0))


def _probe_log(brief: Brief, source: Dict[str, Any], created_utc: str) -> None:
    """Append one JSONL record per PreCompact when CLAIMKEEP_PROBE_LOG is set.

    Records the full reinjected brief, the harvest_enabled flag, and a
    session/corpus/timestamp header so control and treatment runs over the same
    corpus produce machine-distinguishable artifacts. Best-effort; never raises.
    """
    path = os.environ.get("CLAIMKEEP_PROBE_LOG")
    if not path:
        return
    try:
        record = {
            "ts": created_utc,
            "session_id": source.get("session"),
            "corpus_id": os.environ.get("CLAIMKEEP_CORPUS_ID"),
            "harvest_enabled": bool(getattr(default_config(), "harvest_enabled", True)),
            "brief": brief.to_dict(),
        }
        append_private(path, json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        _warn("probe log not written", exc)
        return


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_markers(_args: argparse.Namespace) -> int:
    """Print the confidence-marker instruction for an agent's system prompt.

    The calibration harvester is only as good as the markers it finds, so the
    plugin ships the convention instead of assuming it.
    """
    print(marker_instruction())
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    """Report what the layer actually did, counted from the stored briefs."""
    report = collect_stats(default_config())
    print(
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else render_stats(report),
        end="",
    )
    return 0


def _cmd_recall(args: argparse.Namespace) -> int:
    """Search every stored brief and lesson, not just the most recent one."""
    config = default_config()
    rows = recall(args.query, config, limit=args.limit, budget_chars=args.budget)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "text": row["doc"].text,
                        "kind": row["doc"].kind,
                        "id": row["doc"].id,
                        "ts": row["doc"].ts,
                        "superseded": row["doc"].superseded,
                        "score": row["score"],
                        "bm25": row["bm25"],
                        "source": row["doc"].source,
                    }
                    for row in rows
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not rows:
        print("no match")
        return 0
    for row in rows:
        doc = row["doc"]
        flag = " [superseded]" if doc.superseded else ""
        print(f"- ({doc.kind}, {row['score']}){flag} {doc.text}")
    return 0


def _cmd_lessons(args: argparse.Namespace) -> int:
    config = default_config()
    store = LessonStore(config.expanded_lessons_path())
    if args.add:
        written = store.append([Lesson(text=args.add, ts=_now_iso())])
        print("stored" if written else "already stored")
        return 0
    lessons = store.recent(args.limit)
    if args.json:
        print(
            json.dumps(
                [lesson.to_dict() for lesson in lessons], ensure_ascii=False, indent=2
            )
        )
        return 0
    if not lessons:
        print("no lessons stored yet")
        return 0
    for lesson in lessons:
        stamp = lesson.ts or "unknown time"
        print(f"- [{stamp}] {lesson.text}")
    return 0


def _cmd_precompact(args: argparse.Namespace) -> int:
    try:
        hook = {} if args.transcript else _read_hook_stdin()
        transcript_path = args.transcript or hook.get("transcript_path")
        if not transcript_path:
            return 0
        transcript = _read_transcript(str(transcript_path))
        created_utc = args.now or _now_iso()
        source = {
            "agent": str(hook.get("agent", "claude-code")),
            "session": hook.get("session_id")
            or hook.get("sessionId")
            or hook.get("session"),
        }
        brief = _build_brief(transcript, created_utc, source)
        out = args.out
        if not out:
            config = default_config()
            brief_dir = config.expanded_brief_dir()
            private_dir(brief_dir)
            stamp = created_utc.replace(":", "").replace("-", "")
            session = source.get("session") or "session"
            out = os.path.join(brief_dir, f"{stamp}-{session}.json")
        else:
            private_dir(os.path.dirname(os.path.abspath(out)))
        write_private(out, brief.to_json())
        _probe_log(brief, source, created_utc)
        print(out)
        return 0
    except Exception as exc:
        _warn("precompact failed; no brief was written", exc)
        return 0


def _cmd_postcompact(args: argparse.Namespace) -> int:
    try:
        brief_path = args.brief
        if not brief_path:
            brief_path = _newest_brief(default_config().expanded_brief_dir())
        if not brief_path:
            return 0
        with open(brief_path, "r", encoding="utf-8") as handle:
            brief = Brief.from_json(handle.read())
        budget = int(getattr(default_config(), "budget_chars", 0) or 0)
        payload = postcompact_payload(brief, args.event, budget)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        _warn("postcompact failed; nothing was re-injected", exc)
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimkeep")
    sub = parser.add_subparsers(dest="command", required=True)

    version = sub.add_parser("version")
    version.set_defaults(func=_cmd_version)

    markers = sub.add_parser("markers", help="print the confidence-marker instruction")
    markers.set_defaults(func=_cmd_markers)

    stats_cmd = sub.add_parser(
        "stats", help="report what the layer did across every stored brief"
    )
    stats_cmd.add_argument("--json", action="store_true")
    stats_cmd.set_defaults(func=_cmd_stats)

    recall_cmd = sub.add_parser("recall", help="search every stored brief and lesson")
    recall_cmd.add_argument("query")
    recall_cmd.add_argument("--limit", type=int, default=10)
    recall_cmd.add_argument(
        "--budget", type=int, default=0, help="cap the result set in characters"
    )
    recall_cmd.add_argument("--json", action="store_true")
    recall_cmd.set_defaults(func=_cmd_recall)

    lessons = sub.add_parser("lessons", help="list or add durable lessons")
    lessons.add_argument("--limit", type=int, default=20)
    lessons.add_argument("--add", help="store a lesson verbatim")
    lessons.add_argument("--json", action="store_true")
    lessons.set_defaults(func=_cmd_lessons)

    precompact = sub.add_parser("precompact")
    precompact.add_argument("--transcript")
    precompact.add_argument("--out")
    precompact.add_argument("--now")
    precompact.set_defaults(func=_cmd_precompact)

    postcompact = sub.add_parser("postcompact")
    postcompact.add_argument("--brief")
    postcompact.add_argument(
        "--event", choices=("SessionStart", "PostCompact"), default="SessionStart"
    )
    postcompact.set_defaults(func=_cmd_postcompact)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
