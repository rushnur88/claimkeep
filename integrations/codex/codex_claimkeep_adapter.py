#!/usr/bin/env python3
"""codex_claimkeep_adapter — bridge `codex exec --json` output to ClaimKeep transcript units.

Stdlib-only (0 deps), like the ClaimKeep package it feeds.

VERIFIED against Codex CLI 0.145.0 (real exec run, 2026-07-22) and re-verified
unchanged on 0.147.0 (real exec run, 2026-08-13). Event stream
on stdout when invoked as `codex exec --json --skip-git-repo-check < /dev/null`:

    {"type":"thread.started","thread_id":"..."}
    {"type":"turn.started", ...}
    {"type":"item.completed","item":{"type":"agent_message","text":"<assistant answer>"}}
    {"type":"turn.completed","usage":{"input_tokens":N,"cached_input_tokens":M,"output_tokens":K}}

There is NO `response.output_text.delta` event — the assistant answer lives in
`item.completed` where `item.type == "agent_message"`, field `item.text`. Raw `codex exec`
WITHOUT `--json` emits a flat text log that is unusable here; always pass `--json`.

The bridge target is deliberately the SAME shape ClaimKeep's own `cli._read_transcript`
already consumes: one JSON object per line carrying a `text` field. So downstream we can run
the published `claimkeep precompact --transcript <file>` unchanged — no fork of the package.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, Iterator, List, Optional

AGENT_MESSAGE = "agent_message"


def iter_events(lines: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Yield decoded JSON objects, one per non-empty line. Tolerant: skips any line that
    is not a JSON object (e.g. stray stderr text that leaked into the stream).

    A whole stdout blob is accepted as well as a sequence of lines. `on_run_complete`
    takes the blob, so passing the same blob here is the natural thing to try — and
    iterating a str yields characters, none of which parse, so the run came back
    empty with no error at all. Silent zero instead of a complaint is the one
    failure this project refuses to ship.
    """
    if isinstance(lines, str):
        lines = lines.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _text_from_content(content: Any) -> Optional[str]:
    """Defensive fallback if a future build nests text under item.content instead of item.text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for it in content:
            if isinstance(it, str):
                parts.append(it)
            elif isinstance(it, dict) and isinstance(it.get("text"), str):
                parts.append(it["text"])
        if parts:
            return "\n".join(parts)
    return None


def iter_agent_messages(events: Iterable[Dict[str, Any]]) -> Iterator[str]:
    """Yield the assistant answer text from every agent_message item.completed event."""
    for ev in events:
        if ev.get("type") != "item.completed":
            continue
        item = ev.get("item")
        if not isinstance(item, dict) or item.get("type") != AGENT_MESSAGE:
            continue
        text = item.get("text")
        if not isinstance(text, str):
            text = _text_from_content(item.get("content"))
        if isinstance(text, str) and text.strip():
            yield text


def last_usage(events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the usage block of the LAST turn.completed event (input/cached/output tokens).
    input_tokens is the context size fed to the model on that turn — the signal the WRITE
    trigger uses as a compaction proxy (Codex has no PreCompact hook)."""
    usage: Optional[Dict[str, Any]] = None
    for ev in events:
        if ev.get("type") == "turn.completed":
            u = ev.get("usage")
            if isinstance(u, dict):
                usage = u
    return usage


def parse_run(lines: Iterable[str]) -> Dict[str, Any]:
    """Single-pass parse of one codex-exec run's JSONL stream.

    Returns: {units: [{"text":...}], usage: {...}, thread_id: str|None, events: int}
    `units` are ready to append verbatim to a ClaimKeep transcript file.
    """
    events = list(iter_events(lines))
    # State the author rather than relying on the reader's default. Roleless rows
    # are still accepted there for transcripts written by older builds, but a
    # producer that knows the answer should say it.
    units = [{"role": "assistant", "text": t} for t in iter_agent_messages(events)]
    usage = last_usage(events) or {}
    thread_id = next(
        (
            ev.get("thread_id")
            for ev in events
            if ev.get("type") == "thread.started" and ev.get("thread_id")
        ),
        None,
    )
    return {
        "units": units,
        "usage": usage,
        "thread_id": thread_id,
        "events": len(events),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="codex_claimkeep_adapter",
        description="Convert `codex exec --json` JSONL to ClaimKeep transcript units.",
    )
    ap.add_argument(
        "--in",
        dest="inp",
        default="-",
        help="codex --json JSONL file, or - for stdin (default)",
    )
    ap.add_argument(
        "--usage",
        action="store_true",
        help="also print the final usage block as JSON to stderr",
    )
    args = ap.parse_args(argv)

    if args.inp == "-":
        res = parse_run(sys.stdin)
    else:
        with open(args.inp, "r", encoding="utf-8") as fh:
            res = parse_run(fh)

    for unit in res["units"]:
        sys.stdout.write(json.dumps(unit, ensure_ascii=False) + "\n")
    if args.usage:
        sys.stderr.write(json.dumps(res["usage"], ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
