"""Small geodesy helpers: jitter around a centroid, placing points on land, great-circle distance."""
from __future__ import annotations

import math
import random
from typing import Tuple

from valeo_routing.service_area import ServiceArea

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


def place_in_area(
    rng: random.Random, area, service_area: ServiceArea, max_tries: int
) -> Tuple[float, float]:
    """A jittered point around the area's centroid that lies on land in the area's own emirate.

    Redraws until it does; raises if `max_tries` draws all miss, which means the area's centroid
    or jitter radius needs fixing in areas.csv.
    """
    for _ in range(max_tries):
        lat, lon = jitter(rng, area.lat, area.lon, area.jitter_m)
        if service_area.emirate_at(lat, lon) == area.emirate:
            return lat, lon
    raise ValueError(
        "No point on land in {} within {} draws around {} ({})".format(
            area.emirate, max_tries, area.area_id, area.area_name
        )
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
