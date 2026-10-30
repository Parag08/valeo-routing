"""Lay out one pair's day for a fixed sequence of visits.

Everything is decided earliest-first, so the first part of a day never depends on visits that come
later, except one thing: a pair goes to the lab early when carrying a sample that would otherwise
miss its deadline after the next visit. That one-visit lookahead is the only non-causal step.

A day starts and ends at the office. Between visits the pair waits (at the office or in place, per the
standby policy), collects IV kits when an order needs them and the pair has not been at the office since
`kit_stop_min` after the order was published, and drops samples at their lab. It fails with a reason code when a visit cannot be made:

    window_missed    cannot arrive within the tolerance of the requested slot
    shift_ended      a visit or lab drop would run past the end of the shift
    sample_deadline  a sample cannot reach its lab in time
    lab_closed       the lab is closed when the sample could arrive
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .distance import DistanceModel
from .model import DRIVE, LAB, OFFICE, STANDBY, VISIT, Block, Job, Lab, Loc, Pair
from .standby import StandbyPolicy


@dataclass(frozen=True)
class Context:
    dist: DistanceModel
    office: Loc
    labs: Dict[str, Lab]
    tolerance_min: int
    access_min: int
    kit_stop_min: int
    min_gap_min: int
    standby: StandbyPolicy


@dataclass
class Schedule:
    ok: bool
    blocks: List[Block]
    km: float
    reason: Optional[str] = None


class _Infeasible(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class _Sample:
    job_id: str
    lab_id: str
    deadline: int  # latest arrival at the lab


class _Walker:
    """The pair's position in time and space while its day is being laid out."""

    def __init__(self, pair: Pair, ctx: Context):
        self.pair, self.ctx = pair, ctx
        self.t = pair.shift_start_min
        self.loc = ctx.office
        self.last_office = self.t  # the latest moment the pair was at the office
        self.blocks: List[Block] = []
        self.km = 0.0
        self.pending: List[_Sample] = []

    def clone(self) -> "_Walker":
        other = copy.copy(self)
        other.blocks = list(self.blocks)
        other.pending = list(self.pending)
        return other

    # -- movement ----------------------------------------------------------------------------

    def _drive(self, to: Loc, depart: int) -> int:
        """Drive from here to `to`, leaving at `depart` (never earlier than now); returns the arrival."""
        if self.loc == self.ctx.office:
            self.last_office = max(self.last_office, depart)
        if to == self.loc:
            self.t = depart
            return depart
        km = self.ctx.dist.km(self.loc, to)
        arrive = depart + self.ctx.dist.minutes(self.loc, to, depart)
        self.blocks.append(Block(DRIVE, depart, arrive, to, from_loc=self.loc, km=km))
        self.km += km
        self.loc, self.t = to, arrive
        return arrive

    def _wait_until(self, until: int, note: str) -> None:
        if until > self.t:
            self.blocks.append(Block(STANDBY, self.t, until, self.loc, note=note))
            self.t = until
        if self.loc == self.ctx.office:
            self.last_office = max(self.last_office, self.t)

    def _depart_for(self, frm: Loc, to: Loc, earliest: int, target: int) -> int:
        """The latest departure (not before `earliest`) that still arrives at about `target`."""
        d = max(earliest, target - self.ctx.dist.minutes(frm, to, earliest))
        for _ in range(3):
            arrival = d + self.ctx.dist.minutes(frm, to, d)
            if arrival == target:
                break
            d = max(earliest, d + (target - arrival))
        return d

    # -- one visit ---------------------------------------------------------------------------

    def _approach(self, dest: Loc, target: int) -> int:
        """Get to `dest` for `target`, waiting or detouring to a standby spot if there is spare time."""
        ctx = self.ctx
        direct = self.t + ctx.dist.minutes(self.loc, dest, self.t)
        if direct >= target:
            return self._drive(dest, self.t)
        spot = None
        if target - direct >= ctx.min_gap_min:
            spot = ctx.standby.spot(self.loc, dest)
        if spot is not None and spot.loc != self.loc:
            at_spot = self.t + ctx.dist.minutes(self.loc, spot.loc, self.t)
            leave = self._depart_for(spot.loc, dest, at_spot, target)
            if leave + ctx.dist.minutes(spot.loc, dest, leave) <= target + ctx.tolerance_min:
                self._drive(spot.loc, self.t)
                self._wait_until(leave, spot.note)
                return self._drive(dest, leave)
        leave = self._depart_for(self.loc, dest, self.t, target)
        self._wait_until(leave, "office" if self.loc == ctx.office else "in place")
        return self._drive(dest, leave)

    def go_to_job(self, job: Job) -> None:
        """Travel to the job and serve it; raises _Infeasible if the slot, shift or sample can't be met."""
        ctx = self.ctx
        window_start = job.slot_min - ctx.tolerance_min
        window_end = job.slot_min + ctx.tolerance_min

        if job.needs_kits and self.last_office < job.published_min + ctx.kit_stop_min:
            self._drive(ctx.office, self.t)
            start = max(self.t, job.published_min)
            self._wait_until(start, "office")
            self.blocks.append(Block(OFFICE, start, start + ctx.kit_stop_min, ctx.office, note="IV kits"))
            self.t = self.last_office = start + ctx.kit_stop_min

        arrival = self._approach(job.loc, window_start)
        if arrival < window_start:
            self._wait_until(window_start, "early at door")
            arrival = window_start
        if arrival > window_end:
            raise _Infeasible("window_missed")

        end = arrival + ctx.access_min + job.duration_min
        if end > self.pair.shift_end_min:
            raise _Infeasible("shift_ended")
        self.blocks.append(Block(VISIT, arrival, end, job.loc, job_id=job.job_id,
                                 service_start=arrival + ctx.access_min))
        self.t, self.loc = end, job.loc

        if job.lab_id is not None:
            lab = ctx.labs[job.lab_id]
            deadline = end + job.sample_max_min
            self._check_lab_reachable(lab, self.loc, end, deadline)
            self.pending.append(_Sample(job.job_id, job.lab_id, deadline))

    # -- labs --------------------------------------------------------------------------------

    def _check_lab_reachable(self, lab: Lab, frm: Loc, depart: int, deadline: int) -> int:
        """When a drop at `lab` would start, or raise if it can't meet the deadline or opening hours."""
        arrive = depart + self.ctx.dist.minutes(frm, lab.loc, depart)
        start = max(arrive, lab.opens_min)
        if arrive > deadline:
            raise _Infeasible("sample_deadline")
        if start > deadline:
            raise _Infeasible("lab_closed")
        if start + lab.handover_min > lab.closes_min:
            raise _Infeasible("lab_closed")
        return start

    def drop_samples(self, lab_id: str) -> None:
        lab = self.ctx.labs[lab_id]
        group = [p for p in self.pending if p.lab_id == lab_id]
        start = self._check_lab_reachable(lab, self.loc, self.t, min(p.deadline for p in group))
        self._drive(lab.loc, self.t)
        self._wait_until(start, "lab opens")
        end = start + lab.handover_min
        if end > self.pair.shift_end_min:
            raise _Infeasible("shift_ended")
        self.blocks.append(Block(LAB, start, end, lab.loc, lab_id=lab_id,
                                 job_ids=tuple(sorted(p.job_id for p in group))))
        self.t = end
        self.pending = [p for p in self.pending if p.lab_id != lab_id]

    def _at_risk_lab(self, job: Job) -> Optional[str]:
        """The lab to visit first if serving `job` next would make a carried sample miss its deadline."""
        if not self.pending:
            return None
        trial = self.clone()
        trial.go_to_job(job)
        at_risk = []
        for p in self.pending:  # samples carried before this job; the job's own sample was checked in go_to_job
            try:
                trial._check_lab_reachable(self.ctx.labs[p.lab_id], trial.loc, trial.t, p.deadline)
            except _Infeasible:
                at_risk.append(p)
        if not at_risk:
            return None
        return min(at_risk, key=lambda p: (p.deadline, p.lab_id)).lab_id


def build_schedule(pair: Pair, jobs: Sequence[Job], ctx: Context) -> Schedule:
    """Lay out the pair's whole day for `jobs`, in the given order."""
    walker = _Walker(pair, ctx)
    try:
        for job in jobs:
            while True:
                lab_id = walker._at_risk_lab(job)
                if lab_id is None:
                    break
                walker.drop_samples(lab_id)
            walker.go_to_job(job)
        while walker.pending:
            first = min(walker.pending, key=lambda p: (p.deadline, p.lab_id))
            walker.drop_samples(first.lab_id)
        walker._drive(ctx.office, walker.t)  # the way home counts towards km, not towards the shift
    except _Infeasible as failure:
        return Schedule(False, [], 0.0, failure.reason)
    return Schedule(True, walker.blocks, walker.km)
