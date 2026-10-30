"""Small geodesy helpers: jitter around a centroid and great-circle distance."""
from __future__ import annotations

import math
import random
from typing import Tuple

# Physical constants, not tunable parameters.
EARTH_RADIUS_M = 6_371_000.0
METRES_PER_DEG_LAT = math.pi * EARTH_RADIUS_M / 180.0


def jitter(rng: random.Random, lat: float, lon: float, radius_m: float) -> Tuple[float, float]:
    """A point uniformly distributed in a disc of `radius_m` metres around (lat, lon)."""
    r = radius_m * math.sqrt(rng.random())
    theta = rng.random() * 2.0 * math.pi
    dlat = r * math.cos(theta) / METRES_PER_DEG_LAT
    dlon = r * math.sin(theta) / (METRES_PER_DEG_LAT * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
