"""Things that happen to staff and cars on a day: sick calls, breakdowns, late starts."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

from .reference import Reference
from .staff import Availability, Staff


@dataclass
class Event:
    event_id: str
    date: date
    type: str  # sick_call / car_breakdown / late_start
    staff_id: Optional[str]
    car_id: Optional[str]
    at: datetime
    until: Optional[datetime]


def _clock(rng: random.Random, day: date, hour_range) -> datetime:
    lo, hi = hour_range
    return datetime.combine(day, time(rng.randint(lo, hi - 1), rng.randrange(60)))


def make_events(
    rng: random.Random, ref: Reference, staff: List[Staff], availability: List[Availability],
    start: date, days: int,
) -> List[Event]:
    """Sick calls mirror the availability table; breakdowns and late starts are drawn per day."""
    cfg = ref.profile["events"]
    cars = [c.car_id for c in ref.fleet if c.status == "active"]
    by_day: Dict[date, List[Availability]] = {}
    for row in availability:
        by_day.setdefault(row.date, []).append(row)

    events: List[Event] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        rows = sorted(by_day.get(day, []), key=lambda r: r.staff_id)
        for row in rows:
            if row.status == "sick":
                events.append(Event("", day, "sick_call", row.staff_id, None, row.known_at, None))
        for car_id in cars:
            b = cfg["car_breakdown"]
            if rng.random() < b["p_per_car_day"]:
                at = _clock(rng, day, b["at_hour_range"])
                if rng.random() < b["all_day_share"]:
                    until = None
                else:
                    lo, hi = b["duration_min_range"]
                    until = at + timedelta(minutes=rng.randint(lo, hi))
                events.append(Event("", day, "car_breakdown", None, car_id, at, until))
        for row in rows:
            if row.status != "available":
                continue
            late = cfg["late_start"]
            if rng.random() < late["p_per_staff_day"]:
                at = _clock(rng, day, late["at_hour_range"])
                lo, hi = late["delay_min_range"]
                events.append(Event("", day, "late_start", row.staff_id, None, at,
                                    at + timedelta(minutes=rng.randint(lo, hi))))

    events.sort(key=lambda e: (e.date, e.at, e.type, e.staff_id or "", e.car_id or ""))
    for i, event in enumerate(events, start=1):
        event.event_id = "EV-{:04d}".format(i)
    return events
