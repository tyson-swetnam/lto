#!/usr/bin/env python3
"""Targeted ingest of the four R11 coastal-terrestrial facility JSON
files into ``db/cod_kmap.duckdb``. Mirrors what scripts/ingest.py does
for the R1..R10 agent JSON, but skips the schema rebuild + dedup steps
because we know R11 records are non-conflicting (they passed
``crossvalidate.py`` with status=`new`).

Pipeline:

  1. Refresh the ``facility_types``, ``research_areas``, and ``networks``
     vocab tables from schema/vocab/*.csv so the new slugs we added for
     R11 (``protected-area-federal``, ``coastal-terrestrial-ecosystems``,
     ``nwrs``, etc.) exist.
  2. Read every R11/facilities_*.json, hash a deterministic facility_id,
     INSERT-OR-REPLACE into ``facilities`` and ``locations``, and stage
     the network/area links.
  3. INSERT-OR-IGNORE the area/network links (FK-safe — schema enforces
     the slugs exist by step 1).
  4. Refresh provenance rows so each new facility records where it came
     from.
  5. Re-export ``facilities``, ``locations``, ``networks``,
     ``network_membership``, ``area_links``, ``research_areas``,
     ``facility_types``, ``provenance`` parquets into both
     ``db/parquet/`` and ``public/parquet/``.
  6. Rebuild ``public/facilities.geojson`` from the v_facility_map view.

Idempotent — reruns produce identical state. Safe to run alongside
scripts/fix_epa_region_affiliations.py (no overlap).
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent.parent
# DB path is overridable so we can run the ingest against a copy in a
# writable scratch directory when the original repo mount disallows
# deleting DuckDB's .wal sidecar (e.g. inside Cowork sandboxes).
import os as _os
DB_PATH = Path(_os.environ.get("COD_KMAP_DB", str(ROOT / "db" / "cod_kmap.duckdb")))
RAW_DIR = ROOT / "data" / "raw" / "R11_coastal_ecosystems"
VOCAB_DIR = ROOT / "schema" / "vocab"
OUT_DB = ROOT / "db" / "parquet"
OUT_WEB = ROOT / "public" / "parquet"
GEOJSON_OUT = ROOT / "public" / "facilities.geojson"

R11_FILES = [
    "facilities_fws_coastal.json",
    "facilities_nps_coastal.json",
    "facilities_usfs_special.json",
    "facilities_wilderness_coastal.json",
    # Phase-2: state agency parks/preserves + NGO/private holdings + Ramsar.
    "facilities_state_protected.json",
    "facilities_ngo_private.json",
    "facilities_ramsar.json",
    # Phase-3: NEON sites WERE ingested as facility points but were
    # superseded by the polygon overlay public/overlays/neon-sites.geojson
    # (sourced from NEON's Field_Sampling_Boundaries feature service).
    # The points duplicated the polygons on the map, so they were removed
    # by scripts/coastal_research/remove_neon_facility_points.py and the
    # seed JSON intentionally left out of this list.
]

PARQUET_TABLES = (
    "facilities", "locations", "networks", "network_membership",
    "area_links", "research_areas", "facility_types", "provenance",
)


def fid(name: str, acronym: str | None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def lid(facility_id: str, label: str | None) -> str:
    return hashlib.sha1((facility_id + "|" + (label or "")).encode("utf-8")).hexdigest()[:16]


def refresh_vocab(conn: duckdb.DuckDBPyConnection) -> None:
    # We can't DELETE+INSERT here because facilities have a foreign key
    # to facility_types — delete violates FK. Use INSERT-OR-IGNORE so
    # any new vocab slugs are added but existing rows remain.
    conn.execute(
        """INSERT OR IGNORE INTO main.facility_types
           SELECT * FROM read_csv_auto(?, header=True)""",
        [str(VOCAB_DIR / "facility_types.csv")],
    )
    conn.execute(
        """INSERT OR IGNORE INTO main.research_areas
           SELECT slug AS area_id, label, gcmd_uri, parent_slug AS parent_id
           FROM read_csv_auto(?, header=True)""",
        [str(VOCAB_DIR / "research_areas.csv")],
    )
    conn.execute(
        """INSERT OR IGNORE INTO main.networks
           SELECT slug AS network_id, label, level, url
           FROM read_csv_auto(?, header=True)""",
        [str(VOCAB_DIR / "networks.csv")],
    )
    n_ft = conn.execute("SELECT COUNT(*) FROM main.facility_types").fetchone()[0]
    n_ra = conn.execute("SELECT COUNT(*) FROM main.research_areas").fetchone()[0]
    n_nw = conn.execute("SELECT COUNT(*) FROM main.networks").fetchone()[0]
    print(f"[r11] vocab now: facility_types={n_ft}  research_areas={n_ra}  networks={n_nw}",
          file=sys.stderr)


def insert_records(conn: duckdb.DuckDBPyConnection) -> int:
    n = 0
    today = time.strftime("%Y-%m-%d")
    for fn in R11_FILES:
        path = RAW_DIR / fn
        if not path.exists():
            print(f"[r11] missing {path.relative_to(ROOT)}, skipping", file=sys.stderr)
            continue
        with path.open() as f:
            recs = json.load(f)
        for d in recs:
            this = fid(d["canonical_name"], d.get("acronym"))
            hq = d.get("hq") or {}
            # DuckDB enforces FKs on INSERT OR REPLACE (which deletes first),
            # so use INSERT OR IGNORE to add new rows and a separate UPDATE
            # to refresh metadata on existing rows. R11 facilities are
            # confirmed new by crossvalidate.py, so the IGNORE is a no-op
            # the first time and idempotent on re-runs.
            conn.execute(
                """INSERT OR IGNORE INTO main.facilities VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                [
                    this,
                    d.get("canonical_name"),
                    d.get("acronym"),
                    d.get("parent_org"),
                    d.get("facility_type"),
                    d.get("country"),
                    d.get("region"),
                    hq.get("address"),
                    hq.get("lat"),
                    hq.get("lng"),
                    d.get("url"),
                    d.get("contact"),
                    d.get("established"),
                ],
            )
            # Note: We deliberately do NOT UPDATE existing rows because
            # DuckDB's FK checker raises spurious constraint errors on
            # UPDATEs against parent rows that have child references
            # (locations, area_links, network_membership), even when the
            # PK column is unchanged. R11 facilities are confirmed-new
            # by crossvalidate.py, so the IGNORE is the right shape.
            for loc in d.get("locations") or []:
                lid_ = lid(this, loc.get("label"))
                conn.execute(
                    "INSERT OR IGNORE INTO main.locations VALUES (?,?,?,?,?,?,?)",
                    [
                        lid_, this,
                        loc.get("label"), loc.get("address"),
                        loc.get("lat"), loc.get("lng"), loc.get("role"),
                    ],
                )
            for area_slug in d.get("research_areas") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO main.area_links VALUES (?,?)",
                    [this, area_slug],
                )
            for net_label in d.get("networks") or []:
                # Network slugs in our R11 facility records use the
                # human-readable form (e.g. NWRS); the network table is
                # keyed by lowercase slug. Normalise.
                slug = net_label.lower().replace(" ", "-")
                # Verify the slug exists; INSERT IGNORE silently drops
                # non-existent ones to keep the FK happy.
                exists = conn.execute(
                    "SELECT 1 FROM main.networks WHERE network_id = ?", [slug]
                ).fetchone()
                if exists:
                    conn.execute(
                        "INSERT OR IGNORE INTO main.network_membership VALUES (?,?,?)",
                        [this, slug, "member"],
                    )
            # provenance has no PK — DELETE existing row(s) for this
            # facility's R11 source then re-INSERT. Column order:
            # (record_type, record_id, source_url, retrieved_at, confidence, agent)
            prov = d.get("provenance") or {}
            conn.execute(
                "DELETE FROM main.provenance WHERE record_type='facility' "
                "AND record_id=? AND agent='R11'",
                [this],
            )
            conn.execute(
                "INSERT INTO main.provenance VALUES ('facility', ?, ?, ?, ?, ?)",
                [
                    this,
                    prov.get("source_url"),
                    prov.get("retrieved_at", today),
                    prov.get("confidence", "high"),
                    prov.get("agent", "R11"),
                ],
            )
            n += 1
        print(f"[r11] ingested {len(recs)} records from {fn}", file=sys.stderr)
    return n


def export_parquet(conn: duckdb.DuckDBPyConnection) -> None:
    OUT_DB.mkdir(parents=True, exist_ok=True)
    OUT_WEB.mkdir(parents=True, exist_ok=True)
    for t in PARQUET_TABLES:
        out = OUT_DB / f"{t}.parquet"
        conn.execute(f"COPY (SELECT * FROM main.{t}) TO '{out}' (FORMAT PARQUET)")
        shutil.copyfile(out, OUT_WEB / f"{t}.parquet")
    print(f"[r11] refreshed parquet: {', '.join(PARQUET_TABLES)}", file=sys.stderr)


def rebuild_facilities_geojson(conn: duckdb.DuckDBPyConnection) -> int:
    rows = conn.execute(
        """SELECT id, name, acronym, type, country, lat, lng, url, parent_org
           FROM v_facility_map"""
    ).fetchall()
    feats = []
    for fid_, name, acr, ftype, country, lat, lng, url, parent in rows:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": fid_, "name": name, "acronym": acr, "type": ftype,
                "country": country, "url": url, "parent_org": parent,
            },
        })
    GEOJSON_OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, indent=0)
    )
    return len(feats)


def main() -> int:
    print(f"[r11] DB: {DB_PATH}", file=sys.stderr)
    with duckdb.connect(str(DB_PATH)) as conn:
        # Provenance table schema check — different schemas across DBs
        # define different column orders. Inspect first.
        try:
            cols = [r[0] for r in conn.execute(
                "PRAGMA table_info('provenance')"
            ).fetchall()]
            print(f"[r11] provenance columns: {cols}", file=sys.stderr)
        except Exception:
            pass

        refresh_vocab(conn)
        n = insert_records(conn)
        print(f"[r11] inserted/replaced {n} facility records", file=sys.stderr)
        export_parquet(conn)
        n_geo = rebuild_facilities_geojson(conn)
        print(f"[r11] rebuilt {GEOJSON_OUT.relative_to(ROOT)} with {n_geo} features",
              file=sys.stderr)

        # final sanity counts
        n_fac = conn.execute("SELECT COUNT(*) FROM main.facilities").fetchone()[0]
        n_loc = conn.execute("SELECT COUNT(*) FROM main.locations").fetchone()[0]
        n_al = conn.execute("SELECT COUNT(*) FROM main.area_links").fetchone()[0]
        n_nm = conn.execute("SELECT COUNT(*) FROM main.network_membership").fetchone()[0]
        print(
            f"[r11] facilities={n_fac}  locations={n_loc}  "
            f"area_links={n_al}  network_membership={n_nm}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
