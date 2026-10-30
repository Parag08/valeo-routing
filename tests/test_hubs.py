"""Hub siting (K-median), the hub standby policy, and replays with hubs through the validator."""
from __future__ import annotations

from datetime import date
from itertools import combinations

import pytest

from valeo_routing.datagen.reference import load_reference
from valeo_routing.engine import roster as rosters
from valeo_routing.engine.catalog import Catalog
from valeo_routing.engine.data import engine_labs, load_world, make_context
from valeo_routing.engine.hubs import _Matrix, curve, history_window, site
from valeo_routing.engine.policy import LogisticsValeoV1
from valeo_routing.engine.replay import replay_day
from valeo_routing.engine.standby import HubStandby
from valeo_routing.engine.validator import Rules, validate
from valeo_routing.service_area import ServiceArea
from valeo_routing.settings import EngineSettings

from .conftest import ROOT

REF_DIR = ROOT / "data" / "reference"


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
def world(settings, written):
    return load_world(settings.data_reference_dir, settings.demand_profile_path, written)


@pytest.fixture(scope="module")
def sitings(world, ref, ctx, engine_settings):
    _, history = history_window(world.orders, engine_settings.hub_history_days)
    return curve([(o.lat, o.lon) for o in history], ref.areas, ctx.office, engine_settings.hub_max_count, ctx.dist)


def test_history_window_is_the_last_days_without_cancellations(world, engine_settings):
    dates, history = history_window(world.orders, engine_settings.hub_history_days)
    all_dates = sorted({o.service_date for o in world.orders})
    assert dates == all_dates[-engine_settings.hub_history_days:]
    assert history and all(o.cancelled_at is None and o.service_date in set(dates) for o in history)


def test_more_hubs_never_cost_more(sitings, engine_settings):
    assert [s.k for s in sitings] == list(range(engine_settings.hub_max_count + 1))
    assert sitings[0].hubs == () and sitings[0].office_orders > 0
    for a, b in zip(sitings, sitings[1:]):
        assert b.km_per_order <= a.km_per_order + 1e-9
    assert sitings[1].km_per_order < sitings[0].km_per_order


def test_hubs_are_area_centroids_on_land_in_their_own_emirate(sitings, ref):
    land = ServiceArea(REF_DIR / "service_area.geojson")
    areas = {a.area_id: a for a in ref.areas}
    for s in sitings:
        assert len({h.area_id for h in s.hubs}) == s.k
        assert sum(h.orders for h in s.hubs) + s.office_orders > 0
        for h in s.hubs:
            area = areas[h.area_id]
            assert h.loc == (area.lat, area.lon) and h.emirate == area.emirate
            assert land.emirate_at(*h.loc) == h.emirate, h


def test_siting_is_deterministic(world, ref, ctx, sitings):
    _, history = history_window(world.orders, 30)
    again = site([(o.lat, o.lon) for o in history], list(reversed(ref.areas)), ctx.office, 2, ctx.dist)
    assert [h.area_id for h in again.hubs] == [h.area_id for h in sitings[2].hubs]


def test_greedy_plus_swap_matches_brute_force_on_a_small_case(world, ref, ctx):
    points = [(o.lat, o.lon) for o in world.orders[:150]]
    cands = sorted(ref.areas, key=lambda a: a.area_id)[:14]
    m = _Matrix(points, cands, ctx.office, ctx.dist)
    best = min(m.cost(list(c)) for c in combinations(range(len(cands)), 2))
    found = site(points, cands, ctx.office, 2, ctx.dist)
    assert found.km_per_order * len(points) == pytest.approx(best, rel=1e-9)


def test_hub_standby_picks_the_smallest_detour(ctx):
    near_a, near_b = (25.07, 55.14), (25.30, 55.38)  # Marina side, Sharjah side
    policy = HubStandby(ctx.office, [("west", (25.08, 55.15)), ("north", (25.31, 55.39))], ctx.dist)
    assert policy.spot(near_a, near_a).note == "hub west"
    assert policy.spot(near_b, near_b).note == "hub north"
    assert policy.spot(ctx.office, ctx.office).note == "office"  # the office wins when it costs nothing


@pytest.mark.parametrize("day", [date(2026, 11, 4), date(2026, 11, 21), date(2026, 12, 2)])
def test_replays_with_hubs_are_valid_and_drive_less(day, world, ref, ctx, sitings, engine_settings):
    catalog = Catalog(engine_settings.plan_duration_position)
    services = {s.service_id: s for s in ref.services}
    demand = rosters.expected_demand(world.orders, services, catalog, day, engine_settings)
    pairs = rosters.allocate(day, world.staff, world.availability, demand, engine_settings).pairs
    rules = Rules(ctx.dist, ctx.office, engine_labs(ref), ctx.tolerance_min, ctx.access_min, ctx.kit_stop_min)
    km = {}
    for s in (sitings[0], sitings[engine_settings.hub_count]):
        standby = HubStandby(ctx.office, [(h.name, h.loc) for h in s.hubs], ctx.dist)
        result = replay_day(day, pairs, world.orders_on(day), services, catalog, ctx,
                            LogisticsValeoV1(engine_settings, ctx.office, standby), engine_settings.replay_seed)
        assert validate(result.plan, result.jobs, rules) == []
        km[s.k] = result.kpis.km
        if s.k:
            notes = {b.note for d in result.plan.pairs.values() for b in d.blocks if b.kind == "standby"}
            assert any(n.startswith("hub ") for n in notes)
    assert km[engine_settings.hub_count] < km[0]
