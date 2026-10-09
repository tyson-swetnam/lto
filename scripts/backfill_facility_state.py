#!/usr/bin/env python3
"""Set facilities.state from the HQ point, by point-in-polygon.

`facilities` only ever carried `country` and a free-text `region`
("Southwest", "Domain 14 — Desert Southwest", "EPA Region 6"), so there
was no way to ask for "the New Mexico facilities". This derives a USPS
state / territory code for every facility that has coordinates and
writes the decision log to data/seed/facility_state.csv.

Run from the repo root (idempotent)::

    python scripts/backfill_facility_state.py
    python scripts/backfill_facility_state.py --dry-run
    python scripts/backfill_facility_state.py --nm-outline public/overlays/nm-boundary.geojson

Method, in order:
  1. `manual`   — a row in data/seed/facility_state.csv whose method is
                  `manual` always wins. Edit the CSV to correct a point
                  the polygons get wrong.
  2. `contains` — the HQ point is inside exactly one state polygon.
  3. `nearest`  — the point is in no polygon (offshore buoys, piers,
                  barrier islands lost to boundary generalisation) but
                  within NEAREST_KM of one. Distance is logged.
  4. unset      — everything else (Antarctica, open ocean). state = NULL.

Boundaries are the Census TIGERweb "States" layer, fetched once as
GeoJSON and cached under data/raw/census/_state/ (gitignored). They are
generalised to ~200 m, so a point that close to a state line can land on
the wrong side; that is what the manual override is for.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import duckdb
import requests
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "lto.duckdb"
CACHE = ROOT / "data" / "raw" / "census" / "_state" / "us_states.geojson"
LOG = ROOT / "data" / "seed" / "facility_state.csv"

STATES_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
    "State_County/MapServer/0/query"
)
STATES_PARAMS = {
    "where": "1=1",
    "outFields": "STUSAB,NAME,GEOID",
    "returnGeometry": "true",
    "outSR": "4326",
    "geometryPrecision": "4",
    "maxAllowableOffset": "0.002",
    "f": "geojson",
}
USER_AGENT = "lto-catalogue/0.2 (+https://github.com/tyson-swetnam/lto)"

# Offshore platforms and island stations sit well outside a generalised
# coastline; 150 km takes in the shelf moorings without reaching across
# to a different state's waters in the cases present in the catalogue.
NEAREST_KM = 150.0

LOG_FIELDS = ["facility_id", "canonical_name", "state", "method", "distance_km"]


def load_states() -> list[tuple[str, object]]:
    if not CACHE.exists():
        print(f"[fetch] {STATES_URL}")
        r = requests.get(STATES_URL, params=STATES_PARAMS,
                         headers={"User-Agent": USER_AGENT}, timeout=180)
        r.raise_for_status()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(r.text)
    fc = json.loads(CACHE.read_text())
    states = [(f["properties"]["STUSAB"], shape(f["geometry"])) for f in fc["features"]]
    if len(states) < 50:
        raise SystemExit(f"[error] only {len(states)} state polygons in {CACHE}; "
                         "delete the cache and re-run")
    return states


def km_between(lat: float, lng: float, geom) -> float:
    """Rough distance from a point to a polygon, in km.

    Scales longitude by cos(latitude) before measuring so the planar
    distance is meaningful at high latitudes (Alaska).
    """
    k = math.cos(math.radians(lat))
    from shapely.affinity import scale
    scaled = scale(geom, xfact=k, yfact=1.0, origin=(0, 0))
    return scaled.distance(Point(lng * k, lat)) * 111.2


def load_manual() -> dict[str, str]:
    if not LOG.exists():
        return {}
    with LOG.open(newline="") as fh:
        return {r["facility_id"]: (r["state"] or None)
                for r in csv.DictReader(fh) if r.get("method") == "manual"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="report the assignments without writing the DB or the log")
    ap.add_argument("--nm-outline", type=Path, default=None,
                    help="also write the New Mexico polygon to this GeoJSON path")
    args = ap.parse_args()

    states = load_states()
    codes = [c for c, _ in states]
    geoms = [g for _, g in states]
    tree = STRtree(geoms)
    manual = load_manual()

    if args.nm_outline:
        nm = geoms[codes.index("NM")]
        args.nm_outline.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "New Mexico", "state": "NM",
                               "source": "U.S. Census Bureau TIGERweb, States layer"},
                "geometry": mapping(nm),
            }],
        }))
        print(f"[ok] wrote {args.nm_outline}")

    conn = duckdb.connect(str(DB_PATH), read_only=args.dry_run)
    rows = conn.execute(
        "SELECT facility_id, canonical_name, hq_lat, hq_lng "
        "FROM facilities ORDER BY facility_id"
    ).fetchall()

    log: list[dict] = []
    for fid, name, lat, lng in rows:
        state, method, dist = None, "unset", ""
        if fid in manual:
            state, method = manual[fid], "manual"
        elif lat is not None and lng is not None:
            pt = Point(lng, lat)
            hits = [i for i in tree.query(pt) if geoms[i].contains(pt)]
            if hits:
                state, method = codes[hits[0]], "contains"
            else:
                i = int(tree.nearest(pt))
                km = km_between(lat, lng, geoms[i])
                if km <= NEAREST_KM:
                    state, method, dist = codes[i], "nearest", f"{km:.1f}"
        log.append({"facility_id": fid, "canonical_name": name,
                    "state": state or "", "method": method, "distance_km": dist})

    by_method: dict[str, int] = {}
    for r in log:
        by_method[r["method"]] = by_method.get(r["method"], 0) + 1
    print("[state] " + ", ".join(f"{k}={v}" for k, v in sorted(by_method.items())))
    for r in log:
        if r["method"] in ("nearest", "unset"):
            print(f"  {r['method']:<8} {r['state'] or '--':<3} "
                  f"{r['distance_km'] or '':>6}  {r['canonical_name']}")

    if args.dry_run:
        return 0

    conn.executemany(
        "UPDATE facilities SET state = ? WHERE facility_id = ?",
        [(r["state"] or None, r["facility_id"]) for r in log],
    )
    conn.close()
    with LOG.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(log)
    print(f"[ok] set state on {sum(1 for r in log if r['state'])} of {len(log)} "
          f"facilities; log → {LOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
