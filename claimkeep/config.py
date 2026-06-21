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
    calibration_marker_regex: str = r"\[C:\s*(\d{1,3})\s*%\]"
    floor_paths: bool = True
    floor_ids: bool = True
    floor_decisions: bool = True
    redact: bool = True
    brief_dir: str = DEFAULT_BRIEF_DIR

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
        return cfg

    def expanded_brief_dir(self) -> str:
        return os.path.abspath(os.path.expanduser(self.brief_dir))


def default_config() -> Config:
    return Config.from_env()
