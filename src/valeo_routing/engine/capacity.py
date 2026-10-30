"""Capacity: how many nurse-driver pairs each day's demand needs.

Two numbers per service day, both on the orders the patient did not cancel:

* **Concurrency floor.** The most visits that overlap in time, each held from its earliest arrival (slot
  less the tolerance) to the end of its service. No roster can serve the day with fewer pairs, whatever
  the routing; travel and lab runs only push the real need higher.
* **Simulated need.** The fewest pairs with which the planner serves at least `CAPACITY_SERVE_SHARE` of
  the orders that `CAPACITY_MAX_PAIRS` pairs can serve, all of them known upfront (the offline plan, so
  acceptance delays and the competitor play no part). Orders that even the largest fleet cannot fit (a
  slot outside every shift, a lab out of reach, IV work clashing for the certified nurses) are reported
  as unservable rather than counted against every roster size. The pairs are hypothetical: shift starts chosen by the roster for that many pairs, and
  the staff pool's share of IV-certified nurses, spread across the starts. Idle pairs wait at the hubs
  Logistics Valeo uses by default.

Service levels then read across days: the pairs needed at p75 are enough on at least 75% of the days
(nearest-rank percentile, rounded up, so it never understates).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Sequence

from valeo_routing.datagen.reference import Service
from valeo_routing.settings import EngineSettings

from . import roster as rosters
from .catalog import Catalog
from .data import OrderRow, StaffRow, to_job
from .model import Job, Pair
from .planner import plan_day
from .schedule import Context


@dataclass(frozen=True)
class DayNeed:
    day: date
    orders: int  # not cancelled
    floor: int  # most visits overlapping in time
    unservable: int  # orders that even `CAPACITY_MAX_PAIRS` pairs do not serve
    needed: int  # fewest pairs that serve the target share of the servable orders
    served: int  # orders served with `needed` pairs
    rostered: int  # pairs the auto roster actually put on duty that day


def concurrency_floor(jobs: Sequence[Job], tolerance_min: int, access_min: int) -> int:
    """The most visits whose arrival-to-finish spans overlap at one moment."""
    events = []
    for j in jobs:
        events.append((j.slot_min - tolerance_min, 1))
        events.append((j.slot_min - tolerance_min + access_min + j.duration_min, -1))
    events.sort(key=lambda e: (e[0], e[1]))  # an end and a start at the same minute do not overlap
    most = now = 0
    for _, step in events:
        now += step
        most = max(most, now)
    return most


def hypothetical_pairs(n: int, iv_share: float, demand: rosters.Demand, s: EngineSettings) -> List[Pair]:
    """`n` pairs with roster-chosen shift starts and `round(n * iv_share)` IV-certified nurses."""
    length = int(round(s.shift_hours * 60))
    starts = rosters.choose_starts(n, demand, s)
    certified = set(rosters._spread(n, int(round(n * iv_share))))
    return [
        Pair("P{:02d}".format(i + 1), "N{:02d}".format(i + 1), "D{:02d}".format(i + 1), "C{:02d}".format(i + 1),
             i in certified, starts[i], starts[i] + length)
        for i in range(n)
    ]


def iv_share(staff: Sequence[StaffRow]) -> float:
    nurses = [p for p in staff if p.role == "nurse"]
    return sum(p.iv_certified for p in nurses) / len(nurses) if nurses else 0.0


def day_need(
    day: date, rows: Sequence[OrderRow], all_orders: Sequence[OrderRow], staff: Sequence[StaffRow],
    services: Dict[str, Service], catalog: Catalog, ctx: Context, s: EngineSettings, rostered: int,
) -> DayNeed:
    live = sorted((r for r in rows if r.cancelled_at is None), key=lambda r: (r.published_at, r.order_id))
    jobs = [to_job(r, services[r.service_id], catalog) for r in live]
    floor = concurrency_floor(jobs, ctx.tolerance_min, ctx.access_min)
    if not jobs:
        return DayNeed(day, 0, 0, 0, 0, 0, rostered)
    demand = rosters.expected_demand(all_orders, services, catalog, day, s)
    share_iv = iv_share(staff)

    def served_with(n: int) -> int:
        return plan_day(day, hypothetical_pairs(n, share_iv, demand, s), jobs, ctx).served

    most = served_with(s.capacity_max_pairs)
    target = int(math.ceil(s.capacity_serve_share * most - 1e-9))
    for n in range(max(1, floor), s.capacity_max_pairs):
        served = served_with(n)
        if served >= target:
            return DayNeed(day, len(jobs), floor, len(jobs) - most, n, served, rostered)
    return DayNeed(day, len(jobs), floor, len(jobs) - most, s.capacity_max_pairs, most, rostered)


def percentile(values: Sequence[int], p: float) -> int:
    """Nearest-rank percentile: the smallest value that at least `p`% of the values do not exceed."""
    ordered = sorted(values)
    if not ordered:
        return 0
    rank = max(1, int(math.ceil(p / 100.0 * len(ordered) - 1e-9)))
    return ordered[rank - 1]
