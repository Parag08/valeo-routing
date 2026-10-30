"""Check a day plan against the rules, independently of the planner.

This module reads only the finished plan (blocks, jobs, labs, the distance model) and re-derives every
rule from scratch; it shares no scheduling code with `schedule` or `planner`. An empty result means the
plan is valid. Codes:

    overlap, gap, teleport      blocks do not join up in time or place
    drive_km, drive_time        a drive disagrees with the distance model
    not_home                    the day does not end at the office
    window, service_start, duration, shift, certification   a visit breaks its rules
    duplicate_job, unknown_job, job_order, resource_reuse   bookkeeping errors
    sample_not_dropped, sample_deadline, lab_hours, lab_handover   sample or lab rules
    kit_missing                 an IV visit without office kits prepared since it was published
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .distance import DistanceModel
from .model import DRIVE, LAB, STANDBY, VISIT, Block, DayPlan, Job, Lab, Loc, PairDay


@dataclass(frozen=True)
class Rules:
    dist: DistanceModel
    office: Loc
    labs: Dict[str, Lab]
    tolerance_min: int
    access_min: int
    kit_stop_min: int


@dataclass(frozen=True)
class Violation:
    code: str
    pair_id: Optional[str]
    job_id: Optional[str]
    detail: str


def _office_departures(blocks: Sequence[Block], pair_start: int, office: Loc) -> List[int]:
    """Every moment the pair was at the office: the start of the shift, then each time it left."""
    times = [pair_start]
    here = office
    for b in blocks:
        if b.kind == DRIVE:
            if here == office:
                times.append(b.start)
            here = b.loc
    return times


def _check_continuity(day: PairDay, rules: Rules, out: List[Violation]) -> None:
    pid = day.pair.pair_id
    time, here = day.pair.shift_start_min, rules.office
    for b in day.blocks:
        if b.start < time:
            out.append(Violation("overlap", pid, b.job_id, "{} starts at {} before {}".format(b.kind, b.start, time)))
        elif b.start > time:
            out.append(Violation("gap", pid, b.job_id, "{} starts at {} after idle {}".format(b.kind, b.start, time)))
        if b.end < b.start:
            out.append(Violation("overlap", pid, b.job_id, "{} ends before it starts".format(b.kind)))
        if b.kind == DRIVE:
            if b.from_loc != here:
                out.append(Violation("teleport", pid, None, "drive leaves from {}, pair is at {}".format(b.from_loc, here)))
            km = rules.dist.km(b.from_loc, b.loc)
            if abs(km - b.km) > 1e-6:
                out.append(Violation("drive_km", pid, None, "{:.3f} km claimed, {:.3f} by the model".format(b.km, km)))
            minutes = rules.dist.minutes(b.from_loc, b.loc, b.start)
            if b.end - b.start != minutes:
                out.append(Violation("drive_time", pid, None, "{} min claimed, {} by the model".format(b.end - b.start, minutes)))
            here = b.loc
        elif b.loc != here:
            out.append(Violation("teleport", pid, b.job_id, "{} at {}, pair is at {}".format(b.kind, b.loc, here)))
        time = max(time, b.end)
    if day.blocks and here != rules.office:
        out.append(Violation("not_home", pid, None, "day ends at {}".format(here)))


def _check_shift(day: PairDay, out: List[Violation]) -> None:
    """Everything except the final way home must finish inside the shift."""
    blocks = list(day.blocks)
    while blocks and blocks[-1].kind == DRIVE:
        blocks.pop()
    for b in blocks:
        if b.end > day.pair.shift_end_min:
            out.append(Violation("shift", day.pair.pair_id, b.job_id, "{} ends at {}, shift ends {}".format(
                b.kind, b.end, day.pair.shift_end_min)))
    for b in day.blocks:
        if b.start < day.pair.shift_start_min:
            out.append(Violation("shift", day.pair.pair_id, b.job_id, "{} starts before the shift".format(b.kind)))


def _check_visits(day: PairDay, jobs: Dict[str, Job], rules: Rules, out: List[Violation]) -> None:
    pid = day.pair.pair_id
    visits = [b for b in day.blocks if b.kind == VISIT]
    if [b.job_id for b in visits] != day.job_ids:
        out.append(Violation("job_order", pid, None, "visit blocks {} do not match jobs {}".format(
            [b.job_id for b in visits], day.job_ids)))
    kit_times = _office_departures(day.blocks, day.pair.shift_start_min, rules.office)
    for b in visits:
        job = jobs.get(b.job_id)
        if job is None:
            out.append(Violation("unknown_job", pid, b.job_id, "no such job"))
            continue
        if b.loc != job.loc:
            out.append(Violation("teleport", pid, b.job_id, "visit is not at the patient's location"))
        if not job.slot_min - rules.tolerance_min <= b.start <= job.slot_min + rules.tolerance_min:
            out.append(Violation("window", pid, b.job_id, "arrives {} for slot {}".format(b.start, job.slot_min)))
        if b.service_start != b.start + rules.access_min:
            out.append(Violation("service_start", pid, b.job_id, "service starts {}".format(b.service_start)))
        if b.end != (b.service_start or 0) + job.duration_min:
            out.append(Violation("duration", pid, b.job_id, "visit lasts to {}".format(b.end)))
        if job.iv_certified_only and not day.pair.iv_certified:
            out.append(Violation("certification", pid, b.job_id, "IV visit by a nurse who is not IV certified"))
        if job.needs_kits and not any(
            job.published_min + rules.kit_stop_min <= t <= b.start for t in kit_times
        ):
            out.append(Violation("kit_missing", pid, b.job_id, "no office visit since the order was published"))


def _lab_arrival(blocks: Sequence[Block], index: int) -> int:
    """When the pair got to the lab: the start of any wait at the lab just before the drop."""
    arrival = blocks[index].start
    j = index - 1
    while j >= 0 and blocks[j].kind == STANDBY and blocks[j].loc == blocks[index].loc:
        arrival = blocks[j].start
        j -= 1
    return arrival


def _check_samples(day: PairDay, jobs: Dict[str, Job], rules: Rules, out: List[Violation]) -> None:
    pid = day.pair.pair_id
    drops: Dict[str, List[Tuple[int, Block]]] = {}
    for i, b in enumerate(day.blocks):
        if b.kind != LAB:
            continue
        lab = rules.labs.get(b.lab_id)
        arrival = _lab_arrival(day.blocks, i)
        if lab is None or b.loc != lab.loc:
            out.append(Violation("lab_hours", pid, None, "drop at an unknown or wrong lab"))
            continue
        if b.start < lab.opens_min or b.end > lab.closes_min:
            out.append(Violation("lab_hours", pid, None, "{} drop {}-{} outside {}-{}".format(
                lab.lab_id, b.start, b.end, lab.opens_min, lab.closes_min)))
        if b.end - b.start != lab.handover_min:
            out.append(Violation("lab_handover", pid, None, "{} drop takes {} min".format(lab.lab_id, b.end - b.start)))
        for job_id in b.job_ids:
            drops.setdefault(job_id, []).append((arrival, b))
    for b in (x for x in day.blocks if x.kind == VISIT):
        job = jobs.get(b.job_id)
        if job is None or job.lab_id is None:
            continue
        mine = drops.get(job.job_id, [])
        if len(mine) != 1 or mine[0][1].start < b.end or mine[0][1].lab_id != job.lab_id:
            out.append(Violation("sample_not_dropped", pid, job.job_id, "sample must be handed over once, at {}, after the visit".format(job.lab_id)))
            continue
        if mine[0][0] > b.end + job.sample_max_min:
            out.append(Violation("sample_deadline", pid, job.job_id, "reaches the lab at {}, deadline {}".format(
                mine[0][0], b.end + job.sample_max_min)))
    planned = {b.job_id for b in day.blocks if b.kind == VISIT}
    for job_id in drops:
        if job_id not in planned:
            out.append(Violation("sample_not_dropped", pid, job_id, "a sample is dropped that was never collected"))


def validate(plan: DayPlan, jobs: Dict[str, Job], rules: Rules) -> List[Violation]:
    """Every rule violation in the plan; an empty list means it is valid."""
    out: List[Violation] = []
    seen: Dict[str, str] = {}
    resources: Dict[str, str] = {}
    for pid, day in plan.pairs.items():
        for key in ("nurse_id", "driver_id", "car_id"):
            value = getattr(day.pair, key)
            if value in resources and resources[value] != pid:
                out.append(Violation("resource_reuse", pid, None, "{} is in pairs {} and {}".format(value, resources[value], pid)))
            resources[value] = pid
        for job_id in day.job_ids:
            if job_id in seen:
                out.append(Violation("duplicate_job", pid, job_id, "also served by {}".format(seen[job_id])))
            seen[job_id] = pid
        _check_continuity(day, rules, out)
        _check_shift(day, out)
        _check_visits(day, jobs, rules, out)
        _check_samples(day, jobs, rules, out)
    for rejection in plan.rejected:
        if rejection.job_id in seen:
            out.append(Violation("duplicate_job", None, rejection.job_id, "rejected but also planned"))
    return out
