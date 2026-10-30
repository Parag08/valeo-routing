"""Acceptance policies, the replay clock (competitor claim, cancellations) and the 'past is fixed' rule."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytest

from valeo_routing.datagen.reference import load_reference
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.commit import prefix_matches, with_idle_tail
from valeo_routing.engine.data import OrderRow, engine_labs, load_world, make_context
from valeo_routing.engine.model import DRIVE, STANDBY, VISIT, Block, Job, Pair
from valeo_routing.engine.pairs import build_pairs
from valeo_routing.engine.policy import (
    AUTO, EXCEL, MANUAL, Decision, ExcelEra, LogisticsValeoV1, effective_lead_h, next_open, quiet_minutes,
)
from valeo_routing.engine.replay import (
    ACCEPTED, CANCELLED, CANCELLED_EARLY, DECLINED, LATE_CANCEL, LOST, DayKpis, replay_day,
)
from valeo_routing.engine.validator import Rules, validate
from valeo_routing.settings import EngineSettings

from .conftest import ROOT

DAY = date(2026, 11, 4)
MIDNIGHT = datetime.combine(DAY, time.min)
QUIET = (22 * 60, 6 * 60)

AL_BARSHA = (25.1050, 55.1970)
MARINA = (25.0770, 55.1450)


def at(h: int, m: int = 0, day_offset: int = 0) -> datetime:
    return MIDNIGHT + timedelta(days=day_offset, hours=h, minutes=m)


@pytest.fixture(scope="module")
def engine_settings() -> EngineSettings:
    return EngineSettings(_env_file=str(ROOT / ".env.example"))


@pytest.fixture(scope="module")
def ref(settings):
    return load_reference(ROOT / "data" / "reference", settings.demand_profile_path)


@pytest.fixture(scope="module")
def ctx(engine_settings, ref):
    return make_context(engine_settings, ref)


@pytest.fixture(scope="module")
def services(ref):
    return {s.service_id: s for s in ref.services}


@pytest.fixture(scope="module")
def catalog(engine_settings):
    return Catalog(engine_settings.plan_duration_position)


@pytest.fixture(scope="module")
def rules(ctx, ref):
    return Rules(ctx.dist, ctx.office, engine_labs(ref), ctx.tolerance_min, ctx.access_min, ctx.kit_stop_min)


def job(published: int, slot: int) -> Job:
    return Job("J", published, slot, AL_BARSHA, 15, "injection", False, False)


def row(order_id, published, slot, loc=AL_BARSHA, claim=240, cancelled=None) -> OrderRow:
    return OrderRow(order_id, published, slot, "SV-11", "AR-10", loc[0], loc[1], "PT-1", None, True, claim, cancelled)


@dataclass
class FixedPolicy:
    """Decides each order at a fixed minute, so scenarios do not depend on random delays."""

    decide_at: dict
    name: str = "fixed"
    standby: object = None

    def when(self, job, rng):
        return Decision(self.decide_at[job.job_id], AUTO)


def run(ctx, services, catalog, rows, policy, pairs=None, trace=False):
    pairs = pairs or [Pair("P01", "N1", "D1", "C1", True, 330, 1050)]
    return replay_day(DAY, pairs, rows, services, catalog, ctx, policy, replay_seed=1, trace=trace)


def outcomes(result):
    return {r.order_id: (r.outcome, r.final) for r in result.log}


# --- time helpers and policies ----------------------------------------------------------------


def test_next_open():
    assert next_open(10 * 60, 480, 1200) == 10 * 60  # inside office hours
    assert next_open(5 * 60, 480, 1200) == 480  # before opening: same day
    assert next_open(21 * 60 + 30, 480, 1200) == 1440 + 480  # after closing: tomorrow
    assert next_open(-60, 480, 1200) == 480  # 23:00 the day before -> 08:00 the day after


def test_quiet_minutes():
    assert quiet_minutes(-600, 480, QUIET) == 480  # 14:00 the day before to 08:00: the whole night
    assert quiet_minutes(9 * 60, 12 * 60, QUIET) == 0
    assert quiet_minutes(21 * 60, 23 * 60, QUIET) == 60
    assert quiet_minutes(0, 2 * 1440, QUIET) == 2 * 480
    assert quiet_minutes(0, 1440, QUIET) == 360 + 120  # 00:00-06:00 and 22:00-24:00


def test_effective_lead_ignores_the_night():
    assert effective_lead_h(job(published=-600, slot=480), QUIET) == pytest.approx((1080 - 480) / 60)  # 18 h less 8 h = 10 h
    assert effective_lead_h(job(published=-120, slot=480), QUIET) == pytest.approx(2.0)  # published 22:00 for 08:00


def test_excel_era_waits_for_office_hours(engine_settings, ctx):
    policy = ExcelEra(engine_settings, ctx.office)
    lo, hi = engine_settings.excel_response_min_lo, engine_settings.excel_response_min_hi
    rng = random.Random(1)
    for published, opens in ((10 * 60, 10 * 60), (5 * 60, 8 * 60), (21 * 60 + 30 - 1440, 8 * 60)):
        d = policy.when(job(published, published + 600), rng)
        assert d.mode == EXCEL and opens + lo <= d.time_min <= opens + hi


def test_logistics_valeo_accepts_by_itself_only_with_time_to_react(engine_settings, ctx):
    policy = LogisticsValeoV1(engine_settings, ctx.office)
    rng = random.Random(1)
    early = policy.when(job(published=-900, slot=480), rng)  # 09:00 the day before, 08:00 slot: 23 h less 8 h = 15 h
    assert (early.mode, early.time_min) == (AUTO, -900)
    late_night = policy.when(job(published=-120, slot=480), rng)  # 22:00 for 08:00: 2 h of real time
    assert late_night.mode == MANUAL and 480 + engine_settings.manual_response_min_lo <= late_night.time_min \
        <= 480 + engine_settings.manual_response_min_hi
    daytime = policy.when(job(published=10 * 60, slot=14 * 60), rng)
    assert daytime.mode == MANUAL and 600 + 5 <= daytime.time_min <= 600 + 30


def test_threshold_is_configurable(engine_settings, ctx):
    strict = EngineSettings(**{**engine_settings.model_dump(), "auto_accept_lead_h": 24})
    assert LogisticsValeoV1(strict, ctx.office).when(job(published=-900, slot=480), random.Random(1)).mode == MANUAL


# --- committed past ---------------------------------------------------------------------------


def test_prefix_matches_rules(ctx):
    office = ctx.office
    pair = Pair("P", "N", "D", "C", True, 330, 1050)
    drive = Block(DRIVE, 500, 520, MARINA, from_loc=office, km=9.0)
    visit = Block(VISIT, 520, 545, MARINA, job_id="J", service_start=525)
    old = [Block(STANDBY, 330, 500, office, note="office"), drive, visit]
    assert prefix_matches(old, [Block(STANDBY, 330, 490, office, note="office")] + [drive], 400)  # a wait can end sooner
    assert not prefix_matches(old, [Block(STANDBY, 330, 390, office, note="office")], 400)  # but not before 'now'
    assert not prefix_matches(old, [Block(STANDBY, 330, 500, office, note="in place"), drive], 510)  # the wait was at the office
    assert not prefix_matches(old, [old[0], replace_end(drive, 530)], 510)  # a drive under way is fixed
    assert not prefix_matches(old, [old[0], drive, replace_end(visit, 560)], 530)  # so is a visit
    assert prefix_matches(old, [old[0], replace_end(drive, 530)], 500)  # a block starting at 'now' is still free
    idle = with_idle_tail(pair, [], office)
    assert idle == [Block(STANDBY, 330, 1050, office, note="office")]


def replace_end(b: Block, end: int) -> Block:
    from dataclasses import replace

    return replace(b, end=end)


# --- replay scenarios -------------------------------------------------------------------------


def test_auto_accepted_order_is_logged(ctx, services, catalog):
    r = row("A", at(8, 0, -2), at(9))
    result = run(ctx, services, catalog, [r], FixedPolicy({"A": -2 * 1440 + 480}))
    rec = result.log[0]
    assert (rec.outcome, rec.final, rec.pair_id, rec.mode) == (ACCEPTED, "served", "P01", AUTO)
    assert rec.reason.startswith("fits P01") and rec.decided_min == -2 * 1440 + 480
    assert result.kpis.accepted == 1 and result.kpis.visits == 1 and result.kpis.capture_rate == 1.0


def test_order_lost_to_the_competitor(ctx, services, catalog):
    r = row("A", at(21, 30, -1), at(9), claim=120)
    result = run(ctx, services, catalog, [r], FixedPolicy({"A": 8 * 60 + 20}))  # decided next morning
    rec = result.log[0]
    assert rec.outcome == LOST and "claimed by another provider" in rec.reason
    assert rec.decided_min == -150 + 120  # the moment the competitor took it: published (-150) + 120
    assert result.kpis.lost == 1 and result.plan.served == 0


def test_decision_exactly_at_the_claim_deadline_still_counts(ctx, services, catalog):
    r = row("A", at(10, 0, -1), at(9), claim=120)
    result = run(ctx, services, catalog, [r], FixedPolicy({"A": -1440 + 600 + 120}))
    assert result.log[0].outcome == ACCEPTED


def test_too_late_decision_is_declined(ctx, services, catalog):
    r = row("A", at(8, 0), at(9), claim=240)
    result = run(ctx, services, catalog, [r], FixedPolicy({"A": 9 * 60 + 20}))  # after the 09:15 window closed
    assert result.log[0].outcome == DECLINED and result.log[0].reason.startswith("too_late")


def test_cancelled_before_anyone_decides(ctx, services, catalog):
    r = row("A", at(10, 0, -1), at(9), cancelled=at(10, 5, -1))
    result = run(ctx, services, catalog, [r], FixedPolicy({"A": -1440 + 615}))
    assert result.log[0].outcome == CANCELLED_EARLY
    assert result.kpis.capturable == 0 and result.kpis.capture_rate == 0.0


def test_a_cancellation_frees_the_pair(ctx, services, catalog):
    r = row("A", at(8, 0, -2), at(9), cancelled=at(7))
    result = run(ctx, services, catalog, [r], FixedPolicy({"A": -2 * 1440 + 480}))
    rec = result.log[0]
    assert (rec.outcome, rec.final) == (ACCEPTED, CANCELLED)
    assert result.plan.pairs["P01"].job_ids == [] and result.plan.km == 0.0
    assert result.kpis.accepted == 1 and result.kpis.honored_cancellations == 1 and result.kpis.visits == 0


def test_a_cancellation_after_arrival_is_a_late_cancellation(ctx, services, catalog, rules):
    r = row("A", at(8, 0, -2), at(9), cancelled=at(8, 50))  # the pair arrived at 08:45
    result = run(ctx, services, catalog, [r], FixedPolicy({"A": -2 * 1440 + 480}))
    assert (result.log[0].outcome, result.log[0].final) == (ACCEPTED, LATE_CANCEL)
    assert result.plan.pairs["P01"].job_ids == ["A"]  # the visit still happens, and its km are spent
    assert result.kpis.late_cancellations == 1 and result.kpis.visits == 1
    assert validate(result.plan, result.jobs, rules) == []


def test_freed_capacity_is_reused(ctx, services, catalog):
    first = row("A", at(8, 0, -2), at(9), cancelled=at(7, 0))
    second = row("B", at(7, 30), at(9, 5), loc=(25.1972, 55.2744))  # 5 minutes later and 20 km away: only fits if A is gone
    result = run(ctx, services, catalog, [first, second], FixedPolicy({"A": -2 * 1440 + 480, "B": 7 * 60 + 40}))
    assert outcomes(result) == {"A": (ACCEPTED, CANCELLED), "B": (ACCEPTED, "served")}


def test_what_has_started_cannot_be_changed(ctx, services, catalog):
    """B needs the pair to leave the office around 08:20. Decided at 08:10 that still works; at 08:30 it is history."""
    pair_a = row("A", at(8, 0, -2), at(10), loc=MARINA)
    b = row("B", at(8, 0), at(8, 50), loc=AL_BARSHA)
    early = run(ctx, services, catalog, [pair_a, b], FixedPolicy({"A": -2 * 1440 + 480, "B": 8 * 60 + 10}))
    late = run(ctx, services, catalog, [pair_a, b], FixedPolicy({"A": -2 * 1440 + 480, "B": 8 * 60 + 30}))
    assert outcomes(early)["B"] == (ACCEPTED, "served")
    assert outcomes(late)["B"] == (DECLINED, "not_served") and late.log[-1].reason == "no_capacity"
    assert late.plan.pairs["P01"].job_ids == ["A"]


def test_kpi_arithmetic():
    a = DayKpis(offered=10, cancelled_before_decision=2, accepted=6, lost=1, declined=1, honored_cancellations=1, km=100.0)
    b = DayKpis(offered=10, accepted=5, km=50.0)
    assert a.capturable == 8 and a.capture_rate == 0.75 and a.visits == 5 and a.km_per_visit == 20.0
    total = a + b
    assert (total.offered, total.accepted, total.km, total.visits) == (20, 11, 150.0, 10)
    assert DayKpis().capture_rate == 0.0 and DayKpis().km_per_visit == 0.0


# --- a real week ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world(settings, written):
    return load_world(settings.data_reference_dir, settings.demand_profile_path, written)


def replay_real(world, engine_settings, ctx, policy, day, trace=False):
    pairs = build_pairs(day, world.staff, world.availability, engine_settings.shift_start_minutes, engine_settings.shift_hours)
    services = {s.service_id: s for s in world.ref.services}
    return replay_day(day, pairs, world.orders_on(day), services, Catalog(engine_settings.plan_duration_position),
                      ctx, policy, engine_settings.replay_seed, trace=trace)


def policies(engine_settings, ctx):
    return [ExcelEra(engine_settings, ctx.office), LogisticsValeoV1(engine_settings, ctx.office)]


@pytest.mark.parametrize("day", [date(2026, 11, 4), date(2026, 11, 8), date(2026, 11, 17)])
def test_real_days_are_valid_and_the_log_adds_up(world, engine_settings, ctx, rules, day):
    for policy in policies(engine_settings, ctx):
        result = replay_real(world, engine_settings, ctx, policy, day)
        k = result.kpis
        assert validate(result.plan, result.jobs, rules) == []
        assert k.accepted + k.lost + k.declined + k.cancelled_before_decision == k.offered == len(result.log)
        assert k.visits == result.plan.served
        assert sum(1 for d in result.plan.pairs.values() for b in d.blocks if b.kind == VISIT) == k.visits
        assert k.km == pytest.approx(sum(b.km for d in result.plan.pairs.values() for b in d.blocks))
        assert all(r.pair_id for r in result.log if r.outcome == ACCEPTED)
        assert all(r.reason for r in result.log)
        assert {r.outcome for r in result.log} <= {ACCEPTED, DECLINED, LOST, CANCELLED_EARLY}


@pytest.mark.parametrize("which", [0, 1])
def test_what_started_never_changes_during_a_real_day(world, engine_settings, ctx, which):
    """Independent of the planner's own check: a visit that has started is in every later snapshot, unchanged."""
    result = replay_real(world, engine_settings, ctx, policies(engine_settings, ctx)[which], date(2026, 11, 4), trace=True)
    assert len(result.trace) > 20
    for i, (now, snapshot) in enumerate(result.trace):
        started = {(pid, b) for pid, blocks in snapshot.items() for b in blocks if b.kind != STANDBY and b.start < now}
        for _, later in result.trace[i + 1:]:
            present = {(pid, b) for pid, blocks in later.items() for b in blocks}
            missing = started - present
            assert not missing, (now, sorted(missing, key=lambda x: x[1].start)[:2])


def test_the_replay_is_deterministic(world, engine_settings, ctx):
    policy = policies(engine_settings, ctx)[0]
    a = replay_real(world, engine_settings, ctx, policy, date(2026, 11, 4))
    b = replay_real(world, engine_settings, ctx, policy, date(2026, 11, 4))
    assert a.log == b.log and a.kpis == b.kpis
    other = EngineSettings(**{**engine_settings.model_dump(), "replay_seed": engine_settings.replay_seed + 1})
    c = replay_real(world, other, ctx, ExcelEra(other, ctx.office), date(2026, 11, 4))
    assert [r.decided_min for r in c.log] != [r.decided_min for r in a.log]


def test_the_tool_captures_more_than_excel_over_a_week(world, engine_settings, ctx):
    totals = {}
    for policy in policies(engine_settings, ctx):
        total = DayKpis()
        for offset in range(7):
            total += replay_real(world, engine_settings, ctx, policy, date(2026, 11, 2) + timedelta(days=offset)).kpis
        totals[policy.name] = total
    excel, lv1 = totals["excel"], totals["lv1"]
    assert lv1.capture_rate > excel.capture_rate + 0.05
    assert lv1.lost < excel.lost
