"""Populate the `regions`, `region_area_links`, and `facility_regions`
tables from the canonical overlay GeoJSON files and the already-ingested
facilities.

Run as a standalone step (idempotent):

    python scripts/populate_regions.py                # use default db/cod_kmap.duckdb
    python scripts/populate_regions.py --db <path>

Or, automatically, at the end of `scripts/ingest.py`.

Design notes
------------

* Each polygon in public/overlays/*.geojson becomes one row in `regions`.
  Its `region_id` is a stable hash of (network_id, lower(name)) so re-runs
  are idempotent.

* `facility_regions` is derived: for every row in `facilities` with a
  non-null hq_lat/hq_lng, we do a point-in-polygon test against every
  region. A containment produces a (facility_id, region_id, 'within', 0.0)
  row. This makes "which facilities sit inside the Florida Keys NMS?" a
  plain SQL join.

* `region_area_links` is seeded from a small `KIND_AREAS` map — each
  region kind gets a set of plausible research areas that apply system-
  wide (e.g. every NMS sanctuary is tagged with "marine-ecosystems",
  "marine-policy-and-socio-economics"). You can refine per-region links by
  editing the rows in DuckDB directly.

Dependencies
------------
  * shapely   (pip install shapely)   — for efficient PIP.
  * duckdb    (already a project dep).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import duckdb
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
OVERLAYS = ROOT / 'public' / 'overlays'
DEFAULT_DB = ROOT / 'db' / 'cod_kmap.duckdb'


# ── Region kind -> seed research-area slugs ─────────────────────────
# Conservative defaults: anything that applies system-wide to every
# feature of this kind. Per-region edits should happen directly in the
# region_area_links table. Area slugs must exist in research_areas.

KIND_AREAS = {
    'sanctuary': [
        'marine-ecosystems',
        'marine-policy-and-socio-economics',
        'fisheries-and-aquaculture',
    ],
    'monument': [
        'marine-ecosystems',
        'deep-sea',
        'marine-policy-and-socio-economics',
    ],
    'nerr-reserve': [
        'estuaries-and-wetlands',
        'salt-marshes',
        'tidal-wetlands',
        'long-term-ecological-research',
    ],
    'nep-program': [
        'estuaries-and-wetlands',
        'marine-policy-and-socio-economics',
        'coastal-processes',
    ],
    'nps-unit': [
        'coastal-terrestrial-ecosystems',
        'coastal-processes',
    ],
    'neon-domain': [
        'long-term-ecological-research',
        'coastal-terrestrial-ecosystems',
    ],
    'epa-region': [
        'marine-policy-and-socio-economics',
    ],
}


# ── Helpers ─────────────────────────────────────────────────────────

def region_id(network_id: str, name: str) -> str:
    key = f'{network_id or ""}|{(name or "").strip().lower()}'
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]


def overlay_files() -> list[Path]:
    return sorted(p for p in OVERLAYS.glob('*.geojson'))


def load_region_rows(files: list[Path]) -> list[dict]:
    """One dict per polygon, ready for INSERT into `regions`. Plus a
    `geometry` key (shapely object) for PIP, stripped before insert."""
    rows: list[dict] = []
    for p in files:
        with p.open() as f:
            j = json.load(f)
        for feat in j.get('features', []):
            props = feat.get('properties') or {}
            name = props.get('name')
            if not name:
                continue
            network_slug = props.get('network_slug')
            rid = region_id(network_slug, name)
            try:
                geom = shape(feat['geometry'])
            except Exception as e:
                print(f'[warn] {p.name}: skipping bad geometry for {name!r}: {e}', file=sys.stderr)
                continue

            rows.append({
                'region_id':   rid,
                'name':        name,
                'acronym':     props.get('acronym'),
                'kind':        props.get('kind'),
                'network_id':  network_slug,
                'url':         props.get('url'),
                'manager':     props.get('manager'),
                'designated':  props.get('year_designated') or (
                    int(props['year']) if str(props.get('year') or '').isdigit() else None
                ),
                'state':       props.get('state') or props.get('states'),
                'description': props.get('description'),
                'source_file': p.name,
                'source':      props.get('source'),
                'geometry':    geom,
            })
    return rows


def insert_regions(conn: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    conn.execute('DELETE FROM main.regions')
    for r in rows:
        conn.execute(
            """INSERT INTO main.regions
               (region_id, name, acronym, kind, network_id, url, manager,
                designated, state, description, source_file, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                r['region_id'], r['name'], r['acronym'], r['kind'],
                r['network_id'], r['url'], r['manager'],
                r['designated'], r['state'], r['description'],
                r['source_file'], r['source'],
            ],
        )


def insert_region_area_links(conn: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    conn.execute('DELETE FROM main.region_area_links')
    valid_areas = {
        a for (a,) in conn.execute('SELECT area_id FROM main.research_areas').fetchall()
    }
    for r in rows:
        for area_id in KIND_AREAS.get(r['kind'] or '', []):
            if area_id not in valid_areas:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO main.region_area_links VALUES (?, ?)",
                [r['region_id'], area_id],
            )


def insert_facility_regions(conn: duckdb.DuckDBPyConnection, rows: list[dict]) -> int:
    """Point-in-polygon every facility against every region. Uses
    shapely's STRtree to keep the inner loop O(log n)."""
    conn.execute('DELETE FROM main.facility_regions')

    geoms = [r['geometry'] for r in rows]
    ids   = [r['region_id'] for r in rows]
    if not geoms:
        return 0

    tree = STRtree(geoms)

    facilities = conn.execute(
        """SELECT facility_id, hq_lat, hq_lng
           FROM main.facilities
           WHERE hq_lat IS NOT NULL AND hq_lng IS NOT NULL"""
    ).fetchall()

    n_links = 0
    for fid, lat, lng in facilities:
        pt = Point(lng, lat)
        for idx in tree.query(pt):
            # shapely >=2 returns numpy integer indices; earlier versions
            # returned geometry objects. Coerce to a Python int either way.
            try:
                geom_idx = int(idx)
            except (TypeError, ValueError):
                geom_idx = geoms.index(idx)
            if geoms[geom_idx].contains(pt):
                conn.execute(
                    "INSERT OR IGNORE INTO main.facility_regions "
                    "VALUES (?, ?, 'within', 0.0)",
                    [fid, ids[geom_idx]],
                )
                n_links += 1
    return n_links


# ── Main ────────────────────────────────────────────────────────────

def populate(db_path: Path) -> None:
    files = overlay_files()
    rows = load_region_rows(files)
    print(f'[info] loaded {len(rows)} region polygons from {len(files)} overlay files')

    with duckdb.connect(str(db_path)) as conn:
        # We need schema.sql to have been applied already. ingest.py does
        # that; if running standalone against an existing db, the tables
        # are present from the previous run.
        conn.execute('SET search_path = main;')
        insert_regions(conn, rows)
        insert_region_area_links(conn, rows)
        n_links = insert_facility_regions(conn, rows)
        print(f'[ok] regions: {len(rows)} rows')
        print(f'[ok] region_area_links: seeded from kind heuristics')
        print(f'[ok] facility_regions: {n_links} containment edges')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=str(DEFAULT_DB), help='path to DuckDB file')
    args = parser.parse_args()
    populate(Path(args.db))
    return 0


if __name__ == '__main__':
    sys.exit(main())
