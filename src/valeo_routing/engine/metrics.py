"""Metrics: predicted against "actual" km and time, and how a saving is measured.

**Predicted** is what the planner used: straight-line distance x the road factor, at the hour's speed.
**Actual** stands in for a vehicle tracker. The demo has no real ground data, so each drive's recorded km
and minutes are the prediction times a seeded log-normal draw (`METRICS_KM_BIAS`, `METRICS_TIME_BIAS` and
their sigmas): synthetic, and labelled so. Trackers also fail. On some days one pair's tracker drops out
part-way through the shift (its recorded km stop short), and on others it records a GPS jump (extra km
that were never driven).

**Exclusion rules.** A day is left out of every total when any pair's tracker covered less than
`METRICS_MIN_COVERAGE` of its shift, or recorded more than `METRICS_MAX_PAIR_RATIO` x its predicted km.
The reason is kept, so the exclusion is visible.

**The saving** is measured as the real project measured it:

* km per visit from totals (sum of km / sum of visits over the clean days), not the average of daily ratios
* baseline (Excel era) against the tool, on the same clean days and the same demand
* km saved = (baseline km per visit - tool km per visit) x the tool's visits
* valued at the marginal cost per km (fuel, tolls, parking). Salaries and rental don't fall when cars drive
  less, so the all-in average would overstate it; it is shown only to show by how much.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

from valeo_routing.settings import EngineSettings

from .model import DRIVE, DayPlan


@dataclass(frozen=True)
class PairMetrics:
    pair_id: str
    visits: int
    predicted_km: float
    actual_km: float
    predicted_drive_min: int
    actual_drive_min: float
    coverage: float  # share of the shift the tracker recorded
    fault: str = ""  # '' / 'gap' / 'spike'

    @property
    def km_ratio(self) -> float:
        return self.actual_km / self.predicted_km if self.predicted_km else 1.0


@dataclass(frozen=True)
class DayMetrics:
    day: date
    visits: int
    pairs: List[PairMetrics]
    excluded: str = ""  # why the day is left out of the totals; '' when it is clean

    @property
    def predicted_km(self) -> float:
        return sum(p.predicted_km for p in self.pairs)

    @property
    def actual_km(self) -> float:
        return sum(p.actual_km for p in self.pairs)

    @property
    def predicted_drive_min(self) -> int:
        return sum(p.predicted_drive_min for p in self.pairs)

    @property
    def actual_drive_min(self) -> float:
        return sum(p.actual_drive_min for p in self.pairs)


def _draw(rng: random.Random, bias: float, sigma: float) -> float:
    """A multiplier with mean `bias`: log-normal, so it is never negative."""
    return bias * math.exp(rng.gauss(0.0, sigma) - sigma * sigma / 2.0)


def track_day(day: date, plan: DayPlan, visits: int, s: EngineSettings) -> DayMetrics:
    """The synthetic tracker's record of one planned day, and whether the day is clean.

    Draws depend only on the seed, the day and the pair, so the same plan always gets the same record,
    and a day's faults are the same whichever policy planned it.
    """
    day_rng = random.Random("{}|{}|faults".format(s.metrics_seed, day))
    pair_ids = sorted(plan.pairs)
    fault, faulty = "", None
    roll = day_rng.random()
    if roll < s.metrics_gap_day_rate:
        fault = "gap"
    elif roll < s.metrics_gap_day_rate + s.metrics_spike_day_rate:
        fault = "spike"
    if fault and pair_ids:
        faulty = day_rng.choice(pair_ids)
    gap_share = day_rng.uniform(0.35, 0.8)  # share of the shift recorded when the tracker drops out
    spike_km = day_rng.uniform(60.0, 220.0)  # km a GPS jump adds

    pairs: List[PairMetrics] = []
    for pid in pair_ids:
        pd = plan.pairs[pid]
        rng = random.Random("{}|{}|{}".format(s.metrics_seed, day, pid))
        shift = pd.pair.shift_end_min - pd.pair.shift_start_min
        cutoff = pd.pair.shift_start_min + gap_share * shift if pid == faulty and fault == "gap" else None
        predicted_km = actual_km = actual_min = 0.0
        predicted_min = 0
        for b in pd.blocks:
            if b.kind != DRIVE:
                continue
            k, t = _draw(rng, s.metrics_km_bias, s.metrics_km_sigma), _draw(rng, s.metrics_time_bias, s.metrics_time_sigma)
            predicted_km += b.km
            predicted_min += b.end - b.start
            if cutoff is None or b.start < cutoff:
                actual_km += b.km * k
                actual_min += (b.end - b.start) * t
        coverage = gap_share if cutoff is not None else 1.0
        if pid == faulty and fault == "spike":
            actual_km += spike_km
        pairs.append(PairMetrics(pid, len(pd.job_ids), predicted_km, actual_km, predicted_min, actual_min, coverage,
                                 fault if pid == faulty else ""))
    return DayMetrics(day, visits, pairs, _exclusion(pairs, s))


def _exclusion(pairs: Sequence[PairMetrics], s: EngineSettings) -> str:
    for p in pairs:
        if p.coverage < s.metrics_min_coverage:
            return "tracker offline on {}: {:.0%} of the shift recorded (rule: at least {:.0%})".format(
                p.pair_id, p.coverage, s.metrics_min_coverage)
        if p.predicted_km and p.km_ratio > s.metrics_max_pair_ratio:
            return "{} recorded {:.1f}x its predicted km, a GPS jump (rule: at most {:.1f}x)".format(
                p.pair_id, p.km_ratio, s.metrics_max_pair_ratio)
    return ""


@dataclass
class Totals:
    """Sums over a set of days, so ratios are taken from totals."""

    days: int = 0
    visits: int = 0
    predicted_km: float = 0.0
    actual_km: float = 0.0
    predicted_drive_min: float = 0.0
    actual_drive_min: float = 0.0
    daily_km_per_visit: List[float] = field(default_factory=list)

    @classmethod
    def of(cls, days: Sequence[DayMetrics]) -> "Totals":
        t = cls()
        for d in days:
            t.days += 1
            t.visits += d.visits
            t.predicted_km += d.predicted_km
            t.actual_km += d.actual_km
            t.predicted_drive_min += d.predicted_drive_min
            t.actual_drive_min += d.actual_drive_min
            if d.visits:
                t.daily_km_per_visit.append(d.actual_km / d.visits)
        return t

    @property
    def km_per_visit(self) -> float:
        """From totals: sum of km / sum of visits."""
        return self.actual_km / self.visits if self.visits else 0.0

    @property
    def mean_of_daily(self) -> float:
        """The average of each day's ratio: shown only to compare against the total."""
        return sum(self.daily_km_per_visit) / len(self.daily_km_per_visit) if self.daily_km_per_visit else 0.0


@dataclass(frozen=True)
class Saving:
    baseline: Totals
    tool: Totals
    km_saved: float
    marginal: float  # value at the marginal rate
    all_in: float  # what the all-in rate would claim

    @classmethod
    def measure(cls, baseline: Sequence[DayMetrics], tool: Sequence[DayMetrics], s: EngineSettings) -> "Saving":
        """Both lists are the same clean days, in the same order, under the two policies."""
        b, t = Totals.of(baseline), Totals.of(tool)
        km = (b.km_per_visit - t.km_per_visit) * t.visits
        return cls(b, t, km, km * s.cost_per_km_marginal, km * s.cost_per_km_all_in)


def clean(days: Sequence[DayMetrics]) -> List[DayMetrics]:
    return [d for d in days if not d.excluded]


def error_share(pairs: Sequence[PairMetrics]) -> Optional[float]:
    """Median absolute km error per pair-day, as a share of the prediction (pairs that drove at all)."""
    errors = sorted(abs(p.km_ratio - 1.0) for p in pairs if p.predicted_km > 0)
    if not errors:
        return None
    mid = len(errors) // 2
    return errors[mid] if len(errors) % 2 else (errors[mid - 1] + errors[mid]) / 2.0
