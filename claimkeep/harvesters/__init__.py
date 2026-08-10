"""Built-in harvester registry."""

from __future__ import annotations

from typing import Dict, Type

from .atomic import AtomicFactHarvester
from .base import Harvester
from .calibration import CalibrationHarvester
from .lessons import LessonHarvester
from .regex_floor import RegexFloorHarvester
from .retraction import RetractionHarvester


REGISTRY: Dict[str, Type[Harvester]] = {
    AtomicFactHarvester.name: AtomicFactHarvester,
    CalibrationHarvester.name: CalibrationHarvester,
    RegexFloorHarvester.name: RegexFloorHarvester,
    LessonHarvester.name: LessonHarvester,
    RetractionHarvester.name: RetractionHarvester,
}


def get_harvester(name: str) -> Type[Harvester]:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError("unknown harvester: " + name) from exc


__all__ = [
    "Harvester",
    "AtomicFactHarvester",
    "CalibrationHarvester",
    "RegexFloorHarvester",
    "LessonHarvester",
    "RetractionHarvester",
    "REGISTRY",
    "get_harvester",
]
