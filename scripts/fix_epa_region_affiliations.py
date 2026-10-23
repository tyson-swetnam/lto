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
  3. Upserts (MERGE) the 10 facility rows into ``main.facilities``
     and refreshes their ``main.locations`` HQ rows.
  4. Reads the EPA-R* rows from ``data/seed/facility_personnel_seed.csv``,
     resolves their person_id from ``main.people`` by the URL on
     homepage_url (which is set on every orphan), and writes the matching
     ``main.facility_personnel`` row.
  5. Writes steps 3-4 as one lake snapshot. Publishing is no longer this
     script's job: run ``scripts/export_parquet.py`` (the only writer of
     ``public/parquet/`` and ``public/facilities.geojson``) and
     ``scripts/export_view_caches.py`` afterwards.

Idempotent — safe to re-run. Leaves the rest of the lake untouched.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EPA_JSON = ROOT / "data" / "raw" / "R1" / "facilities_epa_regional_offices.json"
SEED_CSV = ROOT / "data" / "seed" / "facility_personnel_seed.csv"


def facility_id(name: str, acronym: str | None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def location_id(fid: str, label: str | None) -> str:
    return hashlib.sha1((fid + "|" + (label or "")).encode("utf-8")).hexdigest()[:16]


def load_epa_records() -> list[dict]:
    with EPA_JSON.open() as f:
        return json.load(f)


def upsert_facilities(conn: duckdb.DuckDBPyConnection, recs: list[dict]) -> list[str]:
    """Insert/refresh the 10 EPA Region facilities. Returns their IDs.

    Rows are staged, then MERGEd on the primary key (the old INSERT OR
    REPLACE). Only the columns named here are overwritten; derived ones
    (state, ror, record_length_years, ...) survive a re-run.
    """
    conn.execute(
        """CREATE OR REPLACE TEMP TABLE _stage_epa_facilities (
               facility_id VARCHAR, canonical_name VARCHAR, acronym VARCHAR,
               parent_org VARCHAR, facility_type VARCHAR, country VARCHAR,
               region VARCHAR, hq_address VARCHAR, hq_lat DOUBLE,
               hq_lng DOUBLE, url VARCHAR, contact VARCHAR,
               established INTEGER, created_at TIMESTAMP, _seq INTEGER)""")
    conn.execute(
        """CREATE OR REPLACE TEMP TABLE _stage_epa_locations (
               location_id VARCHAR, facility_id VARCHAR, label VARCHAR,
               address VARCHAR, lat DOUBLE, lng DOUBLE, role VARCHAR,
               _seq INTEGER)""")
    ids: list[str] = []
    for d in recs:
        fid = facility_id(d["canonical_name"], d.get("acronym"))
        ids.append(fid)
        hq = d.get("hq") or {}
        conn.execute(
            """INSERT INTO _stage_epa_facilities VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
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
                len(ids),
            ],
        )
        # locations
        for loc in (d.get("locations") or []):
            lid = location_id(fid, loc.get("label"))
            conn.execute(
                "INSERT INTO _stage_epa_locations VALUES (?,?,?,?,?,?,?,"
                " (SELECT count(*) FROM _stage_epa_locations))",
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
    # Last write wins on a repeated key, as the per-row REPLACE did;
    # created_at is set only when the row is first inserted.
    print("[fix] facilities merge: " + str(lto_db.merge_upsert(
        conn, "facilities", ["facility_id"], "_stage_epa_facilities",
        update_cols=["canonical_name", "acronym", "parent_org",
                     "facility_type", "country", "region", "hq_address",
                     "hq_lat", "hq_lng", "url", "contact", "established"],
        order_by="_seq DESC")), file=sys.stderr)
    print("[fix] locations merge: " + str(lto_db.merge_upsert(
        conn, "locations", ["location_id"], "_stage_epa_locations",
        order_by="_seq DESC")), file=sys.stderr)
    conn.execute("DROP TABLE _stage_epa_facilities")
    conn.execute("DROP TABLE _stage_epa_locations")
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
            # One-row MERGE on (person_id, facility_id, role) — the old
            # INSERT OR REPLACE; at most 10 rows, so no staging needed.
            lto_db.merge_upsert(
                conn, "facility_personnel", ["person_id", "facility_id", "role"],
                """SELECT ? AS person_id, ? AS facility_id, ? AS role,
                          ? AS title, ? AS is_key_personnel,
                          NULL::DATE AS start_date, NULL::DATE AS end_date,
                          ? AS source, ? AS source_url,
                          CURRENT_DATE AS retrieved_at, ? AS confidence,
                          ? AS notes""",
                params=[
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    lto_db.add_argparse_catalog(ap)
    args = ap.parse_args()
    print(f"[fix] lake catalog: {lto_db.catalog_path(args.catalog)}", file=sys.stderr)
    recs = load_epa_records()
    print(f"[fix] EPA Region records to upsert: {len(recs)}", file=sys.stderr)

    with lto_db.connect(catalog=args.catalog, data=args.lake_data) as conn:
        with lto_db.transaction(conn, f"fix_epa_region_affiliations: {len(recs)} "
                                      f"EPA Region facilities + administrators"):
            ids = upsert_facilities(conn, recs)
            print(f"[fix] upserted {len(ids)} EPA Region facilities", file=sys.stderr)

            # Make sure parent EPA agency exists in funders so the parent-agency
            # link in the JSON has a place to land. (Not strictly required for
            # the affiliation fix but keeps provenance complete.)
            # — funders backfill omitted; the existing R9 funding flow tooling
            # owns funder hygiene.

            n = link_administrators(conn)
            print(f"[fix] linked {n} administrators via facility_personnel", file=sys.stderr)
            lto_db.assert_integrity(conn, ["facilities", "locations", "facility_personnel"])

        # parquet + facilities.geojson are export_parquet.py's to write.
        print("[fix] next: scripts/backfill_facility_state.py, then "
              "export_parquet.py and export_view_caches.py to publish",
              file=sys.stderr)

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
