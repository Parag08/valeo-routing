"""Replay one service day in time order: orders are decided on, patients cancel, a competitor claims.

Events happen in minute order. A policy says when each order is decided; at that moment the planner is
asked whether the order fits, subject to two clocks:

* the competitor's claim: if nobody has accepted an order `competitor_claim_min` minutes after it was
  published, another provider takes it, and it is lost;
* the day itself: what a pair has already started cannot change (see `commit`).

A patient's cancellation removes the visit only if the plan can drop it without changing anything that
has already started; otherwise the visit still happens and is logged as a late cancellation.

Under v2 an order that fits nowhere may still be accepted by making room (see `swap`): an accepted order
is moved to another pair, or released back to the platform (`bumped`), and the log says which.

The roster is the day's final one (who was actually available), a known simplification: sick calls are
not yet played out as disruptions.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from .catalog import Catalog
from .commit import prefix_matches, with_idle_tail
from .data import OrderRow, minutes_of_day, to_job
from .model import DRIVE, LAB, OFFICE, STANDBY, VISIT, Block, DayPlan, Job, Pair, PairDay, Rejection
from .planner import best_insertion, explain_rejection
from .policy import AcceptancePolicy
from .schedule import Context, build_schedule
from .swap import find_room

ACCEPTED, DECLINED, LOST, CANCELLED_EARLY = "accepted", "declined", "lost", "cancelled_before_decision"
SERVED, CANCELLED, LATE_CANCEL, NOT_SERVED = "served", "cancelled", "late_cancellation", "not_served"
BUMPED = "bumped"  # v2: accepted, then released back to the platform to make room for another order


@dataclass
class DecisionRecord:
    """One row of the decision log."""

    order_id: str
    published_min: int
    slot_min: int
    decided_min: int
    mode: str  # auto / manual / excel
    outcome: str  # accepted / declined / lost / cancelled_before_decision
    reason: str
    pair_id: Optional[str] = None
    final: str = NOT_SERVED  # served / cancelled / late_cancellation / not_served / bumped
    room: str = ""  # v2: how room was made for this order, or what happened to it to make room for another


@dataclass
class DayKpis:
    offered: int = 0
    cancelled_before_decision: int = 0
    accepted: int = 0
    lost: int = 0
    declined: int = 0
    honored_cancellations: int = 0
    late_cancellations: int = 0
    moved: int = 0  # v2: accepted orders moved to another pair to make room
    bumped: int = 0  # v2: accepted orders released back to the platform to make room
    km: float = 0.0
    visit_h: float = 0.0
    drive_h: float = 0.0
    idle_h: float = 0.0  # on-shift time that is neither driving, serving, at the lab nor collecting kits

    @property
    def capturable(self) -> int:
        return self.offered - self.cancelled_before_decision

    @property
    def capture_rate(self) -> float:
        """Accepted and kept: an order released to make room for another does not count."""
        return (self.accepted - self.bumped) / self.capturable if self.capturable else 0.0

    @property
    def visits(self) -> int:
        """Visits actually made: accepted, less the cancellations the plan could drop and orders released."""
        return self.accepted - self.honored_cancellations - self.bumped

    @property
    def km_per_visit(self) -> float:
        return self.km / self.visits if self.visits else 0.0

    def __add__(self, other: "DayKpis") -> "DayKpis":
        return DayKpis(**{f: getattr(self, f) + getattr(other, f) for f in self.__dataclass_fields__})


@dataclass
class DayResult:
    day: date
    policy: str
    plan: DayPlan
    jobs: Dict[str, Job]
    log: List[DecisionRecord]
    kpis: DayKpis
    trace: List[Tuple[int, Dict[str, List[Block]]]] = field(default_factory=list)


def _kpis(plan: DayPlan, log: Sequence[DecisionRecord]) -> DayKpis:
    k = DayKpis(offered=len(log))
    for r in log:
        k.cancelled_before_decision += r.outcome == CANCELLED_EARLY
        k.accepted += r.outcome == ACCEPTED
        k.lost += r.outcome == LOST
        k.declined += r.outcome == DECLINED
        k.honored_cancellations += r.final == CANCELLED
        k.late_cancellations += r.final == LATE_CANCEL
        k.bumped += r.final == BUMPED
        k.moved += r.room.startswith("moved")
    for day in plan.pairs.values():
        k.km += day.km
        busy = sum(day.minutes(kind) for kind in (VISIT, DRIVE, LAB, OFFICE))
        shift = day.pair.shift_end_min - day.pair.shift_start_min
        k.visit_h += day.minutes(VISIT) / 60.0
        k.drive_h += day.minutes(DRIVE) / 60.0
        k.idle_h += max(0, shift - busy) / 60.0
    return k


def replay_day(
    day: date, pairs: Sequence[Pair], rows: Sequence[OrderRow], services: Dict, catalog: Catalog,
    ctx: Context, policy: AcceptancePolicy, replay_seed: int, trace: bool = False,
) -> DayResult:
    """Run the day under `policy`. `rows` are every order for the service date, cancelled ones included.

    Idle pairs wait where the policy says (office or hubs); a policy without a standby keeps the context's.
    """
    if policy.standby is not None:
        ctx = replace(ctx, standby=policy.standby)
    swap_rules = getattr(policy, "swap_rules", None)  # v2 only
    rng = random.Random("{}|{}|{}".format(replay_seed, day, policy.name))
    ordered = sorted(rows, key=lambda r: r.order_id)
    jobs = {r.order_id: to_job(r, services[r.service_id], catalog) for r in ordered}
    claim = {r.order_id: r.competitor_claim_min for r in ordered}
    cancel_at = {r.order_id: minutes_of_day(r.cancelled_at, day) for r in ordered if r.cancelled_at}

    events: List[Tuple[int, int, str, str, object]] = []
    for r in ordered:
        decision = policy.when(jobs[r.order_id], rng)  # drawn in a fixed order, whatever the event order
        events.append((decision.time_min, 1, r.order_id, "decide", decision))
        if r.order_id in cancel_at:
            events.append((cancel_at[r.order_id], 0, r.order_id, "cancel", None))
    events.sort(key=lambda e: e[:3])

    sequences: Dict[str, List[Job]] = {p.pair_id: [] for p in pairs}
    blocks: Dict[str, List[Block]] = {p.pair_id: [] for p in pairs}
    km: Dict[str, float] = {p.pair_id: 0.0 for p in pairs}
    by_id = {p.pair_id: p for p in pairs}
    log: Dict[str, DecisionRecord] = {}
    cancelled_early = set()
    snapshots: List[Tuple[int, Dict[str, List[Block]]]] = []

    def record(job: Job, mode: str, decided: int, outcome: str, reason: str, pair_id: Optional[str] = None):
        log[job.job_id] = DecisionRecord(job.job_id, job.published_min, job.slot_min, decided, mode, outcome, reason, pair_id)

    for now, _, order_id, kind, decision in events:
        job = jobs[order_id]
        if kind == "cancel":
            pair_id = log[order_id].pair_id if order_id in log and log[order_id].outcome == ACCEPTED else None
            if order_id in log and log[order_id].final == BUMPED:
                pass  # released earlier; no longer this fleet's order
            elif pair_id is None:
                cancelled_early.add(order_id)
            else:
                pair = by_id[pair_id]
                remaining = [j for j in sequences[pair_id] if j.job_id != order_id]
                schedule = build_schedule(pair, remaining, ctx)
                if schedule.ok and prefix_matches(
                    with_idle_tail(pair, blocks[pair_id], ctx.office), with_idle_tail(pair, schedule.blocks, ctx.office), now
                ):
                    sequences[pair_id], blocks[pair_id], km[pair_id] = remaining, schedule.blocks, schedule.km
                    log[order_id].final = CANCELLED
                else:
                    log[order_id].final = LATE_CANCEL
        else:
            if order_id in cancelled_early:
                record(job, decision.mode, now, CANCELLED_EARLY, "patient cancelled before anyone decided")
            elif now > job.published_min + claim[order_id]:
                record(job, decision.mode, job.published_min + claim[order_id], LOST,
                       "claimed by another provider {} min after publishing; this order was due to be decided {} min after".format(
                           claim[order_id], now - job.published_min))
            elif now > job.slot_min + ctx.tolerance_min:
                record(job, decision.mode, now, DECLINED, "too_late: decided after the arrival window had closed")
            else:
                choice = best_insertion(job, pairs, sequences, km, ctx, now=now, blocks=blocks)
                room = None
                if choice is None and swap_rules is not None:
                    room = find_room(job, pairs, sequences, blocks, km, ctx, now, swap_rules, policy.cancels)
                if room is not None:
                    other, pid = room.other, room.pair_id
                    sequences[pid] = list(room.sequence)
                    blocks[pid], km[pid] = room.schedule.blocks, room.schedule.km
                    at = "{:02d}:{:02d}".format(now // 60 % 24, now % 60)
                    if room.kind == "move":
                        to = room.moved_to
                        sequences[to].insert(room.position, other)
                        blocks[to], km[to] = room.moved_schedule.blocks, room.moved_schedule.km
                        log[other.job_id].pair_id = to
                        log[other.job_id].room = "moved {} to {} at {} for {}".format(pid, to, at, order_id)
                        how = "made room on {} by moving {} to {} ({:+.1f} km)".format(pid, other.job_id, to, room.km_change)
                    else:
                        log[other.job_id].final = BUMPED
                        log[other.job_id].pair_id = None
                        log[other.job_id].room = "released to the platform at {} for {}".format(at, order_id)
                        how = "swapped out {} on {} (gain {:.1f} km-equivalent)".format(other.job_id, pid, room.gain_km)
                    record(job, decision.mode, now, ACCEPTED, how, pid)
                    log[order_id].final = SERVED
                    log[order_id].room = room.kind
                elif choice is None:
                    record(job, decision.mode, now, DECLINED, explain_rejection(job, pairs, ctx))
                else:
                    sequences[choice.pair_id].insert(choice.position, job)
                    blocks[choice.pair_id], km[choice.pair_id] = choice.schedule.blocks, choice.schedule.km
                    record(job, decision.mode, now, ACCEPTED,
                           "fits {} ({:+.1f} km)".format(choice.pair_id, choice.added_km), choice.pair_id)
                    log[order_id].final = SERVED
        if trace:
            snapshots.append((now, {pid: list(b) for pid, b in blocks.items()}))

    plan = DayPlan(
        day,
        {pid: PairDay(by_id[pid], [j.job_id for j in sequences[pid]], blocks[pid]) for pid in sorted(by_id)},
        [Rejection(r.order_id, r.reason) for r in log.values() if r.outcome == DECLINED],
    )
    records = sorted(log.values(), key=lambda r: (r.decided_min, r.order_id))
    return DayResult(day, policy.name, plan, jobs, records, _kpis(plan, records), snapshots)
