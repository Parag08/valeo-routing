"""Which emirate (if any) a point falls in, on land, from data/reference/service_area.geojson.

Pure standard library so the generator and tests need no geometry package. The file itself is built
by tools/build_service_area.py from OpenStreetMap boundaries and coastline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

Ring = Sequence[Sequence[float]]


def _in_ring(lon: float, lat: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


class _Polygon:
    """One polygon (outer ring + holes) with a bounding box for a cheap first test."""

    def __init__(self, rings: List[Ring]):
        self.outer = rings[0]
        self.holes = rings[1:]
        lons = [p[0] for p in self.outer]
        lats = [p[1] for p in self.outer]
        self.bbox = (min(lons), min(lats), max(lons), max(lats))

    def contains(self, lon: float, lat: float) -> bool:
        west, south, east, north = self.bbox
        if not (west <= lon <= east and south <= lat <= north):
            return False
        return _in_ring(lon, lat, self.outer) and not any(_in_ring(lon, lat, h) for h in self.holes)


class ServiceArea:
    """Land inside the served emirates."""

    def __init__(self, path: Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._emirates: List[Tuple[str, List[_Polygon]]] = []
        for feature in data["features"]:
            geom = feature["geometry"]
            parts = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            self._emirates.append((feature["properties"]["emirate"], [_Polygon(p) for p in parts]))

    @property
    def emirates(self) -> List[str]:
        return [name for name, _ in self._emirates]

    def emirate_at(self, lat: float, lon: float) -> Optional[str]:
        """The served emirate this point is in, on land; None for sea or anywhere not served."""
        for name, polygons in self._emirates:
            if any(poly.contains(lon, lat) for poly in polygons):
                return name
        return None

    def contains(self, lat: float, lon: float) -> bool:
        return self.emirate_at(lat, lon) is not None
