"""Capacity: the concurrency floor, the simulated need and service-level percentiles."""
from __future__ import annotations

from datetime import date

import pytest

from valeo_routing.datagen.reference import load_reference
from valeo_routing.engine import capacity as cap
from valeo_routing.engine import roster as rosters
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import load_world, make_context, to_job
from valeo_routing.engine.model import Job
from valeo_routing.engine.planner import plan_day
from valeo_routing.settings import EngineSettings

from .conftest import ROOT


def j(job_id, slot, minutes=15) -> Job:
    return Job(job_id, -600, slot, (25.1, 55.2), minutes, "injection", False, False)


def test_concurrency_floor():
    assert cap.concurrency_floor([], 15, 5) == 0
    # spans: [585, 605), [595, 615), [605, 625): the first two overlap, the third starts as the first ends
    assert cap.concurrency_floor([j("a", 600), j("b", 610), j("c", 620)], 15, 5) == 2
    assert cap.concurrency_floor([j("a", 600), j("b", 700)], 15, 5) == 1


def test_percentile_is_nearest_rank():
    values = [6, 7, 8, 8, 9, 10, 10, 11, 12, 14]
    assert cap.percentile(values, 50) == 9
    assert cap.percentile(values, 75) == 11
    assert cap.percentile(values, 90) == 12
    assert cap.percentile(values, 100) == 14
    assert cap.percentile([], 50) == 0


@pytest.fixture(scope="module")
def engine_settings() -> EngineSettings:
    return EngineSettings(_env_file=str(ROOT / ".env.example"))


@pytest.fixture(scope="module")
def world(settings, written):
    return load_world(settings.data_reference_dir, settings.demand_profile_path, written)


def test_hypothetical_pairs(world, engine_settings):
    catalog = Catalog(engine_settings.plan_duration_position)
    services = {s.service_id: s for s in world.ref.services}
    demand = rosters.expected_demand(world.orders, services, catalog, date(2026, 11, 4), engine_settings)
    pairs = cap.hypothetical_pairs(10, 0.4, demand, engine_settings)
    assert len(pairs) == 10 and sum(p.iv_certified for p in pairs) == 4
    assert all(p.shift_start_min in engine_settings.roster_starts for p in pairs)


@pytest.mark.parametrize("day", [date(2026, 11, 4), date(2026, 11, 8)])
def test_day_need_is_the_fewest_pairs_that_serve_the_target(day, world, engine_settings):
    ctx = make_context(engine_settings, world.ref)
    catalog = Catalog(engine_settings.plan_duration_position)
    services = {s.service_id: s for s in world.ref.services}
    need = cap.day_need(day, world.orders_on(day), world.orders, world.staff, services, catalog, ctx, engine_settings, 9)
    assert need.orders == sum(1 for o in world.orders_on(day) if o.cancelled_at is None)
    assert 1 <= need.floor <= need.needed <= engine_settings.capacity_max_pairs
    servable = need.orders - need.unservable
    assert need.served >= engine_settings.capacity_serve_share * servable - 1e-9
    if need.needed > max(1, need.floor):  # one pair fewer falls short
        rows = sorted((r for r in world.orders_on(day) if r.cancelled_at is None), key=lambda r: (r.published_at, r.order_id))
        jobs = [to_job(r, services[r.service_id], catalog) for r in rows]
        demand = rosters.expected_demand(world.orders, services, catalog, day, engine_settings)
        fewer = plan_day(day, cap.hypothetical_pairs(need.needed - 1, cap.iv_share(world.staff), demand, engine_settings), jobs, ctx)
        assert fewer.served < engine_settings.capacity_serve_share * servable
