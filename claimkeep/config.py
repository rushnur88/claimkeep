"""Configuration for ClaimKeep harvesters and storage."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List


DEFAULT_BRIEF_DIR = "~/.claude/plugins/data/claimkeep/briefs"


@dataclass
class Config:
    harvesters: List[str] = field(default_factory=lambda: ["calibration", "regex_floor"])
    # Accepts both the bare marker `[C:80%]` and the extended form that carries
    # an evidence pointer, `[C:80%, basis: read the file]`. The extended form is
    # what long-running agents actually emit; a regex that only matched the bare
    # form silently harvested zero claims from real transcripts.
    calibration_marker_regex: str = r"\[C:\s*(\d{1,3})\s*%[^\]]*\]"
    floor_paths: bool = True
    floor_ids: bool = True
    floor_decisions: bool = True
    redact: bool = True
    harvest_enabled: bool = True
    brief_dir: str = DEFAULT_BRIEF_DIR
    # Character budget for the assembled brief. The brief is re-injected into
    # the context window the compaction just freed, so it must be bounded or it
    # defeats its own purpose. 0 disables the cap (raw harvest, evaluation only).
    # 12000 chars is roughly the size of a native compaction summary.
    budget_chars: int = 12000

    @classmethod
    def from_file(cls, path: str) -> "Config":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        cfg = cls()
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls()
        if os.environ.get("CLAIMKEEP_BRIEF_DIR"):
            cfg.brief_dir = os.environ["CLAIMKEEP_BRIEF_DIR"]
        harvest = os.environ.get("CLAIMKEEP_HARVEST")
        if harvest is not None and harvest.strip().lower() in ("0", "false", "off", "no"):
            cfg.harvest_enabled = False
        budget = os.environ.get("CLAIMKEEP_BUDGET_CHARS")
        if budget is not None:
            try:
                cfg.budget_chars = max(0, int(budget.strip()))
            except ValueError:
                pass
        return cfg

    def expanded_brief_dir(self) -> str:
        return os.path.abspath(os.path.expanduser(self.brief_dir))


def default_config() -> Config:
    return Config.from_env()
