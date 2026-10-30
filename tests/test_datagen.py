"""Generator contract (v0, three verticals): determinism, schema, and the rules in docs/archive/DATA_v0.md. Replaced in PLAN step 1."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

import pytest
from pydantic import ValidationError

from valeo_routing.datagen.generate import generate, write
from valeo_routing.datagen.geo import haversine_m
from valeo_routing.datagen.schema import COLUMNS
from valeo_routing.settings import Settings

from .conftest import ROOT, make_settings, read_csv

DUBAI_LAT = (24.75, 25.40)
DUBAI_LON = (54.90, 55.60)


def ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def data_md_columns() -> dict:
    """Column names per generated file, parsed from the tables in docs/DATA.md."""
    text = (ROOT / "docs" / "archive" / "DATA_v0.md").read_text(encoding="utf-8")
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


def test_same_seed_gives_identical_bytes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write(generate(make_settings(a)), a)
    write(generate(make_settings(b)), b)
    for name in COLUMNS:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_columns_match_data_md(written):
    expected = data_md_columns()
    for name, cols in COLUMNS.items():
        assert cols == expected[name], name
        header = (written / name).read_text(encoding="utf-8").splitlines()[0].split(",")
        assert header == cols, name


def test_no_staff_double_booking(written, profile):
    """Overlapping bookings per staff member never exceed the vertical's limit (1 for shifts)."""
    by_staff = defaultdict(list)
    for r in read_csv(written / "appointments.csv"):
        assert r["staff_id"], r["appt_id"]
        by_staff[(r["staff_id"], r["vertical"])].append((ts(r["start"]), ts(r["end"])))
    for (staff_id, vertical), spans in by_staff.items():
        limit = profile["verticals"][vertical]["staff_max_concurrent"]
        points = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans], key=lambda p: (p[0], p[1]))
        level = 0
        for _, delta in points:
            level += delta
            assert level <= limit, staff_id


def test_fast_tracks_booked_same_day_with_notice(written, profile):
    lo, hi = profile["verticals"]["sample"]["fast_track"]["notice_min"]
    fast = [r for r in read_csv(written / "appointments.csv") if r["priority"] == "fast_track"]
    assert fast
    for r in fast:
        start, booked = ts(r["start"]), ts(r["booked_at"])
        assert r["vertical"] == "sample"
        assert booked.date() == start.date()
        assert lo <= (start - booked).total_seconds() / 60 <= hi


def test_routine_booked_before_start(written):
    for r in read_csv(written / "appointments.csv"):
        assert ts(r["booked_at"]) < ts(r["start"]), r["appt_id"]


def test_sample_lab_is_nearest(written):
    labs = read_csv(ROOT / "data" / "reference" / "labs.csv")
    clients = {c["client_id"]: c for c in read_csv(written / "clients.csv")}
    for r in read_csv(written / "appointments.csv"):
        if r["vertical"] != "sample":
            continue
        c = clients[r["client_id"]]
        dist = {l["lab_id"]: haversine_m(float(c["lat"]), float(c["lon"]), float(l["lat"]), float(l["lon"])) for l in labs}
        assert r["lab_id"] == min(dist, key=lambda k: (dist[k], k))


def test_points_inside_dubai(written):
    points = [(c["lat"], c["lon"]) for c in read_csv(written / "clients.csv")]
    points += [(s["home_lat"], s["home_lon"]) for s in read_csv(written / "staff.csv")]
    for lat, lon in points:
        assert DUBAI_LAT[0] <= float(lat) <= DUBAI_LAT[1]
        assert DUBAI_LON[0] <= float(lon) <= DUBAI_LON[1]


def test_cancelled_before_start(written):
    rows = read_csv(written / "appointments.csv")
    cancelled = [r for r in rows if r["status"] == "cancelled"]
    assert cancelled
    for r in rows:
        if r["status"] == "cancelled":
            assert ts(r["booked_at"]) < ts(r["cancelled_at"]) < ts(r["start"])
        else:
            assert r["cancelled_at"] == ""


def test_settings_fail_fast_on_missing_key(tmp_path, monkeypatch):
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    keys = [l.split("=", 1)[0] for l in lines if "=" in l and not l.startswith("#")]
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("\n".join(l for l in lines if not l.startswith("CLIENTS_TOTAL=")), encoding="utf-8")
    with pytest.raises(ValidationError, match="clients_total"):
        Settings(_env_file=str(env))
