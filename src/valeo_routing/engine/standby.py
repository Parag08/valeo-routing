"""Where a pair waits when it has more time than the next visit needs.

A policy proposes a spot for an idle gap; the schedule builder uses it only if the detour still gets
the pair to the next visit on time. Hubs (PLAN step 6) are another policy behind the same interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from .model import Loc


@dataclass(frozen=True)
class Spot:
    loc: Loc
    note: str  # 'office', 'hub', ...


class StandbyPolicy(Protocol):
    def spot(self, from_loc: Loc, to_loc: Loc) -> Optional[Spot]: ...


class OfficeStandby:
    """The Excel era: between visits, pairs go back to the office and wait there."""

    def __init__(self, office: Loc):
        self.office = office

    def spot(self, from_loc: Loc, to_loc: Loc) -> Optional[Spot]:
        return Spot(self.office, "office")


class StayStandby:
    """Wait wherever the pair is: the no-detour lower bound."""

    def spot(self, from_loc: Loc, to_loc: Loc) -> Optional[Spot]:
        return None
