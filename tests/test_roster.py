"""Roster auto-allocation: the demand curve, shift starts, pairing and the comparison with simple pairing."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from pydantic import ValidationError

from valeo_routing.datagen.reference import load_reference
from valeo_routing.engine import roster as R
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import AvailabilityRow, OrderRow, StaffRow, load_world
from valeo_routing.settings import EngineSettings

from .conftest import ROOT

DAY = date(2026, 11, 2)  # a Monday


@pytest.fixture(scope="module")
def s() -> EngineSettings:
    return EngineSettings(_env_file=str(ROOT / ".env.example"))


@pytest.fixture(scope="module")
def services(settings):
    ref = load_reference(ROOT / "data" / "reference", settings.demand_profile_path)
    return {x.service_id: x for x in ref.services}


@pytest.fixture(scope="module")
def catalog(s):
    return Catalog(s.plan_duration_position)


def order(day: date, hour: int, n: int, cancelled: bool = False) -> OrderRow:
    slot = datetime.combine(day, time(hour, 0))
    return OrderRow("OR-{}-{}-{}".format(day, hour, n), slot - timedelta(days=1), slot, "SV-11", "AR-10", 25.1, 55.2,
                    "PT-1", None, True, 120, slot - timedelta(hours=3) if cancelled else None)


def staff(role: str, i: int, iv: bool = False) -> StaffRow:
    prefix = "NUR" if role == "nurse" else "DRV"
    return StaffRow("{}-{:03d}".format(prefix, i), "Name {}".format(i), role, iv, "CAR-{:02d}".format(i) if role == "driver" else None)


def available(rows, day=DAY, status="available"):
    return [AvailabilityRow(day, r.staff_id, status) for r in rows]


# --- coverage and starts ----------------------------------------------------------------------


def test_cover_is_fractional_at_the_edges():
    hours = list(range(5, 22))
    cov = R.cover(6 * 60 + 30, 720, hours)
    assert cov[hours.index(5)] == 0 and cov[hours.index(6)] == 0.5 and cov[hours.index(12)] == 1.0
    assert cov[hours.index(18)] == 0.5 and cov[hours.index(19)] == 0
    assert sum(cov) == pytest.approx(12.0)


def demand(hours, required) -> R.Demand:
    return R.Demand(tuple(hours), tuple(required), tuple(required), tuple(required))


def test_starts_cover_a_morning_peak_and_a_late_hour(s):
    hours = list(range(5, 22))
    required = [0.0] * len(hours)
    required[hours.index(8)], required[hours.index(20)] = 1.0, 1.0
    starts = R.choose_starts(2, demand(hours, required), s)
    length = int(round(s.shift_hours * 60))
    covered = [sum(x) for x in zip(*(R.cover(st, length, hours) for st in starts))]
    assert covered[hours.index(8)] >= 1.0 and covered[hours.index(20)] >= 1.0
    assert all(st in s.roster_starts for st in starts) and starts == sorted(starts)


def test_more_pairs_go_where_the_demand_is(s):
    hours = list(range(5, 22))
    required = [0.0] * len(hours)
    for h in (8, 9, 10):
        required[hours.index(h)] = 4.0
    starts = R.choose_starts(4, demand(hours, required), s)
    length = int(round(s.shift_hours * 60))
    covered = [sum(x) for x in zip(*(R.cover(st, length, hours) for st in starts))]
    assert all(covered[hours.index(h)] == 4.0 for h in (8, 9, 10))  # every pair is on duty at the peak


def test_choose_starts_is_deterministic_and_handles_no_demand(s):
    hours = list(range(5, 22))
    flat = demand(hours, [0.0] * len(hours))
    assert R.choose_starts(3, flat, s) == R.choose_starts(3, flat, s) == [s.roster_starts[0]] * 3
    assert R.choose_starts(0, flat, s) == []


# --- expected demand --------------------------------------------------------------------------


def test_demand_uses_the_other_days_only(s, services, catalog):
    history = [order(DAY + timedelta(weeks=w), 8, i) for w, n in ((1, 2), (2, 4), (3, 6)) for i in range(n)]
    own = [order(DAY, 12, i) for i in range(100)]  # the target day itself must not count
    d = R.expected_demand(history + own, services, catalog, DAY, s)
    assert sum(d.orders) == pytest.approx(4.0)  # the mean of 2, 4 and 6 for the same weekday
    assert d.orders[d.hours.index(12)] == 0
    same = R.expected_demand(history, services, catalog, DAY, s)
    assert d == same


def test_demand_is_moved_earlier_by_the_lead_time(s, services, catalog):
    history = [order(DAY + timedelta(weeks=1), 8, i) for i in range(4)]
    d = R.expected_demand(history, services, catalog, DAY, s)
    assert d.orders[d.hours.index(7)] == pytest.approx(2.0) and d.orders[d.hours.index(8)] == pytest.approx(2.0)  # 30 of 60 min


def test_quiet_hours_with_some_bookings_keep_a_pair_on_duty(s, services, catalog):
    history = [order(DAY + timedelta(weeks=1), 8, 0), order(DAY + timedelta(weeks=1), 20, 0)]
    d = R.expected_demand(history, services, catalog, DAY, s)
    assert all(r >= s.roster_min_pairs_when_booked for r, o in zip(d.required_pairs, d.orders) if o >= s.roster_min_orders_for_cover)
    assert d.required_pairs[d.hours.index(13)] == 0  # nothing booked, nothing required


def test_cancelled_orders_do_not_count_and_no_history_means_no_demand(s, services, catalog):
    kept = [order(DAY + timedelta(weeks=1), 8, 0), order(DAY + timedelta(weeks=1), 9, 0, cancelled=True)]
    assert sum(R.expected_demand(kept, services, catalog, DAY, s).orders) == pytest.approx(1.0)
    assert sum(R.expected_demand([], services, catalog, DAY, s).required_pairs) == 0


def test_bigger_services_need_more_pairs(s, services, catalog):
    rows = [order(DAY + timedelta(weeks=1), 9, i) for i in range(4)]
    iv = [OrderRow(r.order_id, r.published_at, r.slot_start, "SV-10", r.area_id, r.lat, r.lon, r.patient_ref,
                   None, True, 120, None) for r in rows]
    assert sum(R.expected_demand(iv, services, catalog, DAY, s).pair_hours) > sum(R.expected_demand(rows, services, catalog, DAY, s).pair_hours)


# --- allocation -------------------------------------------------------------------------------


def test_pairs_reserve_and_iv_spread(s):
    nurses = [staff("nurse", 1, True), staff("nurse", 2, True), staff("nurse", 3), staff("nurse", 4)]
    drivers = [staff("driver", 1), staff("driver", 2), staff("driver", 3)]
    people = nurses + drivers
    hours = list(range(5, 22))
    required = [0.0] * len(hours)
    for h in range(7, 19):
        required[hours.index(h)] = 3.0
    roster = R.allocate(DAY, people, available(people), demand(hours, required), s)
    assert roster.mode == "auto" and len(roster.pairs) == 3 and roster.reserve == ["NUR-004"]
    assert [p.pair_id for p in roster.pairs] == ["P01", "P02", "P03"]
    assert [p.shift_start_min for p in roster.pairs] == sorted(p.shift_start_min for p in roster.pairs)
    assert all(p.shift_end_min - p.shift_start_min == 720 for p in roster.pairs)
    assert roster.pairs[0].iv_certified and roster.pairs[-1].iv_certified and not roster.pairs[1].iv_certified
    assert len({p.nurse_id for p in roster.pairs} | {p.driver_id for p in roster.pairs}) == 6


def test_people_who_are_not_available_are_left_out(s):
    people = [staff("nurse", i) for i in range(1, 4)] + [staff("driver", i) for i in range(1, 4)]
    rows = available(people)
    rows[0] = AvailabilityRow(DAY, "NUR-001", "sick")
    rows[5] = AvailabilityRow(DAY, "DRV-003", "rest")
    d = demand(list(range(5, 22)), [1.0] * 17)
    roster = R.allocate(DAY, people, rows, d, s)
    assert len(roster.pairs) == 2 and not {"NUR-001", "DRV-003"} & {x for p in roster.pairs for x in (p.nurse_id, p.driver_id)}
    marked = R.allocate(DAY, people, available(people), d, s, unavailable={"DRV-001"})
    assert len(marked.pairs) == 2 and "DRV-001" not in {p.driver_id for p in marked.pairs}
    assert R.allocate(DAY, people, [], d, s).pairs == []  # nobody is available


def test_on_duty_curve_matches_the_shifts(s):
    people = [staff("nurse", i) for i in range(1, 4)] + [staff("driver", i) for i in range(1, 4)]
    roster = R.allocate(DAY, people, available(people), demand(list(range(5, 22)), [1.0] * 17), s)
    assert sum(roster.on_duty) == pytest.approx(3 * s.shift_hours)
    assert roster.shortfall == pytest.approx(R.shortfall(roster.demand.required_pairs, roster.on_duty))


def test_simple_roster_is_the_placeholder_pairing(s):
    people = [staff("nurse", i) for i in range(1, 7)] + [staff("driver", i) for i in range(1, 7)]
    roster = R.simple(DAY, people, available(people), demand(list(range(5, 22)), [1.0] * 17), s)
    assert roster.mode == "simple" and [p.shift_start_min for p in roster.pairs] == [330, 480, 600, 330, 480, 600]


def test_settings_are_validated(tmp_path):
    base = dict(EngineSettings(_env_file=str(ROOT / ".env.example")).model_dump())
    for field, value, text in (("roster_lead_min", 90, "between 0 and 60"), ("roster_target_utilisation", 0, "above 0"),
                               ("roster_start_step_min", 0, "positive")):
        with pytest.raises(ValidationError, match=text):
            EngineSettings(**{**base, field: value})
    with pytest.raises(ValueError, match="before roster_start_earliest"):
        EngineSettings(**{**base, "roster_start_earliest": "11:00"}).roster_starts


# --- the generated month ----------------------------------------------------------------------


def test_auto_covers_demand_much_better_than_simple_pairing(settings, written, s, services, catalog):
    world = load_world(settings.data_reference_dir, settings.demand_profile_path, written)
    auto_total = simple_total = 0.0
    for offset in range(settings.data_days):
        day = settings.data_start_date + timedelta(days=offset)
        d = R.expected_demand(world.orders, services, catalog, day, s)
        auto = R.allocate(day, world.staff, world.availability, d, s)
        simple = R.simple(day, world.staff, world.availability, d, s)
        assert len(auto.pairs) == len(simple.pairs)
        auto_total, simple_total = auto_total + auto.shortfall, simple_total + simple.shortfall
    assert auto_total < 0.4 * simple_total
