#!/usr/bin/env python3
"""codex_claimkeep_write — WRITE trigger for a Codex-brained agent.

Codex has NO PreCompact hook (that is Claude-Code-specific). So we approximate the
"snapshot before context compacts" moment two ways, both driven by a completed `codex exec`
run:
  1. APPEND every completed run's assistant answer to a rolling ClaimKeep transcript.
  2. HARVEST a fresh brief (via the published `claimkeep precompact`) when the context size
     — `turn.completed.usage.input_tokens`, reported natively by Codex — crosses a threshold
     (default 250_000). After a harvest we rotate the rolling transcript so the next thread
     starts clean and we never re-harvest the same span.

Wire this in at the point in the gateway launcher where `codex exec --json` returns, feeding
it the run's stdout. Importable API (preferred, from codex_tg_gateway.py):

    from codex_claimkeep_write import on_run_complete
    info = on_run_complete(codex_stdout_text,
                           transcript_path="~/.aria/claimkeep/codex/transcript.jsonl",
                           brief_dir="~/.aria/claimkeep/briefs")
    # info -> {units_appended, input_tokens, threshold, harvested, brief_path, thread_id}

CLI (shell wiring — pipe the codex stdout in):
    codex exec --json ... | python3 codex_claimkeep_write.py \
        --transcript ~/.aria/claimkeep/codex/transcript.jsonl \
        --brief-dir  ~/.aria/claimkeep/briefs

Env:
  CLAIMKEEP_CODEX_TOKEN_THRESHOLD  override the 250k harvest threshold
  CLAIMKEEP_HOME                   path to the claimkeep repo/checkout; prepended to
                                   PYTHONPATH for the `-m claimkeep` subprocess when the
                                   package is not pip-installed (unused if it is).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Union

from codex_claimkeep_adapter import parse_run

DEFAULT_THRESHOLD = int(os.environ.get("CLAIMKEEP_CODEX_TOKEN_THRESHOLD", "250000"))


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _claimkeep_env() -> Dict[str, str]:
    env = dict(os.environ)
    home = os.environ.get("CLAIMKEEP_HOME")
    if home:
        home = _expand(home)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = home + (os.pathsep + existing if existing else "")
    return env


def _append_units(transcript_path: str, units: List[Dict[str, Any]]) -> int:
    transcript_path = _expand(transcript_path)
    parent = os.path.dirname(transcript_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(transcript_path, "a", encoding="utf-8") as fh:
        for unit in units:
            fh.write(json.dumps(unit, ensure_ascii=False) + "\n")
    return len(units)


def _stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harvest(transcript_path: str, brief_dir: str) -> Dict[str, Any]:
    transcript_path = _expand(transcript_path)
    brief_dir = _expand(brief_dir)
    os.makedirs(brief_dir, exist_ok=True)
    out = os.path.join(brief_dir, f"{_stamp()}-codex.json")
    proc = subprocess.run(
        [sys.executable, "-m", "claimkeep", "precompact",
         "--transcript", transcript_path, "--out", out],
        capture_output=True, text=True, env=_claimkeep_env(),
    )
    return {"ok": proc.returncode == 0, "brief_path": out if proc.returncode == 0 else None,
            "returncode": proc.returncode, "stderr": proc.stderr.strip()}


def _rotate(transcript_path: str) -> Optional[str]:
    """Archive the harvested transcript and start a fresh one, so the next thread is clean."""
    transcript_path = _expand(transcript_path)
    if not os.path.exists(transcript_path):
        return None
    archive = f"{transcript_path}.{_stamp()}.harvested"
    os.replace(transcript_path, archive)
    return archive


def on_run_complete(
    codex_stdout: Union[str, Iterable[str]],
    transcript_path: str,
    brief_dir: str,
    threshold: int = DEFAULT_THRESHOLD,
    force_harvest: bool = False,
    rotate: bool = True,
) -> Dict[str, Any]:
    lines = codex_stdout.splitlines() if isinstance(codex_stdout, str) else codex_stdout
    res = parse_run(lines)
    appended = _append_units(transcript_path, res["units"])

    input_tokens = res["usage"].get("input_tokens")
    crossed = isinstance(input_tokens, int) and input_tokens >= threshold
    harvested = False
    brief_path: Optional[str] = None
    archived: Optional[str] = None
    harvest_err: Optional[str] = None

    if force_harvest or crossed:
        h = _harvest(transcript_path, brief_dir)
        harvested = h["ok"]
        brief_path = h["brief_path"]
        harvest_err = None if h["ok"] else h["stderr"]
        if harvested and rotate:
            archived = _rotate(transcript_path)

    return {
        "units_appended": appended,
        "input_tokens": input_tokens,
        "threshold": threshold,
        "crossed_threshold": crossed,
        "harvested": harvested,
        "brief_path": brief_path,
        "archived_transcript": archived,
        "harvest_error": harvest_err,
        "thread_id": res["thread_id"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="codex_claimkeep_write",
        description="Append a completed codex run to the rolling transcript; harvest a brief at threshold.",
    )
    ap.add_argument("--transcript", required=True, help="rolling ClaimKeep transcript JSONL path")
    ap.add_argument("--brief-dir", required=True, help="directory to write harvested briefs into")
    ap.add_argument("--codex-json", default="-", help="codex --json stdout file, or - for stdin")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    ap.add_argument("--force-harvest", action="store_true", help="harvest regardless of token count")
    ap.add_argument("--no-rotate", action="store_true", help="do not rotate transcript after harvest")
    args = ap.parse_args(argv)

    if args.codex_json == "-":
        codex_stdout = sys.stdin.read()
    else:
        with open(args.codex_json, "r", encoding="utf-8") as fh:
            codex_stdout = fh.read()

    info = on_run_complete(
        codex_stdout,
        transcript_path=args.transcript,
        brief_dir=args.brief_dir,
        threshold=args.threshold,
        force_harvest=args.force_harvest,
        rotate=not args.no_rotate,
    )
    sys.stdout.write(json.dumps(info, ensure_ascii=False) + "\n")
    return 0 if info.get("harvest_error") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
