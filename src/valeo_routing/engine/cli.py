"""`valeo-plan`: plan one real day of the generated month and print it with a validation result."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime

from valeo_routing.settings import load_engine_settings, load_settings

from .catalog import Catalog
from .data import engine_labs, load_world, make_context, to_job
from .pairs import build_pairs
from .planner import plan_day
from .render import clock, gantt, summary
from .standby import OfficeStandby, StayStandby
from .validator import Rules, validate


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan one day of the generated month.")
    parser.add_argument("--date", help="service date, YYYY-MM-DD (default: the first generated day)")
    parser.add_argument("--standby", choices=("office", "stay"), default="office",
                        help="where pairs wait in idle gaps: back at the office (Excel era) or in place")
    args = parser.parse_args()

    settings, engine = load_settings(), load_engine_settings()
    world = load_world(settings.data_reference_dir, settings.demand_profile_path, settings.data_output_dir)
    day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else settings.data_start_date

    office = (world.ref.office.lat, world.ref.office.lon)
    ctx = make_context(engine, world.ref, OfficeStandby(office) if args.standby == "office" else StayStandby())
    catalog = Catalog(engine.plan_duration_position)
    services = {s.service_id: s for s in world.ref.services}

    pairs = build_pairs(day, world.staff, world.availability, engine.shift_start_minutes, engine.shift_hours)
    rows = [o for o in world.orders_on(day) if o.cancelled_at is None]
    jobs = [to_job(o, services[o.service_id], catalog) for o in rows]
    plan = plan_day(day, pairs, jobs, ctx)

    rules = Rules(ctx.dist, ctx.office, engine_labs(world.ref), ctx.tolerance_min, ctx.access_min, ctx.kit_stop_min)
    violations = validate(plan, {j.job_id: j for j in jobs}, rules)

    s = summary(plan)
    print("{} {}  standby: {}  pairs on duty: {}  orders: {} (cancelled ones left out)".format(
        day.strftime("%a"), day, args.standby, len(pairs), len(rows)))
    print("served {}  rejected {}  km {:.0f}  km/order {:.1f}  visits {:.1f} h  driving {:.1f} h  standby {:.1f} h".format(
        s["served"], s["rejected"], s["km"], s["km_per_order"], s["visit_h"], s["drive_h"], s["standby_h"]))
    if plan.rejected:
        print("rejected by reason: " + ", ".join(
            "{} {}".format(k, v) for k, v in sorted(Counter(r.reason for r in plan.rejected).items())))
    print("validator: " + ("valid, no violations" if not violations else "{} VIOLATIONS".format(len(violations))))
    for v in violations[:10]:
        print("  {} {} {} {}".format(v.code, v.pair_id, v.job_id, v.detail))
    print()
    print("V visit  L lab drop  o office kits  > driving  s standby  . on shift, idle")
    print("\n".join(gantt(plan)))


if __name__ == "__main__":
    main()
