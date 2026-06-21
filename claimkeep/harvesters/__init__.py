"""Built-in harvester registry."""

from __future__ import annotations

from typing import Dict, Type

from .base import Harvester
from .calibration import CalibrationHarvester
from .regex_floor import RegexFloorHarvester


REGISTRY: Dict[str, Type[Harvester]] = {
    CalibrationHarvester.name: CalibrationHarvester,
    RegexFloorHarvester.name: RegexFloorHarvester,
}


def get_harvester(name: str) -> Type[Harvester]:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError("unknown harvester: " + name) from exc


__all__ = ["Harvester", "CalibrationHarvester", "RegexFloorHarvester", "REGISTRY", "get_harvester"]
