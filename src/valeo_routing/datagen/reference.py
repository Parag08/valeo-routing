"""Load the hand-maintained reference tables, the service area and the demand profile."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional

from valeo_routing.service_area import ServiceArea

from .schema import TIME_FMT


@dataclass(frozen=True)
class Area:
    area_id: str
    area_name: str
    emirate: str
    lat: float
    lon: float
    jitter_m: int
    weights: Dict[str, float]  # orders, staff_home


@dataclass(frozen=True)
class Office:
    office_id: str
    name: str
    area_id: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Lab:
    lab_id: str
    name: str
    area_id: str
    lat: float
    lon: float
    opens: time
    closes: time
    handover_min: int


@dataclass(frozen=True)
class Service:
    service_id: str
    name: str
    category: str
    duration_min_lo: int
    duration_min_hi: int
    needs_lab: bool
    sample_max_min: Optional[int]
    keep_cold: bool
    needs_office_supplies: bool
    iv_certified_only: bool
    mix_weight: float


@dataclass(frozen=True)
class Car:
    car_id: str
    status: str


@dataclass(frozen=True)
class Reference:
    areas: List[Area]
    office: Office
    labs: List[Lab]
    services: List[Service]
    fleet: List[Car]
    names: List[str]
    profile: dict
    service_area: ServiceArea


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _bool(value: str) -> bool:
    if value not in ("true", "false"):
        raise ValueError("expected 'true' or 'false', got {!r}".format(value))
    return value == "true"


def _time(value: str) -> time:
    return datetime.strptime(value, TIME_FMT).time()


def load_reference(reference_dir: Path, profile_path: Path) -> Reference:
    """Read areas, office, labs, services, fleet and names, the service area and the profile JSON."""
    areas = [
        Area(
            area_id=r["area_id"],
            area_name=r["area_name"],
            emirate=r["emirate"],
            lat=float(r["lat"]),
            lon=float(r["lon"]),
            jitter_m=int(r["jitter_m"]),
            weights={"orders": float(r["w_orders"]), "staff_home": float(r["w_staff_home"])},
        )
        for r in _rows(reference_dir / "areas.csv")
    ]
    offices = [
        Office(r["office_id"], r["name"], r["area_id"], float(r["lat"]), float(r["lon"]))
        for r in _rows(reference_dir / "office.csv")
    ]
    if len(offices) != 1:
        raise ValueError("office.csv must hold exactly one office, found {}".format(len(offices)))
    labs = [
        Lab(
            lab_id=r["lab_id"], name=r["name"], area_id=r["area_id"], lat=float(r["lat"]), lon=float(r["lon"]),
            opens=_time(r["opens"]), closes=_time(r["closes"]), handover_min=int(r["handover_min"]),
        )
        for r in _rows(reference_dir / "labs.csv")
    ]
    services = [
        Service(
            service_id=r["service_id"], name=r["name"], category=r["category"],
            duration_min_lo=int(r["duration_min_lo"]), duration_min_hi=int(r["duration_min_hi"]),
            needs_lab=_bool(r["needs_lab"]),
            sample_max_min=int(r["sample_max_min"]) if r["sample_max_min"] else None,
            keep_cold=_bool(r["keep_cold"]), needs_office_supplies=_bool(r["needs_office_supplies"]),
            iv_certified_only=_bool(r["iv_certified_only"]), mix_weight=float(r["mix_weight"]),
        )
        for r in _rows(reference_dir / "services.csv")
    ]
    fleet = [Car(car_id=r["car_id"], status=r["status"]) for r in _rows(reference_dir / "fleet.csv")]
    names = ["{} {}.".format(r["first_name"], r["last_initial"]) for r in _rows(reference_dir / "names.csv")]
    with profile_path.open(encoding="utf-8") as f:
        profile = json.load(f)
    return Reference(
        areas=sorted(areas, key=lambda a: a.area_id),
        office=offices[0],
        labs=sorted(labs, key=lambda l: l.lab_id),
        services=sorted(services, key=lambda s: s.service_id),
        fleet=sorted(fleet, key=lambda c: c.car_id),
        names=sorted(set(names)),
        profile=profile,
        service_area=ServiceArea(reference_dir / "service_area.geojson"),
    )
