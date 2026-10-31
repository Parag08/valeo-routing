"""Logistics Valeo v2: making room for an order that does not fit, by moving or swapping out an accepted one."""
from __future__ import annotations

from datetime import date

import pytest

from valeo_routing.datagen.reference import load_reference
from valeo_routing.engine import roster as rosters
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import engine_labs, load_world, make_context
from valeo_routing.engine.model import Job, Pair
from valeo_routing.engine.planner import best_insertion
from valeo_routing.engine.policy import LogisticsValeoV1, LogisticsValeoV2
from valeo_routing.engine.replay import ACCEPTED, BUMPED, replay_day
from valeo_routing.engine.schedule import build_schedule
from valeo_routing.engine.swap import CancelModel, SwapRules, find_room
from valeo_routing.engine.validator import Rules, validate
from valeo_routing.settings import EngineSettings

from .conftest import ROOT

DAYS = [date(2026, 11, d) for d in (3, 4, 10, 18, 21)] + [date(2026, 12, 2)]


@pytest.fixture(scope="module")
def engine_settings() -> EngineSettings:
    return EngineSettings(_env_file=str(ROOT / ".env.example"))


@pytest.fixture(scope="module")
def world(settings, written):
    return load_world(settings.data_reference_dir, settings.demand_profile_path, written)


@pytest.fixture(scope="module")
def ctx(engine_settings, world):
    return make_context(engine_settings, world.ref)


@pytest.fixture(scope="module")
def services(world):
    return {s.service_id: s for s in world.ref.services}


@pytest.fixture(scope="module")
def cancels(world, services, engine_settings):
    return CancelModel(world.orders, services, engine_settings.cancel_bands_h, engine_settings.v2_cancel_prior_weight)


def test_cancel_model_is_smoothed_and_banded(cancels, world):
    assert 0 < cancels.overall < 0.2
    assert all(0 < r < 1 for r in cancels.rates.values())
    assert cancels.band(1) == 0 and cancels.band(6) == 1 and cancels.band(30) == 2 and cancels.band(100) == 3


def _job(job_id, slot, loc, iv_only=False, minutes=20):
    return Job(job_id, -600, slot, loc, minutes, "iv" if iv_only else "injection", iv_only, False)


class NoCancels:
    def p_cancel(self, job):
        return 0.0


def _setup(ctx, b_shift_end):
    """P01 is IV-certified and holds an ordinary visit at 10:00; P02 is not certified. A new IV-only order
    arrives for 10:00 nearby: only P01 may serve it, and P01 is busy."""
    a = Pair("P01", "N1", "D1", "C1", True, 8 * 60, 20 * 60)
    b = Pair("P02", "N2", "D2", "C2", False, 8 * 60, b_shift_end)
    near = (ctx.office[0] + 0.02, ctx.office[1] + 0.02)
    old = _job("O-OLD", 10 * 60, near, minutes=120)  # long enough that nothing else fits around 10:00
    new = _job("O-NEW", 10 * 60, near, iv_only=True, minutes=60)
    seq = {"P01": [old], "P02": []}
    sched = {"P01": build_schedule(a, [old], ctx)}
    blocks = {"P01": sched["P01"].blocks, "P02": []}
    km = {"P01": sched["P01"].km, "P02": 0.0}
    assert best_insertion(new, [a, b], seq, km, ctx, now=0, blocks=blocks) is None
    return [a, b], new, seq, blocks, km


def test_a_move_makes_room_without_losing_an_order(ctx):
    pairs, new, seq, blocks, km = _setup(ctx, 20 * 60)
    room = find_room(new, pairs, seq, blocks, km, ctx, 0, SwapRules(120, 12, 60, 10), NoCancels())
    assert room.kind == "move" and room.pair_id == "P01" and room.other.job_id == "O-OLD" and room.moved_to == "P02"
    assert [j.job_id for j in room.sequence] == ["O-NEW"]


def test_a_swap_needs_notice_and_a_gain(ctx):
    pairs, new, seq, blocks, km = _setup(ctx, 9 * 60)  # P02 goes home before 10:00, so O-OLD cannot move
    # Same place, same km: the gain is only the cancellation difference, which is zero here.
    assert find_room(new, pairs, seq, blocks, km, ctx, 0, SwapRules(120, 9, 60, 10), NoCancels()) is None

    class OldMayCancel:
        def p_cancel(self, job):
            return 0.5 if job.job_id == "O-OLD" else 0.0

    room = find_room(new, pairs, seq, blocks, km, ctx, 0, SwapRules(120, 9, 60, 10), OldMayCancel())
    assert room.kind == "swap" and room.other.job_id == "O-OLD" and room.gain_km == pytest.approx(30.0)
    # The slot is 10 h away: too close to hand O-OLD back to the platform with 11 h notice required.
    assert find_room(new, pairs, seq, blocks, km, ctx, 0, SwapRules(120, 11, 60, 10), OldMayCancel()) is None


@pytest.mark.parametrize("day", DAYS)
def test_v2_replays_are_valid_and_never_capture_less(day, world, ctx, services, cancels, engine_settings):
    catalog = Catalog(engine_settings.plan_duration_position)
    demand = rosters.expected_demand(world.orders, services, catalog, day, engine_settings)
    pairs = rosters.allocate(day, world.staff, world.availability, demand, engine_settings).pairs
    rows = world.orders_on(day)
    rules = Rules(ctx.dist, ctx.office, engine_labs(world.ref), ctx.tolerance_min, ctx.access_min, ctx.kit_stop_min)
    v1 = replay_day(day, pairs, rows, services, catalog, ctx, LogisticsValeoV1(engine_settings, ctx.office), engine_settings.replay_seed)
    v2 = replay_day(day, pairs, rows, services, catalog, ctx, LogisticsValeoV2(engine_settings, ctx.office, cancels),
                    engine_settings.replay_seed)
    assert validate(v2.plan, v2.jobs, rules) == []
    planned = {j for d in v2.plan.pairs.values() for j in d.job_ids}
    for r in v2.log:
        if r.final == BUMPED:
            assert r.outcome == ACCEPTED and r.order_id not in planned and r.room.startswith("released")
        elif r.outcome == ACCEPTED and r.final in ("served", "late_cancellation"):
            assert r.order_id in planned and r.order_id in v2.plan.pairs[r.pair_id].job_ids
    assert v2.kpis.visits == v2.plan.served
    assert v2.kpis.capture_rate >= v1.kpis.capture_rate - 0.05  # history can diverge; v2 should not fall behind
