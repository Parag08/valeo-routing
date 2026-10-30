"""The partner order feed: what the platform publishes, when, and for whom."""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

from .draw import count_for_day, pick, pick_weighted
from .geo import haversine_m, place_in_area
from .reference import Lab, Reference, Service
from .schema import WEEKDAYS
from .staff import area_by_weight


@dataclass
class Order:
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


@dataclass
class _Patient:
    ref: str
    area_id: str
    lat: float
    lon: float


def nearest_lab(labs: List[Lab], lat: float, lon: float) -> Lab:
    """The closest lab by straight-line distance; ties go to the lower lab_id."""
    return min(labs, key=lambda l: (haversine_m(lat, lon, l.lat, l.lon), l.lab_id))


def _draw_slot(rng: random.Random, profile: dict, day: date, lab: Optional[Lab]) -> datetime:
    """A quarter-hour slot start; for lab services, early enough to still reach the lab before it closes."""
    margin = timedelta(minutes=profile["lab_cutoff_margin_min"])
    for _ in range(profile["slot_max_redraws"]):
        hour = int(pick(rng, profile["slot_hour_weights"]))
        minute = int(pick(rng, profile["slot_minute_weights"]))
        slot = datetime.combine(day, time(hour, minute))
        if lab is None or slot <= datetime.combine(day, lab.closes) - margin:
            return slot
    raise ValueError("No slot before {} close after {} draws".format(lab.lab_id, profile["slot_max_redraws"]))


def _draw_lead(rng: random.Random, profile: dict, slot: datetime) -> timedelta:
    """Time between publishing and the slot; redrawn until it lands at an hour patients book at."""
    buckets = profile["lead_time_h"]
    hour_weights = {int(h): w for h, w in profile["publish_hour_weights"].items()}
    top = max(hour_weights.values())
    for _ in range(profile["lead_max_redraws"]):
        bucket = pick_weighted(rng, buckets, [b["weight"] for b in buckets])
        lead = timedelta(minutes=max(1, int(round(rng.uniform(bucket["min_h"], bucket["max_h"]) * 60))))
        if rng.random() < hour_weights[(slot - lead).hour] / top:
            return lead
    raise ValueError("No lead time accepted after {} draws".format(profile["lead_max_redraws"]))


def _cancellation(rng: random.Random, profile: dict, service: Service, lead: timedelta,
                  published: datetime, slot: datetime) -> Optional[datetime]:
    cfg = profile["cancellation"]
    lead_h = lead.total_seconds() / 3600.0
    multiplier = next(
        (b["multiplier"] for b in cfg["lead_multiplier"] if lead_h <= b["max_lead_h"]),
        cfg["lead_multiplier"][-1]["multiplier"],
    )
    p = cfg["base_rate"] * multiplier * cfg["service_multiplier"][service.category]
    if rng.random() >= p:
        return None
    lo, hi = cfg["fraction_range"]
    cancelled = published + (slot - published) * rng.uniform(lo, hi)
    cancelled = cancelled.replace(second=0, microsecond=0)
    return min(max(cancelled, published + timedelta(minutes=1)), slot - timedelta(minutes=1))


def make_orders(
    rng: random.Random, ref: Reference, start: date, days: int, orders_per_day: float
) -> List[Order]:
    """Every order for the service days, with publish time, location, lab and cancellation."""
    profile = ref.profile
    services = ref.services
    cutoff_hour = profile["supplies"]["prep_cutoff_hour"]
    claim = profile["competitor_claim_min"]
    max_resample = profile["geo"]["max_resample"]
    patients: List[_Patient] = []
    history: List[_Patient] = []  # one entry per order, so repeat patients are drawn by past orders
    by_day: Dict[date, List[Order]] = defaultdict(list)

    for offset in range(days):
        day = start + timedelta(days=offset)
        mean = orders_per_day * profile["weekday_multipliers"][WEEKDAYS[day.weekday()]]
        for _ in range(count_for_day(rng, mean, profile["volume_noise_sd_factor"])):
            service = pick_weighted(rng, services, [s.mix_weight for s in services])
            if history and rng.random() < profile["patients"]["repeat_share"]:
                patient = rng.choice(history)
            else:
                area = area_by_weight(rng, ref.areas, "orders")
                lat, lon = place_in_area(rng, area, ref.service_area, max_resample)
                patient = _Patient("PT-{:05d}".format(len(patients) + 1), area.area_id, lat, lon)
                patients.append(patient)
            history.append(patient)

            lab = nearest_lab(ref.labs, patient.lat, patient.lon) if service.needs_lab else None
            slot = _draw_slot(rng, profile, day, lab)
            lead = _draw_lead(rng, profile, slot)
            published = slot - lead
            ready = (not service.needs_office_supplies) or published < datetime.combine(
                day - timedelta(days=1), time(cutoff_hour)
            )
            by_day[day].append(
                Order(
                    order_id="",
                    published_at=published,
                    slot_start=slot,
                    service_id=service.service_id,
                    area_id=patient.area_id,
                    lat=patient.lat,
                    lon=patient.lon,
                    patient_ref=patient.ref,
                    lab_id=lab.lab_id if lab else None,
                    supplies_ready=ready,
                    competitor_claim_min=int(round(rng.triangular(claim["lo"], claim["hi"], claim["mode"]))),
                    cancelled_at=_cancellation(rng, profile, service, lead, published, slot),
                )
            )

    orders = []
    for day, day_orders in sorted(by_day.items()):
        day_orders.sort(key=lambda o: (o.published_at, o.slot_start, o.patient_ref))
        for i, order in enumerate(day_orders, start=1):
            order.order_id = "OR-{}-{:04d}".format(day.strftime("%Y%m%d"), i)
        orders.extend(day_orders)
    return orders
