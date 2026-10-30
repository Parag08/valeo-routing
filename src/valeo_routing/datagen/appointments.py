"""Daily bookings per vertical, staff assignment and booking outcomes."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .draw import count_for_day, pick, pick_weighted
from .geo import haversine_m
from .people import Client, Staff
from .reference import Lab, Reference
from .schema import VERTICALS, WEEKDAYS


@dataclass
class Appointment:
    service_date: date
    vertical: str
    client_id: str
    start: datetime
    end: datetime
    service_min: int
    needs_dropoff: bool
    needs_pickup: bool
    priority: str
    booked_at: datetime
    channel: str
    payer: str
    notes: str
    test_type: str = ""
    fasting: Optional[bool] = None
    sample_max_min: Optional[int] = None
    lab_id: str = ""
    staff_id: str = ""
    status: str = "confirmed"
    cancelled_at: Optional[datetime] = None
    appt_id: str = ""
    # Other (start, end) windows the booking may be moved to if no staff is free.
    alternatives: List[Tuple[datetime, datetime]] = field(default_factory=list, repr=False)


def nearest_lab(labs: List[Lab], lat: float, lon: float) -> Lab:
    """Closest lab by great-circle distance (ties broken by lab_id)."""
    return min(labs, key=lambda l: (haversine_m(lat, lon, l.lat, l.lon), l.lab_id))


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day)


def _routine_booked_at(rng: random.Random, profile: dict, cfg: dict, day: date) -> datetime:
    lead = int(pick(rng, cfg["lead_time_days"]))
    first, last = profile["booking_hours"]
    return _midnight(day - timedelta(days=lead)) + timedelta(
        hours=rng.randrange(first, last), minutes=rng.randrange(60)
    )


def _timed_booking(rng: random.Random, ref: Reference, vertical: str, day: date, client: Client) -> Appointment:
    """Nursing or babysitting: a block of hours with the staff member on site."""
    cfg = ref.profile["verticals"][vertical]
    kinds = cfg["bookings"]
    kind = pick_weighted(rng, kinds, [k["weight"] for k in kinds])
    hours = int(pick(rng, kind["duration_h_weights"]))
    minute = int(pick(rng, kind["start_minute_weights"]))
    start_weights = kind["start_hour_weights"]
    latest = kind.get("latest_end_hour")
    if latest is not None:
        start_weights = {
            h: w for h, w in start_weights.items() if int(h) * 60 + minute + hours * 60 <= latest * 60
        }
    hour = int(pick(rng, start_weights))
    start = _midnight(day) + timedelta(hours=hour, minutes=minute)
    end = start + timedelta(hours=hours)
    return Appointment(
        service_date=day,
        vertical=vertical,
        client_id=client.client_id,
        start=start,
        end=end,
        service_min=hours * 60,
        needs_dropoff=rng.random() < kind["dropoff_share"],
        needs_pickup=rng.random() < kind["pickup_share"],
        priority="routine",
        booked_at=_routine_booked_at(rng, ref.profile, cfg, day),
        channel=pick(rng, cfg["channel_mix"]),
        payer=pick(rng, cfg["payer_mix"]),
        notes=kind["note"] if kind["note"] is not None else pick(rng, cfg["notes"]),
    )


def _sample_booking(rng: random.Random, ref: Reference, day: date, client: Client) -> Appointment:
    """A sample collection: a slot window, a short visit, and a lab the sample must reach."""
    cfg = ref.profile["verticals"]["sample"]
    ft = cfg["fast_track"]
    slot = timedelta(minutes=cfg["slot_min"])
    test = pick(rng, {k: v["weight"] for k, v in cfg["tests"].items()})
    spec = cfg["tests"][test]
    base = _midnight(day)

    if rng.random() < ft["share"]:
        priority = "fast_track"
        start = base + timedelta(
            hours=int(pick(rng, ft["start_hour_weights"])),
            minutes=int(pick(rng, ft["start_minute_weights"])),
        )
        booked_at = start - timedelta(minutes=rng.randint(*ft["notice_min"]))
        alternatives = []
    else:
        priority = "routine"
        hours = {
            h: w for h, w in cfg["slot_hour_weights"].items()
            if not spec["fasting"] or int(h) <= cfg["fasting_latest_slot_hour"]
        }
        hour = int(pick(rng, hours))
        start = base + timedelta(hours=hour)
        booked_at = _routine_booked_at(rng, ref.profile, cfg, day)
        alternatives = []
        for step in range(1, cfg["slot_search_max_shift_h"] + 1):
            for h in (hour - step, hour + step):
                if str(h) in hours:
                    alt = base + timedelta(hours=h)
                    alternatives.append((alt, alt + slot))

    lab = nearest_lab(ref.labs, client.lat, client.lon)
    lo, hi = cfg["service_min"]
    return Appointment(
        service_date=day,
        vertical="sample",
        client_id=client.client_id,
        start=start,
        end=start + slot,
        service_min=rng.randint(lo, hi),
        needs_dropoff=False,
        needs_pickup=False,
        priority=priority,
        booked_at=booked_at,
        channel=pick(rng, cfg["channel_mix"]),
        payer=pick(rng, cfg["payer_mix"]),
        notes=pick(rng, cfg["notes"]),
        test_type=test,
        fasting=spec["fasting"],
        sample_max_min=spec["sample_max_min"],
        lab_id=lab.lab_id,
        alternatives=alternatives,
    )


class StaffBook:
    """Who is busy when, and who has served whom, across the whole horizon."""

    def __init__(self, staff: List[Staff], turnaround_min: Dict[str, int], max_concurrent: Dict[str, int]):
        self.by_vertical: Dict[str, List[Staff]] = {v: [s for s in staff if s.vertical == v] for v in VERTICALS}
        self.turnaround = {v: timedelta(minutes=m) for v, m in turnaround_min.items()}
        self.max_concurrent = max_concurrent
        self.busy: Dict[str, List[Tuple[datetime, datetime]]] = {s.staff_id: [] for s in staff}
        self.served: Dict[Tuple[str, str], int] = {}

    def _free(self, staff_id: str, vertical: str, start: datetime, blocked_until: datetime) -> bool:
        overlapping = sum(1 for s, e in self.busy[staff_id] if s < blocked_until and start < e)
        return overlapping < self.max_concurrent[vertical]

    def assign(self, rng: random.Random, appt: Appointment, start: datetime, end: datetime) -> Optional[str]:
        """Pick a free staff member: working that day first, then on a rest day; prefer continuity."""
        blocked_until = end + self.turnaround[appt.vertical]
        weekday = WEEKDAYS[start.weekday()]
        free = [s for s in self.by_vertical[appt.vertical] if self._free(s.staff_id, appt.vertical, start, blocked_until)]
        on_duty = [s for s in free if weekday in s.works_days]
        pool = on_duty or free
        if not pool:
            return None
        best = max(self.served.get((s.staff_id, appt.client_id), 0) for s in pool)
        if best > 0:
            pool = [s for s in pool if self.served.get((s.staff_id, appt.client_id), 0) == best]
        chosen = rng.choice(pool)
        self.busy[chosen.staff_id].append((start, blocked_until))
        key = (chosen.staff_id, appt.client_id)
        self.served[key] = self.served.get(key, 0) + 1
        return chosen.staff_id


def _set_outcome(rng: random.Random, cfg: dict, appt: Appointment) -> None:
    u = rng.random()
    if u < cfg["cancel_rate"]:
        appt.status = "cancelled"
        window = int((appt.start - appt.booked_at).total_seconds() // 60)
        appt.cancelled_at = appt.booked_at + timedelta(minutes=rng.randint(1, max(1, window - 1)))
    elif u < cfg["cancel_rate"] + cfg["no_show_rate"]:
        appt.status = "no_show"


def make_appointments(
    rng: random.Random,
    ref: Reference,
    clients: List[Client],
    staff: List[Staff],
    start_date: date,
    days: int,
    volumes: Dict[str, float],
) -> Tuple[List[Appointment], Dict[str, int]]:
    """Generate, staff and number bookings for each day. Returns (appointments, declined per vertical)."""
    profile = ref.profile
    book = StaffBook(
        staff,
        {v: profile["verticals"][v]["staff_turnaround_min"] for v in VERTICALS},
        {v: profile["verticals"][v]["staff_max_concurrent"] for v in VERTICALS},
    )
    by_service = {v: [c for c in clients if v in c.services] for v in VERTICALS}
    declined = {v: 0 for v in VERTICALS}
    result: List[Appointment] = []

    for offset in range(days):
        day = start_date + timedelta(days=offset)
        mult = profile["weekday_multipliers"][WEEKDAYS[day.weekday()]]
        requests: List[Appointment] = []
        for v in VERTICALS:
            n = count_for_day(rng, volumes[v] * mult, profile["volume_noise_sd_factor"])
            for client in rng.sample(by_service[v], min(n, len(by_service[v]))):
                if v == "sample":
                    requests.append(_sample_booking(rng, ref, day, client))
                else:
                    requests.append(_timed_booking(rng, ref, v, day, client))

        # Bookings are staffed in the order they were made.
        requests.sort(key=lambda a: (a.booked_at, VERTICALS.index(a.vertical), a.client_id))
        staffed: List[Appointment] = []
        for appt in requests:
            for start, end in [(appt.start, appt.end)] + appt.alternatives:
                staff_id = book.assign(rng, appt, start, end)
                if staff_id:
                    appt.staff_id, appt.start, appt.end = staff_id, start, end
                    break
            if not appt.staff_id:
                declined[appt.vertical] += 1
                continue
            _set_outcome(rng, profile["verticals"][appt.vertical], appt)
            staffed.append(appt)

        staffed.sort(key=lambda a: (a.start, VERTICALS.index(a.vertical), a.client_id))
        for i, appt in enumerate(staffed, start=1):
            appt.appt_id = "AP-{}-{:04d}".format(day.strftime("%Y%m%d"), i)
        result.extend(staffed)
    return result, declined
