"""Roster auto-allocation: who works together, and when each pair's shift starts.

Demand first. For a service day, expected work per hour comes from the *other* days in the data: the
mean order count for that weekday, spread over the hours by when work actually fell, and moved earlier by
the time a pair needs to reach the patient. Each order counts as its planned service time, the access
time and a driving allowance, so the curve is in pair-hours, and
`required_pairs` divides it by the share of an hour a pair should be working, and never lets an hour
that usually has bookings fall below a minimum, because an hour nobody covers loses every order in it.

Then cover it. Every available nurse and driver is paired (the smaller group sets the number of pairs;
the rest stay in reserve), and each pair gets the shift start, on the configured grid, that most reduces
the squared shortfall against the required curve, so peaks are covered first. Ties go to the start that
covers the most demand, then to the earlier start. IV-certified nurses are then spread across the starts,
so IV work is possible whenever the shifts overlap.

Not modelled: split shifts (one window per pair), keeping the same nurse and driver together from day to
day, and `shift_pref` in the staff data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Collection, Dict, List, Sequence, Tuple

from valeo_routing.datagen.reference import Service
from valeo_routing.settings import EngineSettings

from .catalog import Catalog
from .data import AvailabilityRow, OrderRow, StaffRow
from .model import Pair


@dataclass(frozen=True)
class Demand:
    hours: Tuple[int, ...]  # hour of day each entry describes
    orders: Tuple[float, ...]  # expected orders requested to start in that hour
    pair_hours: Tuple[float, ...]  # expected work, as pairs kept busy through the hour
    required_pairs: Tuple[float, ...]  # pair_hours / target utilisation


@dataclass(frozen=True)
class Roster:
    mode: str  # auto / simple
    pairs: List[Pair]
    reserve: List[str]  # available staff who are not paired
    demand: Demand
    on_duty: Tuple[float, ...]  # pairs on duty in each of demand.hours (fractional at half-hour starts)

    @property
    def shortfall(self) -> float:
        """Pair-hours of expected demand that the roster leaves uncovered."""
        return shortfall(self.demand.required_pairs, self.on_duty)


def hour_span(s: EngineSettings) -> Tuple[int, ...]:
    """The hours a roster has to cover: from the earliest start to the end of the latest shift."""
    first = s.roster_starts[0] // 60
    last = -(-(s.roster_starts[-1] + int(round(s.shift_hours * 60))) // 60)
    return tuple(range(first, last))


def cover(start_min: int, length_min: int, hours: Sequence[int]) -> List[float]:
    """For each hour, the fraction of it that a shift starting at `start_min` is on duty."""
    return [
        max(0, min(start_min + length_min, h * 60 + 60) - max(start_min, h * 60)) / 60.0 for h in hours
    ]


def shortfall(required: Sequence[float], on_duty: Sequence[float]) -> float:
    return sum(max(0.0, r - c) for r, c in zip(required, on_duty))


def expected_demand(
    orders: Sequence[OrderRow], services: Dict[str, Service], catalog: Catalog, day: date, s: EngineSettings
) -> Demand:
    """Expected demand for `day`, estimated from every other day's orders (cancelled ones left out)."""
    hours = hour_span(s)
    history = [o for o in orders if o.service_date != day and o.cancelled_at is None]
    days = {o.service_date for o in orders if o.service_date != day}
    per_day: Dict[date, int] = {}
    for o in history:
        per_day[o.service_date] = per_day.get(o.service_date, 0) + 1
    same_weekday = [n for d, n in per_day.items() if d.weekday() == day.weekday()]
    pool = same_weekday or list(per_day.values())
    expected_total = sum(pool) / len(pool) if pool else 0.0
    n_days = max(1, len(days))

    orders_h = [0.0] * len(hours)
    work_h = [0.0] * len(hours)
    index = {h: i for i, h in enumerate(hours)}
    for o in history:
        i = index.get(o.slot_start.hour)
        if i is None:
            continue
        work = catalog.planned_minutes(services[o.service_id]) + s.access_min + s.roster_travel_allowance_min
        orders_h[i] += 1.0
        work_h[i] += work
    if not history:
        return Demand(hours, tuple(orders_h), tuple(work_h), tuple(work_h))

    # Scale the mean daily history to the expected total for this weekday.
    mean_daily = len(history) / n_days
    scale = expected_total / mean_daily if mean_daily else 0.0
    orders_exp = _earlier([x / n_days * scale for x in orders_h], s.roster_lead_min)
    pair_hours = _earlier([x / n_days * scale / 60.0 for x in work_h], s.roster_lead_min)
    required = [
        max(x / s.roster_target_utilisation, s.roster_min_pairs_when_booked if o >= s.roster_min_orders_for_cover else 0.0)
        for x, o in zip(pair_hours, orders_exp)
    ]
    return Demand(hours, tuple(orders_exp), tuple(pair_hours), tuple(required))


def _earlier(per_hour: Sequence[float], lead_min: int) -> List[float]:
    """Move each hour's demand `lead_min` minutes earlier: a pair has to be there before the slot."""
    f = lead_min / 60.0
    return [(1 - f) * x + f * (per_hour[i + 1] if i + 1 < len(per_hour) else 0.0) for i, x in enumerate(per_hour)]


def choose_starts(n: int, demand: Demand, s: EngineSettings) -> List[int]:
    """Shift starts for `n` pairs that best cover the required curve, peaks first."""
    length = int(round(s.shift_hours * 60))
    options = {start: cover(start, length, demand.hours) for start in s.roster_starts}
    required = demand.required_pairs
    covered = [0.0] * len(demand.hours)
    starts: List[int] = []
    for _ in range(n):
        best = None
        for start, cov in sorted(options.items()):
            gap = sum(max(0.0, r - (c + x)) ** 2 for r, c, x in zip(required, covered, cov))
            weight = sum(r * x for r, x in zip(required, cov))
            key = (round(gap, 9), -round(weight, 9), start)
            if best is None or key < best[0]:
                best = (key, start, cov)
        starts.append(best[1])
        covered = [c + x for c, x in zip(covered, best[2])]
    return sorted(starts)


def _spread(n: int, k: int) -> List[int]:
    """`k` positions spread evenly across `n` slots."""
    return sorted({min(n - 1, int((i + 0.5) * n / k)) for i in range(k)}) if k else []


def _on_duty(pairs: Sequence[Pair], hours: Sequence[int]) -> Tuple[float, ...]:
    totals = [0.0] * len(hours)
    for p in pairs:
        totals = [t + x for t, x in zip(totals, cover(p.shift_start_min, p.shift_end_min - p.shift_start_min, hours))]
    return tuple(totals)


def _available(day: date, staff: Sequence[StaffRow], availability: Sequence[AvailabilityRow],
               unavailable: Collection[str]) -> Tuple[List[StaffRow], List[StaffRow]]:
    ok = {a.staff_id for a in availability if a.date == day and a.status == "available"} - set(unavailable)
    nurses = [p for p in staff if p.role == "nurse" and p.staff_id in ok]
    drivers = sorted((p for p in staff if p.role == "driver" and p.staff_id in ok), key=lambda p: p.staff_id)
    nurses.sort(key=lambda p: (not p.iv_certified, p.staff_id))  # IV-certified first
    return nurses, drivers


def allocate(
    day: date, staff: Sequence[StaffRow], availability: Sequence[AvailabilityRow], demand: Demand,
    s: EngineSettings, unavailable: Collection[str] = (),
) -> Roster:
    """The auto-allocated roster: pairs, shift starts that cover demand, IV nurses spread across the starts."""
    nurses, drivers = _available(day, staff, availability, unavailable)
    n = min(len(nurses), len(drivers))
    reserve = [p.staff_id for p in nurses[n:]] + [p.staff_id for p in drivers[n:]]
    nurses, drivers = nurses[:n], drivers[:n]
    length = int(round(s.shift_hours * 60))
    starts = choose_starts(n, demand, s)

    certified = [p for p in nurses if p.iv_certified]
    plain = [p for p in nurses if not p.iv_certified]
    slots: List[StaffRow] = [None] * n  # type: ignore[list-item]
    for position, nurse in zip(_spread(n, len(certified)), certified):
        slots[position] = nurse
    for i in range(n):  # spread() can collide only if k > n, which cannot happen; fill the rest in order
        if slots[i] is None:
            slots[i] = plain.pop(0) if plain else certified.pop()
    pairs = [
        Pair("P{:02d}".format(i + 1), slots[i].staff_id, drivers[i].staff_id, drivers[i].usual_car_id,
             slots[i].iv_certified, starts[i], starts[i] + length)
        for i in range(n)
    ]
    return Roster("auto", pairs, reserve, demand, _on_duty(pairs, demand.hours))


def simple(
    day: date, staff: Sequence[StaffRow], availability: Sequence[AvailabilityRow], demand: Demand,
    s: EngineSettings, unavailable: Collection[str] = (),
) -> Roster:
    """The placeholder roster: pair in id order and cycle the configured shift starts (see `pairs`)."""
    from .pairs import build_pairs

    pairs = build_pairs(day, staff, availability, s.shift_start_minutes, s.shift_hours, unavailable)
    nurses, drivers = _available(day, staff, availability, unavailable)
    n = len(pairs)
    reserve = [p.staff_id for p in nurses[n:]] + [p.staff_id for p in drivers[n:]]
    return Roster("simple", pairs, reserve, demand, _on_duty(pairs, demand.hours))
