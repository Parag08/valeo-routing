"""When someone acts on a newly published order: ops by hand in the Excel era, the tool with v1 rules.

A policy answers one question per order: at what time is it decided, and by whom? The replay then
asks the planner whether the order fits at that moment, and checks it against the competitor's claim.
Times are minutes after midnight of the service date; an order published the day before has a
negative `published_min`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

from valeo_routing.settings import EngineSettings

from .model import Job
from .standby import OfficeStandby, StandbyPolicy

DAY = 24 * 60
AUTO, MANUAL, EXCEL = "auto", "manual", "excel"


@dataclass(frozen=True)
class Decision:
    time_min: int
    mode: str  # auto / manual / excel


class AcceptancePolicy(Protocol):
    name: str
    standby: StandbyPolicy

    def when(self, job: Job, rng: random.Random) -> Decision: ...


def next_open(t: int, open_min: int, close_min: int) -> int:
    """The first moment at or after `t` that falls inside office hours."""
    day_start = (t // DAY) * DAY
    tod = t - day_start
    if open_min <= tod < close_min:
        return t
    return day_start + open_min if tod < open_min else day_start + DAY + open_min


def quiet_minutes(start: int, end: int, window: Tuple[int, int]) -> int:
    """Minutes of [start, end) that fall in the quiet-hours window, which may wrap past midnight."""
    q_start, q_end = window
    spans = [(q_start, q_end)] if q_start < q_end else [(0, q_end), (q_start, DAY)]
    total = 0
    for day in range((start // DAY) - 1, (end // DAY) + 1):
        for lo, hi in spans:
            total += max(0, min(end, day * DAY + hi) - max(start, day * DAY + lo))
    return total


def effective_lead_h(job: Job, window: Tuple[int, int]) -> float:
    """Hours between publishing and the slot, not counting quiet hours: the time ops really have to react."""
    lead = job.slot_min - job.published_min
    return (lead - quiet_minutes(job.published_min, job.slot_min, window)) / 60.0


class ExcelEra:
    """Ops see an order when they next sit down (office hours), then take a while to decide."""

    name = "excel"

    def __init__(self, s: EngineSettings, office: Tuple[float, float]):
        self.office_open, self.office_close = s.office_window
        self.lo, self.hi = s.excel_response_min_lo, s.excel_response_min_hi
        self.standby: StandbyPolicy = OfficeStandby(office)

    def when(self, job: Job, rng: random.Random) -> Decision:
        seen = next_open(job.published_min, self.office_open, self.office_close)
        return Decision(seen + rng.randint(self.lo, self.hi), EXCEL)


class LogisticsValeoV1:
    """Accept by itself when ops would have time to react; otherwise hand to ops with the slots shown."""

    name = "lv1"

    def __init__(self, s: EngineSettings, office: Tuple[float, float], standby: Optional[StandbyPolicy] = None):
        self.office_open, self.office_close = s.office_window
        self.quiet = s.quiet_window
        self.threshold_h = s.auto_accept_lead_h
        self.lo, self.hi = s.manual_response_min_lo, s.manual_response_min_hi
        # Idle pairs go back to the office until hubs are sited and applied (HubStandby).
        self.standby: StandbyPolicy = standby if standby is not None else OfficeStandby(office)

    def when(self, job: Job, rng: random.Random) -> Decision:
        if effective_lead_h(job, self.quiet) >= self.threshold_h:
            return Decision(job.published_min, AUTO)
        seen = next_open(job.published_min, self.office_open, self.office_close)
        return Decision(seen + rng.randint(self.lo, self.hi), MANUAL)
