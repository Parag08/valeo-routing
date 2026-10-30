"""Run the whole generator and write the CSVs."""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..settings import Settings
from .appointments import Appointment, make_appointments
from .fleet_events import FleetEvent, make_fleet_events
from .people import Client, Driver, Staff, draw_names, make_clients, make_drivers, make_staff
from .reference import load_reference
from .schema import COLUMNS, COORD_DECIMALS, DATE_FMT, DATETIME_FMT


@dataclass
class Dataset:
    drivers: List[Driver]
    staff: List[Staff]
    clients: List[Client]
    appointments: List[Appointment]
    fleet_events: List[FleetEvent]
    declined: Dict[str, int]


def generate(settings: Settings) -> Dataset:
    """Build every table from one random.Random seeded from settings."""
    rng = random.Random(settings.data_seed)
    ref = load_reference(settings.data_reference_dir, settings.demand_profile_path)
    counts = {
        "home_nurse": settings.staff_home_nurses,
        "babysitter": settings.staff_babysitters,
        "collection_nurse": settings.staff_collection_nurses,
    }
    names = draw_names(rng, ref, len(ref.fleet) + sum(counts.values()))
    drivers = make_drivers(rng, ref, names[: len(ref.fleet)])
    staff = make_staff(rng, ref, counts, names[len(ref.fleet):])
    clients = make_clients(rng, ref, settings.clients_total)
    volumes = {
        "nursing": settings.vol_nursing_per_day,
        "babysitting": settings.vol_babysitting_per_day,
        "sample": settings.vol_sample_per_day,
    }
    appointments, declined = make_appointments(
        rng, ref, clients, staff, settings.data_start_date, settings.data_days, volumes
    )
    events = make_fleet_events(rng, ref, drivers, settings.data_start_date, settings.data_days)
    return Dataset(drivers, staff, clients, appointments, events, declined)


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return "{:.{}f}".format(value, COORD_DECIMALS)
    if isinstance(value, datetime):
        return value.strftime(DATETIME_FMT)
    if isinstance(value, date):
        return value.strftime(DATE_FMT)
    if isinstance(value, (tuple, list)):
        return ";".join(value)
    return str(value)


def _row(obj, columns: List[str]) -> List[str]:
    return [_fmt(getattr(obj, c)) for c in columns]


def tables(data: Dataset) -> Dict[str, List[List[str]]]:
    """Formatted rows per output file, in deterministic order."""
    sources = {
        "drivers.csv": sorted(data.drivers, key=lambda d: d.driver_id),
        "staff.csv": sorted(data.staff, key=lambda s: s.staff_id),
        "clients.csv": sorted(data.clients, key=lambda c: c.client_id),
        "appointments.csv": sorted(data.appointments, key=lambda a: a.appt_id),
        "fleet_events.csv": sorted(data.fleet_events, key=lambda e: e.event_id),
    }
    return {name: [_row(o, COLUMNS[name]) for o in rows] for name, rows in sources.items()}


def write(data: Dataset, output_dir: Path) -> Dict[str, int]:
    """Write every table as CSV; returns rows written per file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, rows in tables(data).items():
        with (output_dir / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(COLUMNS[name])
            w.writerows(rows)
        written[name] = len(rows)
    return written
