"""Plain data the engine plans over. Times are whole minutes after midnight of the service date."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

Loc = Tuple[float, float]  # (lat, lon)

# Block kinds in a pair's day.
DRIVE, VISIT, OFFICE, LAB, STANDBY = "drive", "visit", "office", "lab", "standby"


@dataclass(frozen=True)
class Job:
    """One order, ready to plan."""

    job_id: str
    published_min: int  # may be negative: published on an earlier day
    slot_min: int  # requested arrival; the pair may arrive within +/- tolerance
    loc: Loc
    duration_min: int  # planned on-site service time (access time is added by the engine)
    category: str
    iv_certified_only: bool
    needs_kits: bool  # needs IV kits that were not prepared in advance: an office stop after publishing
    lab_id: Optional[str] = None  # the lab a collected sample must reach
    sample_max_min: Optional[int] = None  # minutes allowed from collection to arriving at the lab


@dataclass(frozen=True)
class Lab:
    lab_id: str
    loc: Loc
    opens_min: int
    closes_min: int
    handover_min: int


@dataclass(frozen=True)
class Pair:
    """A nurse and a driver with a car, on duty for one shift that starts and ends at the office."""

    pair_id: str
    nurse_id: str
    driver_id: str
    car_id: str
    iv_certified: bool
    shift_start_min: int
    shift_end_min: int


@dataclass(frozen=True)
class Block:
    """One stretch of a pair's day. Consecutive blocks join up in place and time (waits are blocks)."""

    kind: str
    start: int
    end: int
    loc: Loc  # where it happens; for a drive, the destination
    from_loc: Optional[Loc] = None  # drive only
    km: float = 0.0  # drive only
    job_id: Optional[str] = None  # visit only
    service_start: Optional[int] = None  # visit only: arrival plus access time
    lab_id: Optional[str] = None  # lab only
    job_ids: Tuple[str, ...] = ()  # lab only: the samples handed over
    note: str = ""  # standby: where and why ('office', 'in place', 'lab opens', ...)


@dataclass
class PairDay:
    pair: Pair
    job_ids: List[str] = field(default_factory=list)  # visits, in the order they are served
    blocks: List[Block] = field(default_factory=list)

    @property
    def km(self) -> float:
        return sum(b.km for b in self.blocks)

    def minutes(self, kind: str) -> int:
        return sum(b.end - b.start for b in self.blocks if b.kind == kind)


@dataclass(frozen=True)
class Rejection:
    job_id: str
    reason: str  # no_certified_nurse / lab_unreachable / outside_shifts / no_capacity


@dataclass
class DayPlan:
    day: date
    pairs: Dict[str, PairDay]
    rejected: List[Rejection] = field(default_factory=list)

    @property
    def served(self) -> int:
        return sum(len(p.job_ids) for p in self.pairs.values())

    @property
    def km(self) -> float:
        return sum(p.km for p in self.pairs.values())
