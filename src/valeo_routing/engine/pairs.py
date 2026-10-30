"""A placeholder roster: pair up whoever is available. Replaced by the auto-allocating roster in PLAN step 5."""
from __future__ import annotations

from datetime import date
from typing import List, Sequence

from .data import AvailabilityRow, StaffRow
from .model import Pair


def build_pairs(
    day: date, staff: Sequence[StaffRow], availability: Sequence[AvailabilityRow],
    shift_starts_min: Sequence[int], shift_hours: float,
) -> List[Pair]:
    """Pair the i-th available nurse with the i-th available driver; shift starts cycle over the pairs.

    Sick calls and rest days are respected (they are not 'available'). Late starts and car breakdowns
    are not yet applied.
    """
    on_duty = {a.staff_id for a in availability if a.date == day and a.status == "available"}
    nurses = sorted((s for s in staff if s.role == "nurse" and s.staff_id in on_duty), key=lambda s: s.staff_id)
    drivers = sorted((s for s in staff if s.role == "driver" and s.staff_id in on_duty), key=lambda s: s.staff_id)
    length = int(round(shift_hours * 60))
    pairs = []
    for i, (nurse, driver) in enumerate(zip(nurses, drivers)):
        start = shift_starts_min[i % len(shift_starts_min)]
        pairs.append(Pair("P{:02d}".format(i + 1), nurse.staff_id, driver.staff_id, driver.usual_car_id,
                          nurse.iv_certified, start, start + length))
    return pairs
