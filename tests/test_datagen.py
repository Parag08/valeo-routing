"""Generator contract: determinism, schema, location rules and the data rules in docs/DATA.md."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from valeo_routing.datagen.generate import generate, write
from valeo_routing.datagen.geo import haversine_m
from valeo_routing.datagen.schema import COLUMNS, WEEKDAYS
from valeo_routing.service_area import ServiceArea
from valeo_routing.settings import Settings

from .conftest import ROOT, make_settings, read_csv

REF = ROOT / "data" / "reference"
SERVED = {"Dubai", "Sharjah", "Ajman", "Umm Al Quwain", "Ras Al Khaimah", "Fujairah"}


def ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def day_of(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def flag(value: str) -> bool:
    assert value in ("true", "false"), value
    return value == "true"


def data_md_columns() -> dict:
    """Column names per generated file, parsed from the tables in docs/DATA.md."""
    text = (ROOT / "docs" / "DATA.md").read_text(encoding="utf-8")
    out = {}
    for name in COLUMNS:
        section = text.split("### {}".format(name), 1)[1].split("###", 1)[0]
        cols = []
        for line in section.splitlines():
            m = re.match(r"\|\s*([a-z_, ]+?)\s*\|", line)
            if m and m.group(1) != "column":
                cols.extend(c.strip() for c in m.group(1).split(","))
        out[name] = cols
    return out


@pytest.fixture(scope="session")
def services():
    return {r["service_id"]: r for r in read_csv(REF / "services.csv")}


@pytest.fixture(scope="session")
def labs():
    return {r["lab_id"]: r for r in read_csv(REF / "labs.csv")}


@pytest.fixture(scope="session")
def orders(written):
    return read_csv(written / "orders.csv")


@pytest.fixture(scope="session")
def staff(written):
    return read_csv(written / "staff.csv")


@pytest.fixture(scope="session")
def availability(written):
    return read_csv(written / "availability.csv")


@pytest.fixture(scope="session")
def service_area():
    return ServiceArea(REF / "service_area.geojson")


# --- determinism and schema -------------------------------------------------------------------


def test_same_seed_gives_identical_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(generate(make_settings(a)), a)
    write(generate(make_settings(b)), b)
    for name in COLUMNS:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_different_seed_gives_different_orders(tmp_path):
    s = make_settings(tmp_path)
    other = Settings(**{**s.model_dump(), "data_seed": s.data_seed + 1})
    first, second = generate(s), generate(other)
    assert [o.slot_start for o in first.orders] != [o.slot_start for o in second.orders]


def test_columns_match_data_md(written):
    expected = data_md_columns()
    for name, cols in COLUMNS.items():
        assert cols == expected[name], name
        header = (written / name).read_text(encoding="utf-8").splitlines()[0].split(",")
        assert header == cols, name


# --- locations: land in Dubai and the northern emirates, never Abu Dhabi ----------------------


def test_service_area_covers_exactly_the_served_emirates(service_area):
    assert set(service_area.emirates) == SERVED


def test_service_area_known_places(service_area):
    assert service_area.emirate_at(25.1972, 55.2744) == "Dubai"  # Burj Khalifa
    assert service_area.emirate_at(25.3250, 55.3850) == "Sharjah"  # Al Majaz
    assert service_area.emirate_at(25.4110, 55.4400) == "Ajman"
    assert service_area.emirate_at(25.1200, 56.3300) == "Fujairah"
    assert service_area.emirate_at(24.4500, 54.3800) is None  # Abu Dhabi city: not served
    assert service_area.emirate_at(24.2100, 55.7400) is None  # Al Ain: not served
    assert service_area.emirate_at(25.2800, 56.3200) is None  # Madha: Oman
    assert service_area.emirate_at(25.2100, 55.2200) is None  # sea off Jumeirah
    assert service_area.emirate_at(25.1180, 55.1280) is None  # water between the Palm's fronds


def test_reference_points_on_land_in_their_emirate(service_area):
    for row in read_csv(REF / "areas.csv"):
        assert row["emirate"] in SERVED, row["area_id"]
        assert service_area.emirate_at(float(row["lat"]), float(row["lon"])) == row["emirate"], row["area_id"]
    for name in ("office.csv", "labs.csv"):
        for row in read_csv(REF / name):
            assert service_area.contains(float(row["lat"]), float(row["lon"])), row


def test_generated_points_on_land_in_their_area_emirate(orders, staff, service_area):
    emirate_of = {r["area_id"]: r["emirate"] for r in read_csv(REF / "areas.csv")}
    points = [(o["area_id"], o["lat"], o["lon"]) for o in orders]
    points += [(s["home_area_id"], s["home_lat"], s["home_lon"]) for s in staff]
    for area_id, lat, lon in points:
        assert service_area.emirate_at(float(lat), float(lon)) == emirate_of[area_id], (area_id, lat, lon)


# --- reference integrity ----------------------------------------------------------------------


def test_foreign_keys_resolve(written, orders, staff, availability, services, labs):
    areas = {r["area_id"] for r in read_csv(REF / "areas.csv")}
    cars = {r["car_id"] for r in read_csv(REF / "fleet.csv")}
    staff_ids = {s["staff_id"] for s in staff}
    assert {o["service_id"] for o in orders} <= set(services)
    assert {o["area_id"] for o in orders} <= areas
    assert {o["lab_id"] for o in orders if o["lab_id"]} <= set(labs)
    assert {s["home_area_id"] for s in staff} <= areas
    assert {s["usual_car_id"] for s in staff if s["usual_car_id"]} <= cars
    assert {a["staff_id"] for a in availability} <= staff_ids
    for e in read_csv(written / "events.csv"):
        assert (e["staff_id"] in staff_ids) if e["staff_id"] else (e["car_id"] in cars), e


# --- orders -----------------------------------------------------------------------------------


def test_order_ids_are_numbered_by_service_date_in_publish_order(orders):
    by_day = defaultdict(list)
    for o in orders:
        m = re.fullmatch(r"OR-(\d{8})-(\d{4})", o["order_id"])
        assert m, o["order_id"]
        assert m.group(1) == ts(o["slot_start"]).strftime("%Y%m%d"), o["order_id"]
        by_day[m.group(1)].append((int(m.group(2)), o))
    for rows in by_day.values():
        rows.sort(key=lambda r: r[0])
        assert [n for n, _ in rows] == list(range(1, len(rows) + 1))
        published = [ts(o["published_at"]) for _, o in rows]
        assert published == sorted(published)


def test_slots_lead_times_and_quarter_hour_grid(orders):
    for o in orders:
        slot, published = ts(o["slot_start"]), ts(o["published_at"])
        assert timedelta(minutes=30) <= slot - published <= timedelta(hours=48), o["order_id"]
        assert slot.minute in (0, 15, 30, 45)
        assert 6 <= slot.hour <= 21
    overnight = sum(1 for o in orders if not 6 <= ts(o["published_at"]).hour < 21) / len(orders)
    assert 0.03 < overnight < 0.20, overnight


def test_lab_rules(orders, services, labs, profile):
    margin = timedelta(minutes=profile["lab_cutoff_margin_min"])
    for o in orders:
        if not flag(services[o["service_id"]]["needs_lab"]):
            assert o["lab_id"] == "", o["order_id"]
            continue
        nearest = min(
            labs.values(),
            key=lambda l: (haversine_m(float(o["lat"]), float(o["lon"]), float(l["lat"]), float(l["lon"])), l["lab_id"]),
        )
        assert o["lab_id"] == nearest["lab_id"], o["order_id"]
        slot = ts(o["slot_start"])
        closes = datetime.combine(slot.date(), datetime.strptime(labs[o["lab_id"]]["closes"], "%H:%M").time())
        assert slot <= closes - margin, o["order_id"]


def test_supplies_ready_rule(orders, services, profile):
    cutoff = timedelta(hours=profile["supplies"]["prep_cutoff_hour"])
    seen_ready = seen_not_ready = False
    for o in orders:
        ready = flag(o["supplies_ready"])
        if not flag(services[o["service_id"]]["needs_office_supplies"]):
            assert ready, o["order_id"]
            continue
        day_before = datetime.combine(ts(o["slot_start"]).date() - timedelta(days=1), datetime.min.time())
        assert ready == (ts(o["published_at"]) < day_before + cutoff), o["order_id"]
        seen_ready, seen_not_ready = seen_ready or ready, seen_not_ready or not ready
    assert seen_ready and seen_not_ready


def test_competitor_claim_range(orders, profile):
    cfg = profile["competitor_claim_min"]
    for o in orders:
        assert cfg["lo"] <= int(o["competitor_claim_min"]) <= cfg["hi"], o["order_id"]


def test_cancellations(orders):
    cancelled = [o for o in orders if o["cancelled_at"]]
    assert 0.02 < len(cancelled) / len(orders) < 0.10
    for o in cancelled:
        assert ts(o["published_at"]) < ts(o["cancelled_at"]) < ts(o["slot_start"]), o["order_id"]


def test_repeat_patients_keep_their_location(orders):
    seen = {}
    repeats = 0
    for o in sorted(orders, key=lambda o: o["order_id"]):
        place = (o["area_id"], o["lat"], o["lon"])
        if o["patient_ref"] in seen:
            repeats += 1
            assert seen[o["patient_ref"]] == place, o["patient_ref"]
        seen[o["patient_ref"]] = place
    assert 0.15 < repeats / len(orders) < 0.45


def test_volume_mix_and_peaks(orders, services, settings):
    per_day = Counter(ts(o["slot_start"]).date() for o in orders)
    assert len(per_day) == settings.data_days
    weekdays = [n for d, n in per_day.items() if d.weekday() < 5]
    assert 35 <= sum(weekdays) / len(weekdays) <= 55  # S4
    mix = Counter(services[o["service_id"]]["category"] for o in orders)
    for category, share in (("sample", 0.60), ("iv", 0.30), ("injection", 0.10)):  # S5
        assert abs(mix[category] / len(orders) - share) < 0.06, category
    hours = Counter(ts(o["slot_start"]).hour for o in orders)
    morning, midday, evening = (sum(hours[h] for h in hs) for hs in (range(7, 10), range(11, 15), range(16, 18)))
    assert morning / 3 > 1.5 * midday / 4 and evening / 2 > 1.5 * midday / 4  # S7: two peaks


# --- staff, availability and events -----------------------------------------------------------


def test_staff_pool(staff, settings, profile):
    nurses = [s for s in staff if s["role"] == "nurse"]
    drivers = [s for s in staff if s["role"] == "driver"]
    assert (len(nurses), len(drivers)) == (settings.staff_nurses, settings.staff_drivers)
    assert len({s["name"] for s in staff}) == len(staff)
    assert sum(flag(s["iv_certified"]) for s in nurses) == round(profile["staff"]["nurses_iv_certified_share"] * len(nurses))
    assert not any(flag(s["iv_certified"]) for s in drivers)
    assert all(s["usual_car_id"] == "" for s in nurses)
    assert len({s["usual_car_id"] for s in drivers}) == len(drivers)
    assert {s["rest_day"] for s in staff} <= set(WEEKDAYS)
    assert {s["shift_pref"] for s in staff} <= {"day", "split", "any"}


def test_availability_rules(availability, staff, settings):
    assert len(availability) == len(staff) * settings.data_days
    rest_day = {s["staff_id"]: s["rest_day"] for s in staff}
    for a in availability:
        day = day_of(a["date"])
        midnight = datetime.combine(day, datetime.min.time())
        assert a["status"] in ("available", "rest", "sick", "leave")
        assert (a["status"] == "rest") == (WEEKDAYS[day.weekday()] == rest_day[a["staff_id"]])
        if a["status"] == "available":
            assert a["known_at"] == ""
            continue
        known = ts(a["known_at"])
        assert known < midnight + timedelta(days=1)
        if a["status"] in ("rest", "leave"):
            assert known < midnight
        if a["status"] == "sick":
            assert known >= midnight - timedelta(hours=6)  # evening before, 18:00 at the earliest


def test_pairs_on_duty(availability, staff):
    role = {s["staff_id"]: s["role"] for s in staff}
    per_day = defaultdict(Counter)
    for a in availability:
        if a["status"] == "available":
            per_day[a["date"]][role[a["staff_id"]]] += 1
    pairs = [min(c["nurse"], c["driver"]) for c in per_day.values()]
    assert 8.5 <= sum(pairs) / len(pairs) <= 12  # S3
    assert min(pairs) >= 5


def test_events(written, availability):
    events = read_csv(written / "events.csv")
    sick = sorted((a["date"], a["staff_id"], a["known_at"]) for a in availability if a["status"] == "sick")
    assert sorted((e["date"], e["staff_id"], e["at"]) for e in events if e["type"] == "sick_call") == sick
    status = {(a["date"], a["staff_id"]): a["status"] for a in availability}
    assert {e["type"] for e in events} == {"sick_call", "car_breakdown", "late_start"}
    for e in events:
        assert (e["staff_id"] == "") != (e["car_id"] == "")
        if e["until"]:
            assert ts(e["until"]) > ts(e["at"])
        if e["type"] == "late_start":
            assert status[(e["date"], e["staff_id"])] == "available"
            assert e["until"]
        if e["type"] == "car_breakdown":
            assert ts(e["at"]).date() == day_of(e["date"])


def test_settings_fail_fast_on_missing_key(tmp_path, monkeypatch):
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    keys = [l.split("=", 1)[0] for l in lines if "=" in l and not l.startswith("#")]
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("\n".join(l for l in lines if not l.startswith("ORDERS_PER_DAY=")), encoding="utf-8")
    with pytest.raises(ValidationError, match="orders_per_day"):
        Settings(_env_file=str(env))
