"""Hub siting: where standby hubs should sit, from the last days of synthetic orders.

K-median over a discrete set of candidates. The candidates are the public area centroids in areas.csv,
which are on land in their own emirate (checked by the service area and by OSM; see DATA.md), so a hub is
a neighbourhood, never a real site. Demand is every order in the history window that the patient did not
cancel, at its synthetic location, weighted equally.

The office is always open as a standby spot, so the objective is the mean road km from an order to its
nearest spot, office or hub, and k = 0 is the Excel era's office-only standby. Siting is greedy (add the
candidate that lowers the objective most, k times), then local swap (Teitz-Bart: replace an open hub with
a closed candidate whenever that lowers the objective, until none does). Ties go to the lower area id,
so the same orders always give the same hubs.

This is a proxy: it measures how far demand sits from a standby spot, not the km a day actually drives.
The replay with `HubStandby` measures that.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Sequence, Tuple

from valeo_routing.datagen.reference import Area

from .data import OrderRow
from .distance import DistanceModel
from .model import Loc

EPS = 1e-9


@dataclass(frozen=True)
class Hub:
    hub_id: str  # 'H1' serves the most orders, 'H2' the next, ...
    area_id: str
    name: str  # the area's public name
    emirate: str
    loc: Loc
    orders: int  # history orders whose nearest standby spot is this hub


@dataclass(frozen=True)
class Siting:
    k: int
    hubs: Tuple[Hub, ...]
    km_per_order: float  # mean road km from an order to its nearest standby spot (office or hub)
    office_orders: int  # history orders whose nearest spot is still the office


def history_window(orders: Sequence[OrderRow], days: int) -> Tuple[List[date], List[OrderRow]]:
    """The last `days` service dates in the data, and their orders that were not cancelled."""
    dates = sorted({o.service_date for o in orders})[-days:]
    keep = set(dates)
    return dates, [o for o in orders if o.service_date in keep and o.cancelled_at is None]


class _Matrix:
    """Road km from every demand point to the office and to every candidate."""

    def __init__(self, points: Sequence[Loc], candidates: Sequence[Area], office: Loc, dist: DistanceModel):
        self.office = [dist.km(p, office) for p in points]
        self.to = [[dist.km(p, (c.lat, c.lon)) for c in candidates] for p in points]

    def cost(self, open_: Sequence[int]) -> float:
        return sum(min([o] + [row[j] for j in open_]) for o, row in zip(self.office, self.to))


def site(points: Sequence[Loc], candidates: Sequence[Area], office: Loc, k: int, dist: DistanceModel) -> Siting:
    """The best `k` hubs for `points` among `candidates`, the office always open."""
    cands = sorted(candidates, key=lambda c: c.area_id)
    if not 0 <= k <= len(cands):
        raise ValueError("k must be between 0 and {}".format(len(cands)))
    m = _Matrix(points, cands, office, dist)
    return _siting(points, cands, m, _local_swap(m, _greedy(m, k, len(cands)), len(cands)))


def curve(points: Sequence[Loc], candidates: Sequence[Area], office: Loc, max_k: int,
          dist: DistanceModel) -> List[Siting]:
    """Sitings for k = 0 .. max_k, sharing one distance matrix."""
    cands = sorted(candidates, key=lambda c: c.area_id)
    m = _Matrix(points, cands, office, dist)
    return [_siting(points, cands, m, _local_swap(m, _greedy(m, k, len(cands)), len(cands))) for k in range(max_k + 1)]


def _greedy(m: _Matrix, k: int, n: int) -> List[int]:
    chosen: List[int] = []
    for _ in range(k):
        best = min((j for j in range(n) if j not in chosen), key=lambda j: (round(m.cost(chosen + [j]), 6), j))
        chosen.append(best)
    return chosen


def _local_swap(m: _Matrix, chosen: List[int], n: int) -> List[int]:
    current = list(chosen)
    cost = m.cost(current)
    improved = True
    while improved:
        improved = False
        for i in range(len(current)):
            for j in range(n):
                if j in current:
                    continue
                trial = current[:i] + [j] + current[i + 1:]
                c = m.cost(trial)
                if c < cost - EPS:
                    current, cost, improved = trial, c, True
    return current


def _siting(points: Sequence[Loc], cands: Sequence[Area], m: _Matrix, open_: Sequence[int]) -> Siting:
    counts: Dict[int, int] = {j: 0 for j in open_}
    office_orders = 0
    for o, row in zip(m.office, m.to):
        j = min(open_, key=lambda x: (row[x], cands[x].area_id)) if open_ else None
        if j is None or o <= row[j]:
            office_orders += 1
        else:
            counts[j] += 1
    ranked = sorted(open_, key=lambda j: (-counts[j], cands[j].area_id))
    hubs = tuple(
        Hub("H{}".format(i + 1), cands[j].area_id, cands[j].area_name, cands[j].emirate,
            (cands[j].lat, cands[j].lon), counts[j])
        for i, j in enumerate(ranked)
    )
    km = m.cost(open_) / len(points) if points else 0.0
    return Siting(len(open_), hubs, km, office_orders)
