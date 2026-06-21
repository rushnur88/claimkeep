"""Command line interface for ClaimKeep."""

from __future__ import annotations

import argparse
import datetime as _datetime
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import __version__
from .brief import Brief, Claim, Supplement
from .config import default_config
from .harvesters import get_harvester
from .redact import redact
from .rehydrate import postcompact_payload


def _now_iso() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _read_transcript(path: str) -> List[str]:
    units: List[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            text = _extract_text(obj)
            if text:
                units.append(text)
    return units


def _read_hook_stdin() -> Dict[str, Any]:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _newest_brief(brief_dir: str) -> Optional[str]:
    paths = glob.glob(os.path.join(brief_dir, "*.json"))
    if not paths:
        return None
    return max(paths, key=os.path.getmtime)


def _build_brief(transcript: List[str], created_utc: str, source: Dict[str, Any]) -> Brief:
    config = default_config()
    if getattr(config, "redact", True):
        transcript = [redact(unit) for unit in transcript]
    claims: List[Claim] = []
    supplements: List[Supplement] = []
    # harvest_enabled=False yields an empty (naive) brief — the control arm for
    # a control-vs-treatment evaluation.
    if getattr(config, "harvest_enabled", True):
        for name in config.harvesters:
            harvester = get_harvester(name)()
            for item in harvester.harvest(transcript, config):
                if isinstance(item, Claim):
                    claims.append(item)
                elif isinstance(item, Supplement):
                    supplements.append(item)
    return Brief(created_utc=created_utc, source=source, claims=claims, supplement=supplements)


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
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
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
            "session": hook.get("session_id") or hook.get("sessionId") or hook.get("session"),
        }
        brief = _build_brief(transcript, created_utc, source)
        out = args.out
        if not out:
            config = default_config()
            brief_dir = config.expanded_brief_dir()
            os.makedirs(brief_dir, exist_ok=True)
            stamp = created_utc.replace(":", "").replace("-", "")
            session = source.get("session") or "session"
            out = os.path.join(brief_dir, f"{stamp}-{session}.json")
        else:
            parent = os.path.dirname(os.path.abspath(out))
            if parent:
                os.makedirs(parent, exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(brief.to_json())
        _probe_log(brief, source, created_utc)
        print(out)
        return 0
    except Exception:
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
        print(json.dumps(postcompact_payload(brief, args.event), ensure_ascii=False))
        return 0
    except Exception:
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimkeep")
    sub = parser.add_subparsers(dest="command", required=True)

    version = sub.add_parser("version")
    version.set_defaults(func=_cmd_version)

    precompact = sub.add_parser("precompact")
    precompact.add_argument("--transcript")
    precompact.add_argument("--out")
    precompact.add_argument("--now")
    precompact.set_defaults(func=_cmd_precompact)

    postcompact = sub.add_parser("postcompact")
    postcompact.add_argument("--brief")
    postcompact.add_argument("--event", choices=("SessionStart", "PostCompact"), default="SessionStart")
    postcompact.set_defaults(func=_cmd_postcompact)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
