"""Read the generated CSVs and turn orders into planning jobs."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Dict, List, Optional

from valeo_routing.datagen.reference import Reference, Service, load_reference
from valeo_routing.settings import EngineSettings

from .catalog import Catalog
from .distance import StraightLineRoad
from .model import Job, Lab
from .schedule import Context
from .standby import OfficeStandby, StandbyPolicy

DATETIME_FMT = "%Y-%m-%dT%H:%M"


@dataclass(frozen=True)
class OrderRow:
    order_id: str
    published_at: datetime
    slot_start: datetime
    service_id: str
    area_id: str
    lat: float
    lon: float
    patient_ref: str
    lab_id: Optional[str]
    supplies_ready: bool
    competitor_claim_min: int
    cancelled_at: Optional[datetime]

    @property
    def service_date(self) -> date:
        return self.slot_start.date()


@dataclass(frozen=True)
class StaffRow:
    staff_id: str
    name: str
    role: str
    iv_certified: bool
    usual_car_id: Optional[str]


@dataclass(frozen=True)
class AvailabilityRow:
    date: date
    staff_id: str
    status: str


@dataclass
class World:
    ref: Reference
    orders: List[OrderRow]
    staff: List[StaffRow]
    availability: List[AvailabilityRow]

    def orders_on(self, day: date) -> List[OrderRow]:
        return sorted((o for o in self.orders if o.service_date == day), key=lambda o: (o.published_at, o.order_id))


def _rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _dt(value: str) -> Optional[datetime]:
    return datetime.strptime(value, DATETIME_FMT) if value else None


def load_world(reference_dir: Path, profile_path: Path, sample_dir: Path) -> World:
    ref = load_reference(reference_dir, profile_path)
    orders = [
        OrderRow(
            order_id=r["order_id"], published_at=_dt(r["published_at"]), slot_start=_dt(r["slot_start"]),
            service_id=r["service_id"], area_id=r["area_id"], lat=float(r["lat"]), lon=float(r["lon"]),
            patient_ref=r["patient_ref"], lab_id=r["lab_id"] or None,
            supplies_ready=r["supplies_ready"] == "true", competitor_claim_min=int(r["competitor_claim_min"]),
            cancelled_at=_dt(r["cancelled_at"]),
        )
        for r in _rows(sample_dir / "orders.csv")
    ]
    staff = [
        StaffRow(r["staff_id"], r["name"], r["role"], r["iv_certified"] == "true", r["usual_car_id"] or None)
        for r in _rows(sample_dir / "staff.csv")
    ]
    availability = [
        AvailabilityRow(datetime.strptime(r["date"], "%Y-%m-%d").date(), r["staff_id"], r["status"])
        for r in _rows(sample_dir / "availability.csv")
    ]
    return World(ref, orders, staff, availability)


def minutes_of_day(moment: datetime, day: date) -> int:
    """Minutes after midnight of `day`; negative for earlier days."""
    return int((moment - datetime.combine(day, time.min)).total_seconds() // 60)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def engine_labs(ref: Reference) -> Dict[str, Lab]:
    return {
        l.lab_id: Lab(l.lab_id, (l.lat, l.lon), _minutes(l.opens), _minutes(l.closes), l.handover_min)
        for l in ref.labs
    }


def to_job(row: OrderRow, service: Service, catalog: Catalog) -> Job:
    day = row.service_date
    return Job(
        job_id=row.order_id,
        published_min=minutes_of_day(row.published_at, day),
        slot_min=minutes_of_day(row.slot_start, day),
        loc=(row.lat, row.lon),
        duration_min=catalog.planned_minutes(service),
        category=service.category,
        iv_certified_only=service.iv_certified_only,
        needs_kits=service.needs_office_supplies and not row.supplies_ready,
        lab_id=row.lab_id if service.needs_lab else None,
        sample_max_min=service.sample_max_min if service.needs_lab else None,
    )


def make_context(settings: EngineSettings, ref: Reference, standby: Optional[StandbyPolicy] = None) -> Context:
    office = (ref.office.lat, ref.office.lon)
    return Context(
        dist=StraightLineRoad.from_settings(settings),
        office=office,
        labs=engine_labs(ref),
        tolerance_min=settings.arrival_tolerance_min,
        access_min=settings.access_min,
        kit_stop_min=settings.office_supply_stop_min,
        min_gap_min=settings.standby_min_gap_min,
        standby=standby if standby is not None else OfficeStandby(office),
    )
