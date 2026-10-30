"""Plan a day: put each order where it adds the fewest km, or reject it with a reason.

Cheapest insertion. For an order, try every pair that may serve it and every position in that pair's
sequence of visits, lay out the whole day with `build_schedule`, and keep the feasible option that adds
the fewest km. Ties go to the lower pair id, then the earlier position, so the result is deterministic.

When a decision is made part-way through the day (`now`), the part of each pair's day that has already
started is fixed: a candidate that would change it is not feasible (see `commit`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence

from .commit import prefix_matches, with_idle_tail
from .model import Block, DayPlan, Job, Pair, PairDay, Rejection
from .schedule import Context, Schedule, build_schedule

LAB_REASONS = {"sample_deadline", "lab_closed"}


@dataclass(frozen=True)
class Insertion:
    pair_id: str
    position: int
    schedule: Schedule
    added_km: float


def eligible(pair: Pair, job: Job) -> bool:
    return pair.iv_certified or not job.iv_certified_only


def best_insertion(
    job: Job, pairs: Sequence[Pair], sequences: Dict[str, List[Job]], km: Dict[str, float], ctx: Context,
    now: Optional[int] = None, blocks: Optional[Dict[str, List[Block]]] = None,
) -> Optional[Insertion]:
    """The cheapest feasible way to add `job` to any pair's day, or None.

    With `now` and the pairs' current `blocks`, the part of each day that has started by `now` is kept.
    """
    best: Optional[Insertion] = None
    for pair in sorted(pairs, key=lambda p: p.pair_id):
        if not eligible(pair, job):
            continue
        jobs = sequences[pair.pair_id]
        for position in range(len(jobs) + 1):
            schedule = build_schedule(pair, jobs[:position] + [job] + jobs[position:], ctx)
            if not schedule.ok:
                continue
            if now is not None and not prefix_matches(
                with_idle_tail(pair, blocks[pair.pair_id], ctx.office), with_idle_tail(pair, schedule.blocks, ctx.office), now
            ):
                continue
            added = schedule.km - km[pair.pair_id]
            if best is None or added < best.added_km - 1e-9:
                best = Insertion(pair.pair_id, position, schedule, added)
    return best


def explain_rejection(job: Job, pairs: Sequence[Pair], ctx: Context) -> str:
    """Why nothing fits: structural reasons first, otherwise the day is simply full."""
    candidates = [p for p in pairs if eligible(p, job)]
    if not candidates:
        return "no_certified_nurse"
    reasons = set()
    for pair in candidates:
        alone = build_schedule(pair, [job], ctx)  # the job on an otherwise empty day
        if alone.ok:
            return "no_capacity"
        reasons.add(alone.reason)
    return "lab_unreachable" if reasons <= LAB_REASONS else "outside_shifts"


def plan_day(day: date, pairs: Sequence[Pair], jobs: Sequence[Job], ctx: Context) -> DayPlan:
    """Plan `jobs` over `pairs` in the order given (the order they would be accepted in)."""
    sequences: Dict[str, List[Job]] = {p.pair_id: [] for p in pairs}
    km: Dict[str, float] = {p.pair_id: 0.0 for p in pairs}
    blocks: Dict[str, list] = {p.pair_id: [] for p in pairs}
    rejected: List[Rejection] = []

    for job in jobs:
        choice = best_insertion(job, pairs, sequences, km, ctx)
        if choice is None:
            rejected.append(Rejection(job.job_id, explain_rejection(job, pairs, ctx)))
            continue
        seq = sequences[choice.pair_id]
        seq.insert(choice.position, job)
        km[choice.pair_id] = choice.schedule.km
        blocks[choice.pair_id] = choice.schedule.blocks

    by_id = {p.pair_id: p for p in pairs}
    days = {
        pid: PairDay(by_id[pid], [j.job_id for j in sequences[pid]], blocks[pid]) for pid in sorted(by_id)
    }
    return DayPlan(day, days, rejected)
