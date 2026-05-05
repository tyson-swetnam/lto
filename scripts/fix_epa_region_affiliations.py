"""Backfill the 10 U.S. EPA Region facilities and link the EPA Regional
Administrators (currently orphan records in the ``people`` table) to
them via ``facility_personnel``.

Why this script exists
======================

``data/raw/R1/facilities_epa_regional_offices.json`` defines all 10 EPA
Region offices as facilities, and ``data/seed/facility_personnel_seed.csv``
defines the current Regional Administrator at each. However a previous
``scripts/ingest.py`` run dropped the EPA Region facility rows (root
cause unclear — possibly a re-run that touched only a subset of agent
JSON files), leaving the 10 administrator ``people`` rows without any
matching ``facility_personnel`` row.

The People view in ``src/views/people.js`` LEFT JOINs on ``facility_personnel``
and renders "No facility roles recorded." for any person without a row,
which is exactly what the user observed.

This script:

  1. Reads the canonical R1 EPA Regional Offices JSON to recover every
     facility's name, acronym, parent_org, country, region, hq address,
     hq lat/lng, url, contact, established, locations, networks, and
     facility_type.
  2. Computes the deterministic ``facility_id`` the same way
     ``scripts/ingest.py`` does (sha1(lower(name)|lower(acronym))[:16])
     so the IDs match what's already cached in
     ``public/facilities.geojson``.
  3. INSERT-OR-REPLACEs the 10 facility rows into ``main.facilities``
     and refreshes their ``main.locations`` HQ rows.
  4. Reads the EPA-R* rows from ``data/seed/facility_personnel_seed.csv``,
     resolves their person_id from ``main.people`` by the URL on
     homepage_url (which is set on every orphan), and writes the matching
     ``main.facility_personnel`` row.
  5. Re-exports ``public/parquet/facilities.parquet``,
     ``public/parquet/facility_personnel.parquet``,
     ``public/parquet/locations.parquet`` and rewrites
     ``public/facilities.geojson`` from ``v_facility_map`` so the static
     site now sees a consistent DB ↔ geojson state.

Idempotent — safe to re-run. Leaves the rest of the DB untouched.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "cod_kmap.duckdb"
EPA_JSON = ROOT / "data" / "raw" / "R1" / "facilities_epa_regional_offices.json"
SEED_CSV = ROOT / "data" / "seed" / "facility_personnel_seed.csv"
PARQUET_DB = ROOT / "db" / "parquet"
PARQUET_WEB = ROOT / "public" / "parquet"
GEOJSON_OUT = ROOT / "public" / "facilities.geojson"

PARQUET_TABLES_TO_REFRESH = ("facilities", "facility_personnel", "locations", "people")


def facility_id(name: str, acronym: str | None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def location_id(fid: str, label: str | None) -> str:
    return hashlib.sha1((fid + "|" + (label or "")).encode("utf-8")).hexdigest()[:16]


def load_epa_records() -> list[dict]:
    with EPA_JSON.open() as f:
        return json.load(f)


def upsert_facilities(conn: duckdb.DuckDBPyConnection, recs: list[dict]) -> list[str]:
    """Insert/refresh the 10 EPA Region facilities. Returns their IDs."""
    ids: list[str] = []
    for d in recs:
        fid = facility_id(d["canonical_name"], d.get("acronym"))
        ids.append(fid)
        hq = d.get("hq") or {}
        conn.execute(
            """INSERT OR REPLACE INTO main.facilities VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [
                fid,
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
        # locations
        for loc in (d.get("locations") or []):
            lid = location_id(fid, loc.get("label"))
            conn.execute(
                "INSERT OR REPLACE INTO main.locations VALUES (?,?,?,?,?,?,?)",
                [
                    lid,
                    fid,
                    loc.get("label"),
                    loc.get("address"),
                    loc.get("lat"),
                    loc.get("lng"),
                    loc.get("role"),
                ],
            )
    return ids


def link_administrators(conn: duckdb.DuckDBPyConnection) -> int:
    """Read EPA-R* rows from the seed CSV and create facility_personnel rows.

    Resolves each person by ``homepage_url`` exact match against people, which
    is the most reliable join key on these rows (orcid is sometimes missing).
    """
    # Build acronym → facility_id map
    acr_to_fid: dict[str, str] = {}
    for fid, acronym in conn.execute(
        "SELECT facility_id, acronym FROM main.facilities WHERE acronym LIKE 'EPA-R%'"
    ).fetchall():
        if acronym:
            acr_to_fid[acronym] = fid

    if len(acr_to_fid) != 10:
        print(
            f"[warn] expected 10 EPA Region facilities, found {len(acr_to_fid)}: "
            f"{sorted(acr_to_fid)}",
            file=sys.stderr,
        )

    n_linked = 0
    with SEED_CSV.open() as f:
        for row in csv.DictReader(filter(lambda l: not l.startswith("#"), f)):
            acr = (row.get("facility_acronym") or "").strip()
            if not acr.startswith("EPA-R"):
                continue
            fid = acr_to_fid.get(acr)
            if not fid:
                print(f"[skip] no facility for {acr}", file=sys.stderr)
                continue
            # find person by homepage_url match
            url = (row.get("homepage_url") or "").strip()
            if not url:
                print(f"[skip] {row.get('person_name')!r} has no homepage_url", file=sys.stderr)
                continue
            person = conn.execute(
                "SELECT person_id FROM main.people WHERE homepage_url = ?",
                [url],
            ).fetchone()
            if not person:
                # fall back to name
                person = conn.execute(
                    "SELECT person_id FROM main.people WHERE name = ?",
                    [row.get("person_name", "").strip()],
                ).fetchone()
            if not person:
                print(f"[skip] could not find person for {row.get('person_name')!r}", file=sys.stderr)
                continue
            pid = person[0]
            role = (row.get("role") or "Regional Administrator").strip()
            title = (row.get("title") or "").strip() or None
            is_key = (row.get("is_key_personnel") or "").strip().lower() in ("true", "1", "yes")
            conn.execute(
                """INSERT OR REPLACE INTO main.facility_personnel
                   (person_id, facility_id, role, title, is_key_personnel,
                    start_date, end_date, source, source_url, retrieved_at,
                    confidence, notes)
                   VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, CURRENT_DATE, ?, ?)""",
                [
                    pid, fid, role, title, is_key,
                    (row.get("source") or "press-release"),
                    (row.get("source_url") or "").strip() or None,
                    (row.get("confidence") or "high"),
                    f"Backfilled by scripts/fix_epa_region_affiliations.py from "
                    f"data/seed/facility_personnel_seed.csv (acronym={acr}).",
                ],
            )
            n_linked += 1
            print(f"[ok] linked {row.get('person_name')} → {acr} ({pid} → {fid})")
    return n_linked


def export_parquet(conn: duckdb.DuckDBPyConnection) -> None:
    PARQUET_DB.mkdir(parents=True, exist_ok=True)
    PARQUET_WEB.mkdir(parents=True, exist_ok=True)
    for t in PARQUET_TABLES_TO_REFRESH:
        out = PARQUET_DB / f"{t}.parquet"
        conn.execute(f"COPY (SELECT * FROM main.{t}) TO '{out}' (FORMAT PARQUET)")
        shutil.copyfile(out, PARQUET_WEB / f"{t}.parquet")
    print(f"[ok] refreshed parquet: {', '.join(PARQUET_TABLES_TO_REFRESH)}")


def rebuild_facilities_geojson(conn: duckdb.DuckDBPyConnection) -> int:
    rows = conn.execute(
        """SELECT id, name, acronym, type, country, lat, lng, url, parent_org
           FROM v_facility_map"""
    ).fetchall()
    feats = []
    for fid, name, acronym, ftype, country, lat, lng, url, parent in rows:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": fid, "name": name, "acronym": acronym, "type": ftype,
                "country": country, "url": url, "parent_org": parent,
            },
        })
    GEOJSON_OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, indent=0)
    )
    return len(feats)


def main() -> int:
    print(f"[fix] DB: {DB_PATH}", file=sys.stderr)
    recs = load_epa_records()
    print(f"[fix] EPA Region records to upsert: {len(recs)}", file=sys.stderr)

    with duckdb.connect(str(DB_PATH)) as conn:
        ids = upsert_facilities(conn, recs)
        print(f"[fix] upserted {len(ids)} EPA Region facilities", file=sys.stderr)

        # Make sure parent EPA agency exists in funders so the parent-agency
        # link in the JSON has a place to land. (Not strictly required for
        # the affiliation fix but keeps provenance complete.)
        # — funders backfill omitted; the existing R9 funding flow tooling
        # owns funder hygiene.

        n = link_administrators(conn)
        print(f"[fix] linked {n} administrators via facility_personnel", file=sys.stderr)

        # Re-export parquet for the four tables that changed
        export_parquet(conn)

        # Rebuild facilities.geojson so the static site is consistent
        n_geo = rebuild_facilities_geojson(conn)
        print(f"[fix] rebuilt {GEOJSON_OUT} with {n_geo} features", file=sys.stderr)

        # Sanity: orphan-people count after fix
        orphan = conn.execute(
            """SELECT COUNT(*) FROM main.people p
               WHERE NOT EXISTS (SELECT 1 FROM main.facility_personnel fp
                                 WHERE fp.person_id = p.person_id)"""
        ).fetchone()[0]
        print(f"[fix] orphan people remaining: {orphan}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
