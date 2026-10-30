"""Load the hand-maintained reference tables and the demand profile."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from valeo_routing.service_area import ServiceArea


@dataclass(frozen=True)
class Area:
    area_id: str
    area_name: str
    emirate: str
    lat: float
    lon: float
    jitter_m: int
    weights: Dict[str, float]  # nursing, babysitting, sample, staff_home


@dataclass(frozen=True)
class Lab:
    lab_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Car:
    car_id: str
    home_vertical: str
    status: str


@dataclass(frozen=True)
class Reference:
    areas: List[Area]
    labs: List[Lab]
    fleet: List[Car]
    names: List[str]
    profile: dict
    service_area: ServiceArea


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_reference(reference_dir: Path, profile_path: Path) -> Reference:
    """Read areas, labs, fleet and names CSVs, the service area and the demand profile JSON."""
    areas = [
        Area(
            area_id=r["area_id"],
            area_name=r["area_name"],
            emirate=r["emirate"],
            lat=float(r["lat"]),
            lon=float(r["lon"]),
            jitter_m=int(r["jitter_m"]),
            weights={
                "nursing": float(r["w_nursing"]),
                "babysitting": float(r["w_babysitting"]),
                "sample": float(r["w_sample"]),
                "staff_home": float(r["w_staff_home"]),
            },
        )
        for r in _rows(reference_dir / "areas.csv")
    ]
    labs = [
        Lab(lab_id=r["lab_id"], name=r["name"], lat=float(r["lat"]), lon=float(r["lon"]))
        for r in _rows(reference_dir / "labs.csv")
    ]
    fleet = [
        Car(car_id=r["car_id"], home_vertical=r["home_vertical"], status=r["status"])
        for r in _rows(reference_dir / "fleet.csv")
    ]
    names = ["{} {}.".format(r["first_name"], r["last_initial"]) for r in _rows(reference_dir / "names.csv")]
    with profile_path.open(encoding="utf-8") as f:
        profile = json.load(f)
    return Reference(
        areas=sorted(areas, key=lambda a: a.area_id),
        labs=sorted(labs, key=lambda l: l.lab_id),
        fleet=sorted(fleet, key=lambda c: c.car_id),
        names=sorted(set(names)),
        profile=profile,
        service_area=ServiceArea(reference_dir / "service_area.geojson"),
    )
