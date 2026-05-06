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
    # LTO six-sphere extension tables.
    "spheres",
    "ecosystem_types",
    "life_zones",
    "facility_spheres",
    "facility_ecosystems",
    "facility_life_zones",
    # People tables (Wave F).
    "people",
    "facility_personnel",
    "publications",
    "authorship",
    "person_areas",
    "collaborations",
    # Wave J data-archive layer.
    "archive_types",
    "data_formats",
    "data_licenses",
    "access_modes",
    "data_archives",
    "facility_archives",
    "data_products",
    "api_endpoints",
    "cloud_buckets",
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

        # lightweight geojson — facility map points enriched with the
        # primary_sphere from facility_spheres so the LTO sphere-color
        # legend works without DuckDB-Wasm having to load every parquet.
        rows = conn.execute(
            """SELECT v.id, v.name, v.acronym, v.type, v.country, v.lat, v.lng,
                      v.url, v.parent_org, f.established,
                      f.record_length_years, f.long_term_threshold_met,
                      fs.sphere_slug AS primary_sphere
               FROM v_facility_map v
               JOIN facilities f ON f.facility_id = v.id
               LEFT JOIN facility_spheres fs
                 ON fs.facility_id = v.id AND fs.role = 'primary'"""
        ).fetchall()

    features = []
    for r in rows:
        fid, name, acronym, ftype, country, lat, lng, url, parent, established, rly, ltm, primary_sphere = r
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
                "established": established,
                "record_length_years": rly,
                "long_term_threshold_met": ltm,
                "primary_sphere": primary_sphere,
            },
        })

    GEOJSON_OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=0)
    )

    print(f"[ok] exported {len(TABLES)} parquet tables and {len(features)} features to GeoJSON")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
