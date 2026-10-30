"""Breakdowns, late starts and absent drivers per car and day."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from .people import Driver
from .reference import Reference
from .schema import TIME_FMT

EVENT_TYPES = ("breakdown", "late_start", "driver_absent")


@dataclass
class FleetEvent:
    date: date
    car_id: str
    type: str
    at: datetime
    until: Optional[datetime]
    event_id: str = ""


def make_fleet_events(
    rng: random.Random, ref: Reference, drivers: List[Driver], start_date: date, days: int
) -> List[FleetEvent]:
    """At most one event per active car per day, drawn from the profile's rates."""
    cfg = ref.profile["fleet_events"]
    shifts: Dict[str, Driver] = {d.car_id: d for d in drivers}
    events: List[FleetEvent] = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        for car in ref.fleet:
            if car.status != "active":
                continue
            driver = shifts[car.car_id]
            t0 = datetime.strptime(driver.shift_start, TIME_FMT).time()
            shift_start = datetime.combine(day, t0)
            shift_len = ref.profile["drivers"]["shifts"][car.home_vertical]["hours"]
            u = rng.random()
            cumulative = 0.0
            kind = None
            for t in EVENT_TYPES:
                cumulative += cfg[t]["rate"]
                if u < cumulative:
                    kind = t
                    break
            if kind is None:
                continue
            c = cfg[kind]
            until: Optional[datetime] = None
            if kind == "breakdown":
                at = shift_start + timedelta(minutes=rng.randrange(shift_len * 60))
                lo, hi = c["repair_h"]
                if rng.random() >= c["out_for_day_share"]:
                    until = at + timedelta(minutes=rng.randint(lo * 60, hi * 60))
            elif kind == "late_start":
                at = shift_start - timedelta(minutes=rng.randint(*c["notice_min"]))
                until = shift_start + timedelta(minutes=rng.randint(*c["delay_min"]))
            else:
                at = shift_start - timedelta(minutes=rng.randint(*c["notice_min"]))
            events.append(FleetEvent(date=day, car_id=car.car_id, type=kind, at=at, until=until))
    events.sort(key=lambda e: (e.date, e.at, e.car_id))
    for i, e in enumerate(events, start=1):
        e.event_id = "FE-{:04d}".format(i)
    return events
