"""Export every cod_kmap table to Parquet for DuckDB-Wasm HTTP-range reads.

Produces:
  db/parquet/<table>.parquet
  public/<table>.parquet            (copy that the static site serves)
  public/facilities.geojson         (lightweight first-paint fallback)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "cod_kmap.duckdb"
OUT_DB = ROOT / "db" / "parquet"
OUT_WEB = ROOT / "public" / "parquet"
GEOJSON_OUT = ROOT / "public" / "facilities.geojson"

TABLES = [
    "facilities",
    "locations",
    "funders",
    "funding_links",
    "research_areas",
    "area_links",
    "networks",
    "network_membership",
    "facility_types",
    "provenance",
    # Region-side tables (regions = one row per overlay polygon,
    # region_area_links = region ↔ research_area many-to-many, and
    # facility_regions = which facilities sit inside which regions).
    "regions",
    "region_area_links",
    "facility_regions",
]


def main() -> int:
    OUT_DB.mkdir(parents=True, exist_ok=True)
    OUT_WEB.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(DB_PATH), read_only=True) as conn:
        conn.execute("SET search_path = main;")
        for t in TABLES:
            db_path = OUT_DB / f"{t}.parquet"
            conn.execute(f"COPY (SELECT * FROM {t}) TO '{db_path}' (FORMAT PARQUET)")
            shutil.copyfile(db_path, OUT_WEB / f"{t}.parquet")

        # lightweight geojson with just the facility_map view
        rows = conn.execute(
            """SELECT id, name, acronym, type, country, lat, lng, url, parent_org
               FROM v_facility_map"""
        ).fetchall()

    features = []
    for r in rows:
        fid, name, acronym, ftype, country, lat, lng, url, parent = r
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": fid,
                "name": name,
                "acronym": acronym,
                "type": ftype,
                "country": country,
                "url": url,
                "parent_org": parent,
            },
        })

    GEOJSON_OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=0)
    )

    print(f"[ok] exported {len(TABLES)} parquet tables and {len(features)} features to GeoJSON")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
