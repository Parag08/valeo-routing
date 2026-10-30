"""Engine core: distance, catalog, schedule builder, planner and the independent validator."""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import date

import pytest
from pydantic import ValidationError

from valeo_routing.datagen.reference import load_reference
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import engine_labs, load_world, make_context, to_job
from valeo_routing.engine.distance import StraightLineRoad
from valeo_routing.engine.model import DRIVE, LAB, OFFICE, STANDBY, VISIT, DayPlan, Job, Pair, PairDay
from valeo_routing.engine.pairs import build_pairs
from valeo_routing.engine.planner import plan_day
from valeo_routing.engine.render import gantt
from valeo_routing.engine.schedule import build_schedule
from valeo_routing.engine.standby import OfficeStandby, StayStandby
from valeo_routing.engine.validator import Rules, validate
from valeo_routing.settings import EngineSettings

from .conftest import ROOT

REF_DIR = ROOT / "data" / "reference"

# Real places, used as plain coordinates.
AL_BARSHA = (25.1050, 55.1970)  # next to LAB-02
MARINA = (25.0770, 55.1450)
JBR = (25.0775, 55.1340)
DOWNTOWN = (25.1972, 55.2744)
SHARJAH = (25.3220, 55.3880)
FUJAIRAH = (25.1250, 56.3350)


@pytest.fixture(scope="module")
def engine_settings() -> EngineSettings:
    return EngineSettings(_env_file=str(ROOT / ".env.example"))


@pytest.fixture(scope="module")
def ref(settings):
    return load_reference(REF_DIR, settings.demand_profile_path)


@pytest.fixture(scope="module")
def ctx(engine_settings, ref):
    return make_context(engine_settings, ref)


@pytest.fixture(scope="module")
def ctx_stay(engine_settings, ref):
    return make_context(engine_settings, ref, StayStandby())


@pytest.fixture(scope="module")
def rules(ctx, ref):
    return Rules(ctx.dist, ctx.office, engine_labs(ref), ctx.tolerance_min, ctx.access_min, ctx.kit_stop_min)


def pair(pair_id="P01", start=330, hours=12, certified=True) -> Pair:
    return Pair(pair_id, "N" + pair_id, "D" + pair_id, "C" + pair_id, certified, start, start + hours * 60)


def job(job_id, slot, loc, minutes=15, category="injection", lab_id=None, sample_max=None,
        kits=False, published=-1000, iv_only=False) -> Job:
    return Job(job_id, published, slot, loc, minutes, category, iv_only, kits, lab_id, sample_max)


def sample(job_id, slot, loc, lab="LAB-02", max_min=480) -> Job:
    return job(job_id, slot, loc, category="sample", lab_id=lab, sample_max=max_min)


def plan_of(pairs, jobs, ctx) -> DayPlan:
    return plan_day(date(2026, 11, 4), pairs, jobs, ctx)


def codes(plan, jobs, rules) -> set:
    return {v.code for v in validate(plan, {j.job_id: j for j in jobs}, rules)}


def kinds(plan, pid="P01"):
    return [b.kind for b in plan.pairs[pid].blocks]


# --- settings ---------------------------------------------------------------------------------


def test_engine_settings_fail_fast(tmp_path, monkeypatch):
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    keys = [l.split("=", 1)[0] for l in lines if "=" in l and not l.startswith("#")]
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("\n".join(l for l in lines if not l.startswith("ROAD_FACTOR=")), encoding="utf-8")
    with pytest.raises(ValidationError, match="road_factor"):
        EngineSettings(_env_file=str(env))
    env.write_text("\n".join(l.replace("07:00-09:30,16:00-19:00", "09:30-07:00") for l in lines), encoding="utf-8")
    with pytest.raises(ValidationError, match="ends before it starts"):
        EngineSettings(_env_file=str(env))


# --- distance and catalog ---------------------------------------------------------------------


def test_distance_model(engine_settings):
    d = StraightLineRoad.from_settings(engine_settings)
    assert d.km(MARINA, MARINA) == 0.0 and d.minutes(MARINA, MARINA, 600) == 0
    assert d.km(MARINA, DOWNTOWN) == pytest.approx(d.km(DOWNTOWN, MARINA))
    assert 25 < d.km(MARINA, DOWNTOWN) < 30  # straight line is about 19 km; the road factor stretches it
    assert d.minutes(MARINA, DOWNTOWN, 450) > d.minutes(MARINA, DOWNTOWN, 300)  # 07:30 is peak, 05:00 is not
    assert d.minutes(MARINA, DOWNTOWN, 300) == pytest.approx(d.km(MARINA, DOWNTOWN) / 45 * 60, abs=1)


def test_catalog(ref):
    service = next(s for s in ref.services if s.service_id == "SV-08")  # IV hydration, 50-70 min
    assert Catalog(0.0).planned_minutes(service) == 50
    assert Catalog(0.5).planned_minutes(service) == 60
    assert Catalog(1.0).planned_minutes(service) == 70
    draws = [Catalog.actual_minutes(random.Random(i), service) for i in range(200)]
    assert min(draws) >= 50 and max(draws) <= 70 and len(set(draws)) > 5
    assert Catalog.actual_minutes(random.Random(1), service) == Catalog.actual_minutes(random.Random(1), service)


# --- schedule and planner ---------------------------------------------------------------------


def test_single_visit_day(ctx, rules):
    j = job("J1", 540, AL_BARSHA)
    plan = plan_of([pair()], [j], ctx)
    assert kinds(plan) == [STANDBY, DRIVE, VISIT, DRIVE]
    visit = plan.pairs["P01"].blocks[2]
    assert visit.start == 540 - ctx.tolerance_min  # arrives at the start of the window, no earlier
    assert visit.end == visit.start + ctx.access_min + j.duration_min
    assert plan.pairs["P01"].blocks[-1].loc == ctx.office
    assert codes(plan, [j], rules) == set()


def test_gantt_renders(ctx):
    plan = plan_of([pair()], [job("J1", 540, AL_BARSHA)], ctx)
    rows = gantt(plan)
    assert len(rows) == 2 and "V" in rows[1] and ">" in rows[1]


def test_window_missed_is_outside_shifts(ctx):
    plan = plan_of([pair(start=480)], [job("J1", 485, MARINA)], ctx)  # 5 minutes after the shift starts, 25 km away
    assert plan.served == 0 and [r.reason for r in plan.rejected] == ["outside_shifts"]


def test_visit_past_shift_end(ctx):
    plan = plan_of([pair(start=330, hours=6)], [job("J1", 12 * 60, AL_BARSHA)], ctx)  # shift ends 11:30
    assert [r.reason for r in plan.rejected] == ["outside_shifts"]


def test_second_visit_that_cannot_fit_is_no_capacity(ctx):
    jobs = [job("J1", 540, AL_BARSHA), job("J2", 545, DOWNTOWN)]  # 5 minutes apart, 20 km apart
    plan = plan_of([pair()], jobs, ctx)
    assert plan.pairs["P01"].job_ids == ["J1"]
    assert [(r.job_id, r.reason) for r in plan.rejected] == [("J2", "no_capacity")]


def test_samples_are_batched_into_one_lab_run(ctx, rules):
    jobs = [sample("S1", 480, AL_BARSHA), sample("S2", 540, (25.1060, 55.2000))]
    plan = plan_of([pair()], jobs, ctx)
    labs = [b for b in plan.pairs["P01"].blocks if b.kind == LAB]
    assert len(labs) == 1 and labs[0].job_ids == ("S1", "S2") and labs[0].lab_id == "LAB-02"
    assert codes(plan, jobs, rules) == set()


def test_sample_deadline_forces_an_early_lab_run(ctx, rules):
    a = sample("A", 480, AL_BARSHA, max_min=120)
    b = job("B", 600, SHARJAH)  # serving B first would put the lab out of reach of A's 2-hour limit
    plan = plan_of([pair()], [a, b], ctx)
    assert plan.pairs["P01"].job_ids == ["A", "B"]
    order = [(x.kind, x.job_id or x.job_ids) for x in plan.pairs["P01"].blocks if x.kind in (VISIT, LAB)]
    assert order == [(VISIT, "A"), (LAB, ("A",)), (VISIT, "B")]
    assert codes(plan, [a, b], rules) == set()


def test_unreachable_lab_is_rejected_with_a_reason(ctx):
    far = sample("F", 9 * 60, FUJAIRAH, lab="LAB-01", max_min=120)  # about 3 hours from the lab
    plan = plan_of([pair()], [far], ctx)
    assert [r.reason for r in plan.rejected] == ["lab_unreachable"]


def test_lab_closed(ctx):
    late = sample("L", 19 * 60 + 50, AL_BARSHA, lab="LAB-02")  # LAB-02 closes at 20:00
    plan = plan_of([pair(start=600)], [late], ctx)
    assert [r.reason for r in plan.rejected] == ["lab_unreachable"]


def test_kits_collected_after_publishing(ctx, rules):
    first = job("A", 9 * 60, SHARJAH)
    iv = job("IV", 10 * 60 + 45, JBR, category="iv", minutes=60, kits=True, published=10 * 60, iv_only=True)
    plan = plan_of([pair()], [first, iv], ctx)
    blocks = plan.pairs["P01"].blocks
    office = [b for b in blocks if b.kind == OFFICE]
    visit = next(b for b in blocks if b.job_id == "IV")
    assert len(office) == 1 and office[0].start >= iv.published_min and office[0].end <= visit.start
    assert codes(plan, [first, iv], rules) == set()


def test_no_kit_stop_when_kits_were_prepared_in_advance(ctx):
    iv = job("IV", 10 * 60 + 45, JBR, category="iv", minutes=60, kits=False, published=10 * 60, iv_only=True)
    assert OFFICE not in kinds(plan_of([pair()], [job("A", 9 * 60, SHARJAH), iv], ctx))


def test_kits_published_before_the_shift_need_no_stop(ctx, rules):
    iv = job("IV", 8 * 60, JBR, category="iv", minutes=60, kits=True, published=0, iv_only=True)  # published at midnight
    plan = plan_of([pair()], [iv], ctx)
    assert OFFICE not in kinds(plan) and plan.served == 1
    assert codes(plan, [iv], rules) == set()


def test_iv_needs_a_certified_nurse(ctx):
    iv = job("IV", 9 * 60, AL_BARSHA, category="iv", minutes=60, iv_only=True)
    assert [r.reason for r in plan_of([pair(certified=False)], [iv], ctx).rejected] == ["no_certified_nurse"]
    assert plan_of([pair(certified=False), pair("P02", certified=True)], [iv], ctx).pairs["P02"].job_ids == ["IV"]


def test_office_standby_drives_more_than_staying_put(ctx, ctx_stay, rules):
    jobs = [job("J1", 7 * 60, MARINA), job("J2", 12 * 60, JBR)]
    office, stay = plan_of([pair()], jobs, ctx), plan_of([pair()], jobs, ctx_stay)
    assert office.served == stay.served == 2
    assert office.km > stay.km + 10  # back to Al Quoz and out again
    assert codes(office, jobs, rules) == codes(stay, jobs, rules) == set()


def test_cheapest_insertion_prefers_the_pair_already_nearby(ctx):
    jobs = [job("J1", 9 * 60, MARINA), job("J2", 10 * 60, JBR)]
    plan = plan_of([pair("P01"), pair("P02")], jobs, ctx)
    assert plan.pairs["P01"].job_ids == ["J1", "J2"] and plan.pairs["P02"].job_ids == []


def test_planning_is_deterministic(ctx):
    jobs = [job("J{}".format(i), 7 * 60 + 25 * i, random.Random(i).choice([MARINA, JBR, AL_BARSHA, DOWNTOWN])) for i in range(8)]
    pairs = [pair("P01"), pair("P02", start=480)]
    assert plan_of(pairs, jobs, ctx).pairs["P01"].blocks == plan_of(pairs, jobs, ctx).pairs["P01"].blocks


def test_schedule_failure_codes(ctx):
    assert build_schedule(pair(), [job("J", 545, AL_BARSHA), job("K", 550, DOWNTOWN)], ctx).reason == "window_missed"
    assert build_schedule(pair(hours=1), [job("J", 12 * 60, AL_BARSHA)], ctx).reason == "shift_ended"
    assert build_schedule(pair(), [sample("F", 540, FUJAIRAH, "LAB-01", 120)], ctx).reason == "sample_deadline"


# --- the validator catches broken plans -------------------------------------------------------


@pytest.fixture(scope="module")
def full_day(ctx, rules):
    """A day with a sample, an IV visit that needs kits, and a forced early lab run."""
    jobs = [
        sample("S1", 8 * 60, AL_BARSHA, max_min=120),
        job("IV", 10 * 60 + 45, JBR, category="iv", minutes=60, kits=True, published=10 * 60, iv_only=True),
        job("INJ", 13 * 60, SHARJAH),
    ]
    plan = plan_of([pair()], jobs, ctx)
    assert plan.served == 3 and codes(plan, jobs, rules) == set()
    return plan, jobs


def with_blocks(plan: DayPlan, blocks) -> DayPlan:
    day = plan.pairs["P01"]
    return DayPlan(plan.day, {"P01": PairDay(day.pair, list(day.job_ids), list(blocks))}, plan.rejected)


def test_validator_catches_a_late_visit(full_day, rules):
    plan, jobs = full_day
    blocks = [replace(b, start=b.start + 40, end=b.end + 40) if b.job_id == "INJ" else b for b in plan.pairs["P01"].blocks]
    assert "window" in codes(with_blocks(plan, blocks), jobs, rules)


def test_validator_catches_a_missing_lab_drop(full_day, rules):
    plan, jobs = full_day
    blocks = [b for b in plan.pairs["P01"].blocks if b.kind != LAB]
    assert "sample_not_dropped" in codes(with_blocks(plan, blocks), jobs, rules)


def test_validator_catches_a_late_sample(full_day, rules):
    plan, jobs = full_day
    blocks = [replace(b, start=b.start + 240, end=b.end + 240) if b.kind == LAB else b for b in plan.pairs["P01"].blocks]
    assert "sample_deadline" in codes(with_blocks(plan, blocks), jobs, rules)


def test_validator_catches_a_lab_drop_outside_opening_hours(full_day, rules):
    plan, jobs = full_day
    blocks = [replace(b, start=b.start - 600, end=b.end - 600) if b.kind == LAB else b for b in plan.pairs["P01"].blocks]
    assert "lab_hours" in codes(with_blocks(plan, blocks), jobs, rules)


def test_validator_catches_missing_kits(full_day, rules):
    plan, jobs = full_day
    visit = next(b for b in plan.pairs["P01"].blocks if b.job_id == "IV")
    last_office_exit = max(b.start for b in plan.pairs["P01"].blocks if b.kind == DRIVE and b.from_loc == rules.office)
    late = [replace(j, published_min=last_office_exit) if j.job_id == "IV" else j for j in jobs]  # kits asked for after the pair left
    assert last_office_exit < visit.start
    assert "kit_missing" in codes(plan, late, rules)


def test_validator_catches_a_wrong_drive(full_day, rules):
    plan, jobs = full_day
    drive = next(i for i, b in enumerate(plan.pairs["P01"].blocks) if b.kind == DRIVE)
    wrong_km = list(plan.pairs["P01"].blocks)
    wrong_km[drive] = replace(wrong_km[drive], km=wrong_km[drive].km + 3)
    wrong_time = list(plan.pairs["P01"].blocks)
    wrong_time[drive] = replace(wrong_time[drive], end=wrong_time[drive].end + 5)
    assert "drive_km" in codes(with_blocks(plan, wrong_km), jobs, rules)
    assert "drive_time" in codes(with_blocks(plan, wrong_time), jobs, rules)


def test_validator_catches_overlap_gap_and_teleport(full_day, rules):
    plan, jobs = full_day
    blocks = list(plan.pairs["P01"].blocks)
    i = next(i for i, b in enumerate(blocks) if b.kind == VISIT)
    overlap = blocks[:i] + [replace(blocks[i], start=blocks[i].start - 3)] + blocks[i + 1:]
    gap = blocks[:i] + [replace(blocks[i], start=blocks[i].start + 3, service_start=blocks[i].service_start + 3)] + blocks[i + 1:]
    teleport = blocks[:i] + [replace(blocks[i], loc=(0.0, 0.0))] + blocks[i + 1:]
    assert "overlap" in codes(with_blocks(plan, overlap), jobs, rules)
    assert "gap" in codes(with_blocks(plan, gap), jobs, rules)
    assert "teleport" in codes(with_blocks(plan, teleport), jobs, rules)


def test_validator_catches_not_ending_at_the_office(full_day, rules):
    plan, jobs = full_day
    assert "not_home" in codes(with_blocks(plan, plan.pairs["P01"].blocks[:-1]), jobs, rules)


def test_validator_catches_shift_overrun(full_day, rules):
    plan, jobs = full_day
    short = Pair("P01", "NP01", "DP01", "CP01", True, 330, 12 * 60)  # shift now ends before the last visits
    day = PairDay(short, plan.pairs["P01"].job_ids, plan.pairs["P01"].blocks)
    assert "shift" in codes(DayPlan(plan.day, {"P01": day}, []), jobs, rules)


def test_validator_catches_bookkeeping_errors(full_day, rules):
    plan, jobs = full_day
    day = plan.pairs["P01"]
    twin = PairDay(Pair("P02", "N2", "D2", "C2", True, 330, 1050), list(day.job_ids), list(day.blocks))
    assert "duplicate_job" in codes(DayPlan(plan.day, {"P01": day, "P02": twin}, []), jobs, rules)
    shared = PairDay(Pair("P02", day.pair.nurse_id, "D2", "C2", True, 330, 1050), [], [])
    assert "resource_reuse" in codes(DayPlan(plan.day, {"P01": day, "P02": shared}, []), jobs, rules)
    scrambled = PairDay(day.pair, list(reversed(day.job_ids)), list(day.blocks))
    assert "job_order" in codes(DayPlan(plan.day, {"P01": scrambled}, []), jobs, rules)


def test_validator_catches_an_uncertified_iv_nurse(full_day, rules):
    plan, jobs = full_day
    day = plan.pairs["P01"]
    uncertified = PairDay(replace(day.pair, iv_certified=False), day.job_ids, day.blocks)
    assert "certification" in codes(DayPlan(plan.day, {"P01": uncertified}, []), jobs, rules)


# --- a real generated month --------------------------------------------------------------------


@pytest.fixture(scope="module")
def world(settings, written):
    return load_world(settings.data_reference_dir, settings.demand_profile_path, written)


@pytest.mark.parametrize("day", [date(2026, 11, 4), date(2026, 11, 7), date(2026, 11, 16), date(2026, 12, 2)])
@pytest.mark.parametrize("policy", ["office", "stay"])
def test_real_days_plan_validly(day, policy, world, engine_settings, ref, rules):
    office = (ref.office.lat, ref.office.lon)
    context = make_context(engine_settings, ref, OfficeStandby(office) if policy == "office" else StayStandby())
    catalog = Catalog(engine_settings.plan_duration_position)
    services = {s.service_id: s for s in ref.services}
    rows = [o for o in world.orders_on(day) if o.cancelled_at is None]
    jobs = [to_job(o, services[o.service_id], catalog) for o in rows]
    pairs = build_pairs(day, world.staff, world.availability, engine_settings.shift_start_minutes, engine_settings.shift_hours)
    assert 5 <= len(pairs) <= 12

    plan = plan_day(day, pairs, jobs, context)
    assert validate(plan, {j.job_id: j for j in jobs}, rules) == []
    assert plan.served + len(plan.rejected) == len(jobs)
    assert plan.served / len(jobs) > 0.7
    assert {r.reason for r in plan.rejected} <= {"no_certified_nurse", "lab_unreachable", "outside_shifts", "no_capacity"}
