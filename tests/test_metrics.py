"""Metrics: the synthetic tracker, the exclusion rules and measuring a saving from totals."""
from __future__ import annotations

from datetime import date

import pytest

from valeo_routing.engine.metrics import DayMetrics, PairMetrics, Saving, Totals, clean, error_share, track_day
from valeo_routing.engine.model import DRIVE, Block, DayPlan, Pair, PairDay
from valeo_routing.settings import EngineSettings

from .conftest import ROOT


@pytest.fixture(scope="module")
def s() -> EngineSettings:
    return EngineSettings(_env_file=str(ROOT / ".env.example"))


def _plan(day=date(2026, 11, 4), pairs=4):
    out = {}
    for i in range(pairs):
        p = Pair("P{:02d}".format(i + 1), "N", "D", "C", False, 480, 1200)
        blocks = [Block(DRIVE, 480 + 60 * k, 500 + 60 * k, (25.0, 55.0), (25.1, 55.1), 12.0) for k in range(8)]
        out[p.pair_id] = PairDay(p, ["J{}".format(k) for k in range(4)], blocks)
    return DayPlan(day, out)


def test_tracker_is_deterministic_and_biased_as_configured(s):
    days = [track_day(date(2026, 11, d), _plan(date(2026, 11, d)), 16, s) for d in range(1, 29)]
    again = track_day(date(2026, 11, 4), _plan(), 16, s)
    assert days[3] == again
    kept = Totals.of(clean(days))
    assert kept.actual_km / kept.predicted_km == pytest.approx(s.metrics_km_bias, rel=0.05)
    assert kept.actual_drive_min / kept.predicted_drive_min == pytest.approx(s.metrics_time_bias, rel=0.06)


def test_faulty_days_are_excluded_with_a_reason(s):
    always_gap = s.model_copy(update={"metrics_gap_day_rate": 1.0, "metrics_spike_day_rate": 0.0})
    always_spike = s.model_copy(update={"metrics_gap_day_rate": 0.0, "metrics_spike_day_rate": 1.0})
    never = s.model_copy(update={"metrics_gap_day_rate": 0.0, "metrics_spike_day_rate": 0.0})
    gap, spike, fine = (track_day(date(2026, 11, 4), _plan(), 16, x) for x in (always_gap, always_spike, never))
    assert gap.excluded.startswith("tracker offline") and sum(p.fault == "gap" for p in gap.pairs) == 1
    assert "GPS jump" in spike.excluded and sum(p.fault == "spike" for p in spike.pairs) == 1
    assert fine.excluded == "" and clean([gap, spike, fine]) == [fine]


def test_km_per_visit_comes_from_totals_not_daily_ratios():
    pm = lambda km: [PairMetrics("P01", 1, km, km, 10, 10.0, 1.0)]
    days = [DayMetrics(date(2026, 11, 1), 10, pm(300.0)), DayMetrics(date(2026, 11, 2), 40, pm(800.0))]
    t = Totals.of(days)
    assert t.km_per_visit == pytest.approx(1100 / 50)
    assert t.mean_of_daily == pytest.approx((30 + 20) / 2)


def test_saving_is_valued_at_the_marginal_rate(s):
    pm = lambda km: [PairMetrics("P01", 1, km, km, 10, 10.0, 1.0)]
    base = [DayMetrics(date(2026, 11, 1), 20, pm(800.0))]  # 40 km per visit
    tool = [DayMetrics(date(2026, 11, 1), 25, pm(750.0))]  # 30 km per visit
    sv = Saving.measure(base, tool, s)
    assert sv.km_saved == pytest.approx(250.0)
    assert sv.marginal == pytest.approx(250 * s.cost_per_km_marginal)
    assert sv.all_in > sv.marginal


def test_error_share_is_a_median():
    pairs = [PairMetrics("P", 1, 100.0, km, 1, 1.0, 1.0) for km in (90.0, 105.0, 130.0)]
    assert error_share(pairs) == pytest.approx(0.10)
    assert error_share([]) is None
