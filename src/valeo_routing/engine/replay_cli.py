"""`valeo-replay`: replay days of the generated month under the Excel-era and Logistics Valeo v1 policies."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from typing import Dict, List

from valeo_routing.settings import load_engine_settings, load_settings

from .catalog import Catalog
from .data import engine_labs, load_world, make_context
from .pairs import build_pairs
from .policy import ExcelEra, LogisticsValeoV1
from .replay import DayKpis, DayResult, replay_day
from .validator import Rules, validate

LABELS = {"excel": "Excel era", "lv1": "Logistics Valeo v1"}


def when(minutes: int) -> str:
    """Minutes after midnight of the service date, as 'HH:MM', with a day offset for earlier days."""
    d, tod = divmod(minutes, 24 * 60)
    return "{:02d}:{:02d}".format(tod // 60, tod % 60) + ("" if d == 0 else " {:+d}d".format(d))


def table(totals: Dict[str, DayKpis], violations: Dict[str, int]) -> List[str]:
    head = "{:<20}{:>10}{:>9}{:>6}{:>9}{:>9}{:>8}{:>10}{:>8}{:>6}".format(
        "", "capturable", "accepted", "lost", "declined", "capture", "visits", "km/visit", "idle h", "valid")
    rows = [head]
    for name, k in totals.items():
        rows.append("{:<20}{:>10}{:>9}{:>6}{:>9}{:>8.0%}{:>8}{:>10.1f}{:>8.0f}{:>6}".format(
            LABELS[name], k.capturable, k.accepted, k.lost, k.declined, k.capture_rate, k.visits,
            k.km_per_visit, k.idle_h, "yes" if violations[name] == 0 else "NO"))
    return rows


def log_lines(result: DayResult) -> List[str]:
    fmt = "{:<18}{:>11}{:>11}{:>8}  {:<7}{:<26}{:<5}{:<19}{}"
    lines = [fmt.format("order", "published", "decided", "slot", "mode", "outcome", "pair", "final", "why")]
    for r in result.log:
        lines.append(fmt.format(r.order_id, when(r.published_min), when(r.decided_min), when(r.slot_min),
                                r.mode, r.outcome, r.pair_id or "", r.final, r.reason))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay days under both acceptance policies.")
    parser.add_argument("--date", help="first service date, YYYY-MM-DD (default: the first generated day)")
    parser.add_argument("--days", type=int, default=7, help="how many consecutive days (default 7)")
    parser.add_argument("--log", action="store_true", help="print the first day's Logistics Valeo decision log")
    args = parser.parse_args()

    settings, engine = load_settings(), load_engine_settings()
    world = load_world(settings.data_reference_dir, settings.demand_profile_path, settings.data_output_dir)
    first = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else settings.data_start_date
    ctx = make_context(engine, world.ref)
    catalog = Catalog(engine.plan_duration_position)
    services = {s.service_id: s for s in world.ref.services}
    rules = Rules(ctx.dist, ctx.office, engine_labs(world.ref), ctx.tolerance_min, ctx.access_min, ctx.kit_stop_min)
    policies = [ExcelEra(engine, ctx.office), LogisticsValeoV1(engine, ctx.office)]

    totals = {p.name: DayKpis() for p in policies}
    violations = {p.name: 0 for p in policies}
    per_day: List[str] = []
    first_lv1 = None
    for offset in range(args.days):
        day = first + timedelta(days=offset)
        pairs = build_pairs(day, world.staff, world.availability, engine.shift_start_minutes, engine.shift_hours)
        rows = world.orders_on(day)
        captured = {}
        for policy in policies:
            result = replay_day(day, pairs, rows, services, catalog, ctx, policy, engine.replay_seed)
            totals[policy.name] += result.kpis
            violations[policy.name] += len(validate(result.plan, result.jobs, rules))
            captured[policy.name] = result.kpis
            if policy.name == "lv1" and first_lv1 is None:
                first_lv1 = result
        per_day.append("  {} {}  orders {:>3}  pairs {:>2}   capture: excel {:>4.0%}  lv1 {:>4.0%}".format(
            day.strftime("%a"), day, len(rows), len(pairs), captured["excel"].capture_rate, captured["lv1"].capture_rate))

    print("Replay of {} day(s) from {}; roster: placeholder (all pairs available that day)\n".format(args.days, first))
    print("\n".join(per_day))
    print()
    print("\n".join(table(totals, violations)))
    if args.log and first_lv1 is not None:
        print("\nDecision log, Logistics Valeo v1, {} (times relative to that day; -1d = the day before)\n".format(first_lv1.day))
        print("\n".join(log_lines(first_lv1)))


if __name__ == "__main__":
    main()
