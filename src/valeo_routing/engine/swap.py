"""Logistics Valeo v2 (designed, not shipped): when a new order does not fit, make room for it.

v1 declines an order that no pair can take. v2 first looks for room, in two ways, and only among accepted
orders that have not started and whose slot is within `V2_SEARCH_WINDOW_MIN` of the new one (the visits
that can be in its way):

* **Move.** Take accepted order `o` off pair A, put the new order on A, and give `o` to any pair that can
  still serve it. Nothing is lost, so the move that adds the fewest km wins.
* **Swap.** If `o` fits nowhere else, it is released back to the platform, so another provider can take it,
  and the new order takes its place. That is only worth it when the fleet comes out ahead:

      gain = (km A drives with o) - (km A drives with the new order)
             + V2_VISIT_VALUE_KM * (P(new order is kept) - P(o is kept))

  and the swap goes ahead only when the gain is at least `V2_SWAP_MIN_GAIN_KM` and `o`'s slot is at least
  `V2_MIN_NOTICE_H` away, so the platform has time to place it with someone else.

"Kept" means not cancelled by the patient. The probability is the cancellation share in the synthetic
month for the order's service category and lead-time band, pulled towards the overall share when a band
has few orders (`V2_CANCEL_PRIOR_WEIGHT` orders' worth of weight). A real build would fit it on past months
only; here it sees the whole month, which is fine for a demo of the mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from valeo_routing.datagen.reference import Service
from valeo_routing.settings import EngineSettings

from .commit import prefix_matches, with_idle_tail
from .data import OrderRow
from .model import Block, Job, Pair
from .planner import best_insertion, eligible
from .schedule import Context, Schedule, build_schedule


class CancelModel:
    """P(cancelled) for an order, by service category and lead-time band, smoothed towards the overall share."""

    def __init__(self, orders: Sequence[OrderRow], services: Dict[str, Service], bands_h: Sequence[float],
                 prior_weight: float):
        self.bands_h = list(bands_h)
        cancelled = sum(o.cancelled_at is not None for o in orders)
        self.overall = cancelled / len(orders) if orders else 0.0
        counts: Dict[Tuple[str, int], List[int]] = {}
        for o in orders:
            lead_h = (o.slot_start - o.published_at).total_seconds() / 3600.0
            c = counts.setdefault((services[o.service_id].category, self.band(lead_h)), [0, 0])
            c[0] += 1
            c[1] += o.cancelled_at is not None
        self.rates = {k: (n_cancel + prior_weight * self.overall) / (n + prior_weight) for k, (n, n_cancel) in counts.items()}

    def band(self, lead_h: float) -> int:
        return sum(lead_h >= b for b in self.bands_h)

    def p_cancel(self, job: Job) -> float:
        lead_h = (job.slot_min - job.published_min) / 60.0
        return self.rates.get((job.category, self.band(lead_h)), self.overall)


@dataclass(frozen=True)
class SwapRules:
    search_window_min: int
    min_notice_h: float
    visit_value_km: float
    min_gain_km: float

    @classmethod
    def from_settings(cls, s: EngineSettings) -> "SwapRules":
        return cls(s.v2_search_window_min, s.v2_min_notice_h, s.v2_visit_value_km, s.v2_swap_min_gain_km)


@dataclass(frozen=True)
class Room:
    """How to make room for `job`: it goes on `pair_id`; `other` is moved to `moved_to` or released."""

    kind: str  # move / swap
    pair_id: str
    sequence: Tuple[Job, ...]  # pair_id's new sequence of visits
    schedule: Schedule  # pair_id's new day
    other: Job
    moved_to: Optional[str] = None  # move only
    moved_schedule: Optional[Schedule] = None  # move only: moved_to's new day
    position: int = 0  # move only: where `other` sits in moved_to's sequence
    km_change: float = 0.0  # fleet km after, less before
    gain_km: float = 0.0  # swap only


def _keeps(pair: Pair, old: Sequence[Block], new: Sequence[Block], ctx: Context, now: int) -> bool:
    return prefix_matches(with_idle_tail(pair, old, ctx.office), with_idle_tail(pair, new, ctx.office), now)


def find_room(
    job: Job, pairs: Sequence[Pair], sequences: Dict[str, List[Job]], blocks: Dict[str, List[Block]],
    km: Dict[str, float], ctx: Context, now: int, rules: SwapRules, cancels: CancelModel,
) -> Optional[Room]:
    """The best move, else the best worthwhile swap, else None. Deterministic: ties go to lower ids."""
    best_move: Optional[Room] = None
    best_swap: Optional[Room] = None
    for pair in sorted(pairs, key=lambda p: p.pair_id):
        if not eligible(pair, job):
            continue
        pid = pair.pair_id
        for other in sorted(sequences[pid], key=lambda j: j.job_id):
            if abs(other.slot_min - job.slot_min) > rules.search_window_min:
                continue
            rest = [j for j in sequences[pid] if j.job_id != other.job_id]
            placed = _cheapest_on(pair, rest, job, blocks[pid], ctx, now)
            if placed is None:
                continue
            # Can `other` go to another pair (or back on this one, in a new place)?
            seqs = dict(sequences)
            seqs[pid] = placed[0]
            kms = dict(km)
            kms[pid] = placed[1].km
            blks = dict(blocks)
            blks[pid] = placed[1].blocks
            again = best_insertion(other, pairs, seqs, kms, ctx, now=now, blocks=blks)
            if again is not None:
                change = placed[1].km - km[pid] + again.added_km
                if best_move is None or change < best_move.km_change - 1e-9:
                    best_move = Room("move", pid, tuple(placed[0]), placed[1], other, again.pair_id, again.schedule, again.position, change)
                continue
            if best_move is not None or other.slot_min - now < rules.min_notice_h * 60:
                continue
            gain = (km[pid] - placed[1].km) + rules.visit_value_km * (cancels.p_cancel(other) - cancels.p_cancel(job))
            if gain >= rules.min_gain_km and (best_swap is None or gain > best_swap.gain_km + 1e-9):
                best_swap = Room("swap", pid, tuple(placed[0]), placed[1], other, km_change=placed[1].km - km[pid], gain_km=gain)
    return best_move or best_swap


def _cheapest_on(pair: Pair, rest: List[Job], job: Job, current: Sequence[Block], ctx: Context,
                 now: int) -> Optional[Tuple[List[Job], Schedule]]:
    """`job` added to `rest` on this pair at the cheapest feasible position that keeps what has started."""
    best: Optional[Tuple[List[Job], Schedule]] = None
    for position in range(len(rest) + 1):
        seq = rest[:position] + [job] + rest[position:]
        schedule = build_schedule(pair, seq, ctx)
        if not schedule.ok or not _keeps(pair, current, schedule.blocks, ctx, now):
            continue
        if best is None or schedule.km < best[1].km - 1e-9:
            best = (seq, schedule)
    return best
