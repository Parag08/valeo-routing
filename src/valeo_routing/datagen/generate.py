"""Run the whole generator and write the CSVs."""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

from ..settings import Settings
from .events import Event, make_events
from .orders import Order, make_orders
from .reference import Reference, load_reference
from .schema import COLUMNS, COORD_DECIMALS, DATE_FMT, DATETIME_FMT
from .staff import Availability, Staff, make_availability, make_staff


@dataclass
class Dataset:
    staff: List[Staff]
    availability: List[Availability]
    orders: List[Order]
    events: List[Event]
    reference: Reference


def generate(settings: Settings) -> Dataset:
    """Build every table from one random.Random seeded from settings."""
    rng = random.Random(settings.data_seed)
    ref = load_reference(settings.data_reference_dir, settings.demand_profile_path)
    staff = make_staff(rng, ref, settings.staff_nurses, settings.staff_drivers)
    availability = make_availability(rng, ref, staff, settings.data_start_date, settings.data_days)
    orders = make_orders(rng, ref, settings.data_start_date, settings.data_days, settings.orders_per_day)
    events = make_events(rng, ref, staff, availability, settings.data_start_date, settings.data_days)
    return Dataset(staff, availability, orders, events, ref)


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
        "staff.csv": sorted(data.staff, key=lambda s: s.staff_id),
        "availability.csv": sorted(data.availability, key=lambda a: (a.date, a.staff_id)),
        "orders.csv": sorted(data.orders, key=lambda o: o.order_id),
        "events.csv": sorted(data.events, key=lambda e: e.event_id),
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
