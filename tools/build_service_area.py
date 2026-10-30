"""Build data/reference/service_area.geojson: the land inside the emirates the demo serves.

One-off tool, run by hand when the spec changes; the generator and tests only read its output.
Needs network access and shapely (`pip install shapely`). Downloads are cached in data/cache/.

    .venv/bin/python tools/build_service_area.py

Boundaries come from Nominatim and the coastline from Overpass, both OpenStreetMap (ODbL).
Land is found by polygonizing the coastline against the download box: every face is land unless
it contains one of the spec's sea seeds. The service area is each emirate's boundary intersected
with that land.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
from pathlib import Path

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "reference" / "service_area_spec.json"
OUT = ROOT / "data" / "reference" / "service_area.geojson"
CACHE = ROOT / "data" / "cache"
USER_AGENT = "valeo-routing-demo/0.1 (synthetic-data build tool)"


def fetch(url: str, cache_name: str, data: bytes = None) -> dict:
    """GET (or POST) a JSON document, cached on disk."""
    path = CACHE / cache_name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # curl, not urllib: macOS's system Python 3.9 ships an SSL library these servers reject.
    cmd = ["curl", "-sS", "--fail", "--max-time", "180", "-A", USER_AGENT, url]
    if data is not None:
        cmd[1:1] = ["--data-binary", "@-"]
    body = subprocess.run(cmd, input=data, capture_output=True, check=True).stdout.decode("utf-8")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    time.sleep(1.2)  # Nominatim's usage policy: at most one request a second
    return json.loads(body)


def emirate_boundary(name: str, relation_id: int):
    url = "https://nominatim.openstreetmap.org/lookup?" + urllib.parse.urlencode(
        {"osm_ids": "R{}".format(relation_id), "format": "json", "polygon_geojson": 1}
    )
    result = fetch(url, "boundary_R{}.json".format(relation_id))
    if not result:
        raise SystemExit("No boundary returned for {} (R{})".format(name, relation_id))
    return shape(result[0]["geojson"])


def land_polygon(bbox, sea_seeds):
    south, west, north, east = bbox
    query = '[out:json][timeout:120];way["natural"="coastline"]({},{},{},{});out geom;'.format(
        south, west, north, east
    )
    data = fetch(
        "https://overpass-api.de/api/interpreter",
        "coastline_{}_{}_{}_{}.json".format(south, west, north, east),
        data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
    )
    lines = [
        LineString([(p["lon"], p["lat"]) for p in way["geometry"]])
        for way in data["elements"]
        if len(way.get("geometry", [])) >= 2
    ]
    frame = box(west, south, east, north)
    noded = unary_union(lines + [frame.exterior])
    faces = [f for f in polygonize(noded) if f.within(frame.buffer(1e-9))]
    seeds = [Point(lon, lat) for lat, lon in sea_seeds]
    sea = [f for f in faces if any(f.contains(s) for s in seeds)]
    if len(sea) < len(seeds) and len({id(f) for f in sea}) == 0:
        raise SystemExit("No sea face found; check sea_seeds and the coastline box")
    land = [f for f in faces if not any(f.contains(s) for s in seeds)]
    # Islands are closed coastline rings inside a sea face; polygonize returns them as faces too,
    # and they hold no seed, so they count as land. Holes inside them are lagoons.
    return unary_union(land), len(faces), len(sea)


def polygons_only(geom):
    """Intersections can return stray lines and points along shared borders; keep the areas."""
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in polygons_only(g)]
    return []


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    land, n_faces, n_sea = land_polygon(spec["coastline_bbox"], spec["sea_seeds"])
    print("coastline faces: {} ({} sea)".format(n_faces, n_sea))

    features = []
    for name, relation_id in spec["emirates"].items():
        served = emirate_boundary(name, relation_id).intersection(land)
        served = served.simplify(spec["simplify_deg"], preserve_topology=True)
        served = MultiPolygon(polygons_only(served))
        features.append(
            {"type": "Feature", "properties": {"emirate": name, "osm_relation": relation_id},
             "geometry": mapping(served)}
        )
        print("{:16s} land area ~{:.0f} km2".format(name, served.area * 111.0 * 101.0))

    collection = {
        "type": "FeatureCollection",
        "properties": {"source": spec["_doc"]["source"], "built_by": "tools/build_service_area.py"},
        "features": features,
    }
    OUT.write_text(json.dumps(collection, separators=(",", ":")), encoding="utf-8")
    print("wrote {} ({:.0f} KB)".format(OUT.relative_to(ROOT), OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
