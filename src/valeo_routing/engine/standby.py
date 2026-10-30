"""Where a pair waits when it has more time than the next visit needs.

A policy proposes a spot for an idle gap; the schedule builder uses it only if the detour still gets
the pair to the next visit on time. Hubs (PLAN step 6) are another policy behind the same interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, Tuple

from .distance import DistanceModel
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


class HubStandby:
    """Logistics Valeo with hubs: wait at the standby spot, a hub or the office, that adds the least
    driving between the two visits. Ties go to the office, then to the hub listed first."""

    def __init__(self, office: Loc, hubs: Sequence[Tuple[str, Loc]], dist: DistanceModel):
        self.spots = [Spot(office, "office")] + [Spot(loc, "hub " + name) for name, loc in hubs]
        self.dist = dist

    def spot(self, from_loc: Loc, to_loc: Loc) -> Optional[Spot]:
        return min(self.spots, key=lambda s: self.dist.km(from_loc, s.loc) + self.dist.km(s.loc, to_loc))
