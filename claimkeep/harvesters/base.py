"""Harvester extension point."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Sequence, Union

from ..brief import Claim, Supplement
from ..config import Config


Harvested = Union[Claim, Supplement]


class Harvester(ABC):
    name: str

    @abstractmethod
    def harvest(self, transcript: Sequence[str], config: Config) -> List[Harvested]:
        raise NotImplementedError
