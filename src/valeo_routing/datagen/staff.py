"""Staff (nurses and drivers) and their day-by-day availability."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from .draw import pick, pick_weighted
from .geo import place_in_area
from .reference import Area, Reference
from .schema import WEEKDAYS


@dataclass
class Staff:
    staff_id: str
    name: str
    role: str  # nurse / driver
    iv_certified: bool
    home_area_id: str
    home_lat: float
    home_lon: float
    rest_day: str
    shift_pref: str
    usual_car_id: Optional[str]


@dataclass
class Availability:
    date: date
    staff_id: str
    status: str  # available / rest / sick / leave
    known_at: Optional[datetime]


def draw_names(rng: random.Random, ref: Reference, k: int) -> List[str]:
    """`k` distinct synthetic names from names.csv."""
    if k > len(ref.names):
        raise ValueError("names.csv has {} names but {} people are needed".format(len(ref.names), k))
    return rng.sample(ref.names, k)


def area_by_weight(rng: random.Random, areas: List[Area], key: str) -> Area:
    return pick_weighted(rng, areas, [a.weights[key] for a in areas])


def make_staff(rng: random.Random, ref: Reference, n_nurses: int, n_drivers: int) -> List[Staff]:
    """Nurses first, then drivers; each driver has a usual car (S3)."""
    cars = [c.car_id for c in ref.fleet if c.status == "active"]
    if n_drivers > len(cars):
        raise ValueError("{} drivers but only {} active cars in fleet.csv".format(n_drivers, len(cars)))
    cfg = ref.profile["staff"]
    max_resample = ref.profile["geo"]["max_resample"]
    names = draw_names(rng, ref, n_nurses + n_drivers)
    certified = set(rng.sample(range(n_nurses), int(round(cfg["nurses_iv_certified_share"] * n_nurses))))

    staff = []
    for role, prefix, count in (("nurse", "NUR", n_nurses), ("driver", "DRV", n_drivers)):
        for i in range(1, count + 1):
            area = area_by_weight(rng, ref.areas, "staff_home")
            lat, lon = place_in_area(rng, area, ref.service_area, max_resample)
            staff.append(
                Staff(
                    staff_id="{}-{:03d}".format(prefix, i),
                    name=names.pop(0),
                    role=role,
                    iv_certified=role == "nurse" and (i - 1) in certified,
                    home_area_id=area.area_id,
                    home_lat=lat,
                    home_lon=lon,
                    rest_day=pick(rng, cfg["rest_day_weights"]),
                    shift_pref=pick(rng, cfg["shift_pref_weights"]),
                    usual_car_id=cars[i - 1] if role == "driver" else None,
                )
            )
    return staff


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))


def make_availability(
    rng: random.Random, ref: Reference, staff: List[Staff], start: date, days: int
) -> List[Availability]:
    """One row per staff member per day: rest day, sick, leave or available."""
    cfg = ref.profile["availability"]
    rows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        weekday = WEEKDAYS[day.weekday()]
        for person in staff:
            if weekday == person.rest_day:
                known = _at(day - timedelta(days=cfg["rest_notice_days"]), cfg["notice_hour"])
                rows.append(Availability(day, person.staff_id, "rest", known))
                continue
            r = rng.random()
            if r < cfg["p_sick"]:
                if rng.random() < cfg["sick_known_same_morning_share"]:
                    lo, hi = cfg["sick_known_hour_range"]
                    known = _at(day, rng.randint(lo, hi - 1), rng.randrange(60))
                else:
                    lo, hi = cfg["sick_known_evening_before_hour_range"]
                    known = _at(day - timedelta(days=1), rng.randint(lo, hi - 1), rng.randrange(60))
                rows.append(Availability(day, person.staff_id, "sick", known))
            elif r < cfg["p_sick"] + cfg["p_leave"]:
                lo, hi = cfg["leave_notice_days_range"]
                known = _at(day - timedelta(days=rng.randint(lo, hi)), cfg["notice_hour"])
                rows.append(Availability(day, person.staff_id, "leave", known))
            else:
                rows.append(Availability(day, person.staff_id, "available", None))
    return rows
