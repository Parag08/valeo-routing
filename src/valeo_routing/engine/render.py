"""Text views of a day plan: a summary and a one-line-per-pair timeline."""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from .model import DRIVE, LAB, OFFICE, STANDBY, VISIT, Block, DayPlan

GLYPH = {VISIT: "V", LAB: "L", OFFICE: "o", DRIVE: ">", STANDBY: "s"}
PRIORITY = [VISIT, LAB, OFFICE, DRIVE, STANDBY]


def clock(minutes: int) -> str:
    return "{:02d}:{:02d}".format(minutes // 60 % 24, minutes % 60)


def gantt(plan: DayPlan, start_min: int = 5 * 60, end_min: int = 23 * 60, step: int = 15) -> List[str]:
    """One row per pair. V visit, L lab drop, o office kit stop, > driving, s standby, . on shift but idle."""
    ticks = [" "] * ((end_min - start_min) // step)
    for m in range(start_min, end_min, 60):
        label = "{:02d}".format(m // 60)
        i = (m - start_min) // step
        ticks[i:i + 2] = list(label)
    rows = ["{:<22}{}".format("", "".join(ticks))]
    for pid, day in plan.pairs.items():
        cells = []
        for m in range(start_min, end_min, step):
            overlap: Counter = Counter()
            for b in day.blocks:
                lo, hi = max(b.start, m), min(b.end, m + step)
                if hi > lo:
                    overlap[b.kind] += hi - lo
            if overlap:
                top = max(overlap.values())
                cells.append(GLYPH[next(k for k in PRIORITY if overlap[k] == top)])
            elif day.pair.shift_start_min <= m < day.pair.shift_end_min:
                cells.append(".")
            else:
                cells.append(" ")
        rows.append("{:<22}{}".format(
            "{} {}-{} {:>2}v".format(pid, clock(day.pair.shift_start_min), clock(day.pair.shift_end_min), len(day.job_ids)),
            "".join(cells)))
    return rows


def summary(plan: DayPlan) -> Dict[str, float]:
    served = plan.served
    visit = sum(d.minutes(VISIT) for d in plan.pairs.values())
    drive = sum(d.minutes(DRIVE) for d in plan.pairs.values())
    standby = sum(d.minutes(STANDBY) for d in plan.pairs.values())
    return {
        "served": served,
        "rejected": len(plan.rejected),
        "km": plan.km,
        "km_per_order": plan.km / served if served else 0.0,
        "visit_h": visit / 60.0,
        "drive_h": drive / 60.0,
        "standby_h": standby / 60.0,
    }
