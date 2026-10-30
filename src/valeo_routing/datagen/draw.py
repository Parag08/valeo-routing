"""Weighted draws on a shared random.Random."""
from __future__ import annotations

import random
from typing import Dict, List, Sequence, TypeVar

T = TypeVar("T")


def pick(rng: random.Random, weights: Dict[str, float]) -> str:
    """Pick a key of `weights` with probability proportional to its value."""
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def pick_weighted(rng: random.Random, items: Sequence[T], weights: Sequence[float]) -> T:
    return rng.choices(list(items), weights=list(weights))[0]


def pick_many_without_replacement(rng: random.Random, weights: Dict[str, float], k: int) -> List[str]:
    """Draw `k` distinct keys, each draw proportional to the remaining weights."""
    remaining = dict(weights)
    chosen = []
    for _ in range(k):
        key = pick(rng, remaining)
        chosen.append(key)
        del remaining[key]
    return chosen


def count_for_day(rng: random.Random, mean: float, sd_factor: float) -> int:
    """Poisson-ish daily count: rounded gaussian with sd = factor * sqrt(mean)."""
    return max(0, int(round(rng.gauss(mean, sd_factor * mean ** 0.5))))
