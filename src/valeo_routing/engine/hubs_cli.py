"""`valeo-hubs`: site 0 .. HUB_MAX_COUNT hubs and replay the month under Logistics Valeo v1 with each.

Prints the siting proxy (km from an order to its nearest standby spot) and what the replay actually
drives (km per visit, from totals), with the Excel era alongside. Every plan goes through the validator.
"""
from __future__ import annotations

import argparse
from typing import Dict, List

from valeo_routing.settings import load_engine_settings, load_settings

from . import roster as rosters
from .catalog import Catalog
from .data import engine_labs, load_world, make_context
from .hubs import curve, history_window
from .policy import ExcelEra, LogisticsValeoV1
from .replay import DayKpis, replay_day
from .standby import HubStandby
from .validator import Rules, validate


def main() -> None:
    parser = argparse.ArgumentParser(description="Hub siting and its effect on km per visit.")
    parser.add_argument("--days", type=int, help="replay only the first N days (default: all)")
    args = parser.parse_args()

    settings, engine = load_settings(), load_engine_settings()
    world = load_world(settings.data_reference_dir, settings.demand_profile_path, settings.data_output_dir)
    ctx = make_context(engine, world.ref)
    catalog = Catalog(engine.plan_duration_position)
    services = {s.service_id: s for s in world.ref.services}
    rules = Rules(ctx.dist, ctx.office, engine_labs(world.ref), ctx.tolerance_min, ctx.access_min, ctx.kit_stop_min)

    window, history = history_window(world.orders, engine.hub_history_days)
    sitings = curve([(o.lat, o.lon) for o in history], world.ref.areas, ctx.office, engine.hub_max_count, ctx.dist)
    print("Sited on {} orders, {} to {} (cancelled left out)\n".format(len(history), window[0], window[-1]))
    for s in sitings:
        names = ", ".join("{} {} ({}, {})".format(h.hub_id, h.name, h.emirate, h.orders) for h in s.hubs) or "office only"
        print("  k={}  {:5.1f} km to nearest spot   office keeps {:>4}   {}".format(s.k, s.km_per_order, s.office_orders, names))

    dates = sorted({o.service_date for o in world.orders})[: args.days]
    in_window = set(window)
    policies = {"excel": lambda: ExcelEra(engine, ctx.office)}
    for s in sitings:
        hubs = HubStandby(ctx.office, [(h.name, h.loc) for h in s.hubs], ctx.dist)
        policies["lv1 k={}".format(s.k)] = lambda hubs=hubs: LogisticsValeoV1(engine, ctx.office, hubs)

    totals: Dict[str, Dict[str, DayKpis]] = {name: {"all": DayKpis(), "in": DayKpis(), "out": DayKpis()} for name in policies}
    bad: Dict[str, int] = {name: 0 for name in policies}
    for day in dates:
        demand = rosters.expected_demand(world.orders, services, catalog, day, engine)
        pairs = rosters.allocate(day, world.staff, world.availability, demand, engine).pairs
        rows = world.orders_on(day)
        for name, make in policies.items():
            result = replay_day(day, pairs, rows, services, catalog, ctx, make(), engine.replay_seed)
            bad[name] += len(validate(result.plan, result.jobs, rules))
            t = totals[name]
            t["all"] += result.kpis
            t["in" if day in in_window else "out"] += result.kpis

    print("\nReplay of {} days, auto roster. km per visit = total km / visits (way home included).".format(len(dates)))
    print("'sited on' = the {} days the hubs were sited on; 'other days' were not used for siting.\n".format(len(in_window)))
    head = "{:<12}{:>8}{:>10}{:>11}{:>12}{:>13}{:>9}{:>8}{:>10}"
    print(head.format("", "visits", "km", "km/visit", "sited on", "other days", "capture", "idle h", "violations"))
    for name, t in totals.items():
        k = t["all"]
        print("{:<12}{:>8}{:>10.0f}{:>11.1f}{:>12.1f}{:>13.1f}{:>8.1%}{:>8.0f}{:>10}".format(
            name, k.visits, k.km, k.km_per_visit, t["in"].km_per_visit, t["out"].km_per_visit,
            k.capture_rate, k.idle_h, bad[name]))


if __name__ == "__main__":
    main()
