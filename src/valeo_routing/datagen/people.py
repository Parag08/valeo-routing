"""Drivers (one per car), staff (nurses and babysitters) and clients."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from .draw import pick, pick_many_without_replacement, pick_weighted
from .geo import place_in_area
from .reference import Area, Reference
from .schema import ROLES, TIME_FMT, VERTICALS, WEEKDAYS


@dataclass
class Driver:
    driver_id: str
    name: str
    car_id: str
    shift_start: str
    shift_end: str
    home_area_id: str


@dataclass
class Staff:
    staff_id: str
    name: str
    role: str
    vertical: str
    home_area_id: str
    home_lat: float
    home_lon: float
    languages: str
    works_days: Tuple[str, ...]


@dataclass
class Client:
    client_id: str
    area_id: str
    lat: float
    lon: float
    building_type: str
    access_note: str
    services: Tuple[str, ...]


def draw_names(rng: random.Random, ref: Reference, k: int) -> List[str]:
    """`k` distinct synthetic names from names.csv."""
    if k > len(ref.names):
        raise ValueError("names.csv has {} names but {} people are needed".format(len(ref.names), k))
    return rng.sample(ref.names, k)


def _area_by_weight(rng: random.Random, areas: List[Area], key: str) -> Area:
    return pick_weighted(rng, areas, [a.weights[key] for a in areas])


def shift_bounds(ref: Reference, vertical: str) -> Tuple[str, str]:
    """Contracted shift start and end (HH:MM) for a car's home vertical."""
    shift = ref.profile["drivers"]["shifts"][vertical]
    start = datetime.strptime(shift["start"], TIME_FMT)
    end = start + timedelta(hours=shift["hours"])
    return start.strftime(TIME_FMT), end.strftime(TIME_FMT)


def make_drivers(rng: random.Random, ref: Reference, names: List[str]) -> List[Driver]:
    """One driver per car with that car's vertical shift (A5)."""
    drivers = []
    for i, car in enumerate(ref.fleet, start=1):
        start, end = shift_bounds(ref, car.home_vertical)
        drivers.append(
            Driver(
                driver_id="DRV-{:02d}".format(i),
                name=names[i - 1],
                car_id=car.car_id,
                shift_start=start,
                shift_end=end,
                home_area_id=_area_by_weight(rng, ref.areas, "staff_home").area_id,
            )
        )
    return drivers


def make_staff(rng: random.Random, ref: Reference, counts: Dict[str, int], names: List[str]) -> List[Staff]:
    """Nurses and babysitters with jittered homes and six-of-seven working days."""
    cfg = ref.profile["staff"]
    rest_days = len(WEEKDAYS) - cfg["work_days_per_week"]
    staff = []
    name_iter = iter(names)
    for role, prefix, vertical in ROLES:
        for i in range(1, counts[role] + 1):
            area = _area_by_weight(rng, ref.areas, "staff_home")
            lat, lon = place_in_area(rng, area, ref.service_area, ref.profile["geo"]["max_resample"])
            off = set(pick_many_without_replacement(rng, cfg["rest_day_weights"], rest_days))
            staff.append(
                Staff(
                    staff_id="{}-{:03d}".format(prefix, i),
                    name=next(name_iter),
                    role=role,
                    vertical=vertical,
                    home_area_id=area.area_id,
                    home_lat=lat,
                    home_lon=lon,
                    languages=pick(rng, cfg["languages"][role]),
                    works_days=tuple(d for d in WEEKDAYS if d not in off),
                )
            )
    return staff


def make_clients(rng: random.Random, ref: Reference, total: int) -> List[Client]:
    """Clients placed by their main vertical's area weights, with building type and access note."""
    cfg = ref.profile["clients"]
    clients = []
    for i in range(1, total + 1):
        primary = pick(rng, cfg["primary_mix"])
        services = {primary}
        if rng.random() < cfg["second_service_prob"]:
            services.add(rng.choice([v for v in VERTICALS if v != primary]))
        area = _area_by_weight(rng, ref.areas, primary)
        lat, lon = place_in_area(rng, area, ref.service_area, ref.profile["geo"]["max_resample"])
        villa_share = cfg["villa_share_by_area"].get(area.area_id, cfg["villa_share_default"])
        building = "villa" if rng.random() < villa_share else "apartment"
        clients.append(
            Client(
                client_id="CL-{:04d}".format(i),
                area_id=area.area_id,
                lat=lat,
                lon=lon,
                building_type=building,
                access_note=pick(rng, cfg["access_notes"][building]),
                services=tuple(v for v in VERTICALS if v in services),
            )
        )
    return clients
