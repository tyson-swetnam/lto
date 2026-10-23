#!/usr/bin/env python3
"""Targeted ingest of the four R11 coastal-terrestrial facility JSON
files into the LTO lake (scripts/lto_db.py). Mirrors what
scripts/ingest.py does for the R1..R10 agent JSON, but skips the schema
rebuild + dedup steps because we know R11 records are non-conflicting
(they passed ``crossvalidate.py`` with status=`new`).

Pipeline (one lake snapshot, commit message ``ingest_r11: …``):

  1. Add any missing ``facility_types``, ``research_areas``, and
     ``networks`` vocab rows from schema/vocab/*.csv so the new slugs we
     added for R11 (``protected-area-federal``,
     ``coastal-terrestrial-ecosystems``, ``nwrs``, etc.) exist.
  2. Read every R11/facilities_*.json, hash a deterministic facility_id,
     and insert the facilities and locations that are not there yet.
  3. Insert the missing area/network links (network slugs that are not
     in ``networks`` are dropped, as before).
  4. Refresh provenance rows so each new facility records where it came
     from.
  5. Check integrity (schema.sql keys + FKs) before committing.

This script no longer writes parquet or ``public/facilities.geojson``;
publish with the usual sequence afterwards::

    python scripts/backfill_facility_state.py
    python scripts/qa.py
    python scripts/export_parquet.py
    python scripts/export_view_caches.py

Point it at a scratch lake with ``$LTO_LAKE_CATALOG`` or ``--catalog``.
Idempotent — reruns produce identical state (each rerun is still one
snapshot, because the R11 provenance rows are always rewritten). Safe
to run alongside
scripts/fix_epa_region_affiliations.py (no overlap).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lto_db  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "R11_coastal_ecosystems"
VOCAB_DIR = ROOT / "schema" / "vocab"

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


def fid(name: str, acronym: str | None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def lid(facility_id: str, label: str | None) -> str:
    return hashlib.sha1((facility_id + "|" + (label or "")).encode("utf-8")).hexdigest()[:16]


def refresh_vocab(conn) -> None:
    # Insert-only: new vocab slugs are added, existing rows stay as they
    # are (the old INSERT OR IGNORE).
    lto_db.merge_upsert(
        conn, "facility_types", ["slug"],
        "SELECT slug, label, description FROM read_csv_auto(?, header=True)",
        params=[str(VOCAB_DIR / "facility_types.csv")], insert_only=True)
    lto_db.merge_upsert(
        conn, "research_areas", ["area_id"],
        """SELECT slug AS area_id, label, gcmd_uri, parent_slug AS parent_id
           FROM read_csv_auto(?, header=True)""",
        params=[str(VOCAB_DIR / "research_areas.csv")], insert_only=True)
    lto_db.merge_upsert(
        conn, "networks", ["network_id"],
        """SELECT slug AS network_id, label, level, url
           FROM read_csv_auto(?, header=True)""",
        params=[str(VOCAB_DIR / "networks.csv")], insert_only=True)
    n_ft = lto_db.scalar(conn, "SELECT COUNT(*) FROM facility_types")
    n_ra = lto_db.scalar(conn, "SELECT COUNT(*) FROM research_areas")
    n_nw = lto_db.scalar(conn, "SELECT COUNT(*) FROM networks")
    print(f"[r11] vocab now: facility_types={n_ft}  research_areas={n_ra}  networks={n_nw}",
          file=sys.stderr)


STAGE_DDL = {
    "facilities": """facility_id VARCHAR, canonical_name VARCHAR, acronym VARCHAR,
                     parent_org VARCHAR, facility_type VARCHAR, country VARCHAR,
                     region VARCHAR, hq_address VARCHAR, hq_lat DOUBLE,
                     hq_lng DOUBLE, url VARCHAR, contact VARCHAR,
                     established INTEGER""",
    "locations": """location_id VARCHAR, facility_id VARCHAR, label VARCHAR,
                    address VARCHAR, lat DOUBLE, lng DOUBLE, role VARCHAR""",
    "area_links": "facility_id VARCHAR, area_id VARCHAR",
    "network_membership": "facility_id VARCHAR, network_id VARCHAR, role VARCHAR",
    "provenance": """record_type VARCHAR, record_id VARCHAR, source_url VARCHAR,
                     retrieved_at DATE, confidence VARCHAR, agent VARCHAR""",
}


def insert_records(conn) -> int:
    n = 0
    today = time.strftime("%Y-%m-%d")
    staged: dict[str, list[tuple]] = {t: [] for t in STAGE_DDL}
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
            # Insert-only: R11 facilities are confirmed new by
            # crossvalidate.py, so this adds them the first time and is a
            # no-op on re-runs. (The lake could update them now — the old
            # FK block on UPDATE is gone — but a re-run must not revert
            # later curation such as url_hygiene or state backfills.)
            staged["facilities"].append((
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
            ))
            for loc in d.get("locations") or []:
                staged["locations"].append((
                    lid(this, loc.get("label")), this,
                    loc.get("label"), loc.get("address"),
                    loc.get("lat"), loc.get("lng"), loc.get("role"),
                ))
            for area_slug in d.get("research_areas") or []:
                staged["area_links"].append((this, area_slug))
            for net_label in d.get("networks") or []:
                # Network slugs in our R11 facility records use the
                # human-readable form (e.g. NWRS); the network table is
                # keyed by lowercase slug. Normalise.
                slug = net_label.lower().replace(" ", "-")
                staged["network_membership"].append((this, slug, "member"))
            prov = d.get("provenance") or {}
            staged["provenance"].append((
                "facility", this,
                prov.get("source_url"),
                prov.get("retrieved_at", today),
                prov.get("confidence", "high"),
                prov.get("agent", "R11"),
            ))
            n += 1
        print(f"[r11] read {len(recs)} records from {fn}", file=sys.stderr)

    for t, ddl in STAGE_DDL.items():
        # _seq keeps file order, so the first record of a repeated key
        # wins (as INSERT OR IGNORE did) and the last provenance wins.
        conn.execute(f"CREATE OR REPLACE TEMP TABLE _r11_{t} ({ddl}, _seq INTEGER)")
        if staged[t]:
            ph = ", ".join(["?"] * (len(staged[t][0]) + 1))
            conn.executemany(f"INSERT INTO _r11_{t} VALUES ({ph})",
                             [(*r, i) for i, r in enumerate(staged[t])])

    for t in ("facilities", "locations", "area_links"):
        st = lto_db.merge_upsert(conn, t, lto_db.primary_key(t), f"_r11_{t}",
                                 insert_only=True, order_by="_seq")
        print(f"[r11] {t}: {st}", file=sys.stderr)
    # Unknown network slugs are dropped silently to keep the FK happy.
    st = lto_db.merge_upsert(
        conn, "network_membership", ["facility_id", "network_id"],
        "SELECT * FROM _r11_network_membership "
        "WHERE network_id IN (SELECT network_id FROM networks)",
        insert_only=True, order_by="_seq")
    print(f"[r11] network_membership: {st}", file=sys.stderr)

    # provenance has no PK — DELETE existing R11 row(s) for these
    # facilities then re-INSERT (one row per facility, last record wins).
    conn.execute(
        "DELETE FROM provenance WHERE record_type='facility' AND agent='R11' "
        "AND record_id IN (SELECT record_id FROM _r11_provenance)")
    conn.execute(
        """INSERT INTO provenance BY NAME
           SELECT DISTINCT ON (record_id) * EXCLUDE (_seq)
           FROM _r11_provenance ORDER BY record_id, _seq DESC""")
    for t in STAGE_DDL:
        conn.execute(f"DROP TABLE _r11_{t}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lto_db.add_argparse_catalog(ap)
    args = ap.parse_args()
    print(f"[r11] lake: {lto_db.catalog_path(args.catalog)}", file=sys.stderr)
    with lto_db.connect(catalog=args.catalog, data=args.lake_data) as conn:
        with lto_db.transaction(conn, "ingest_r11: R11 coastal-terrestrial "
                                      "facilities + vocab, links, provenance"):
            refresh_vocab(conn)
            n = insert_records(conn)
            print(f"[r11] staged {n} facility records", file=sys.stderr)
            lto_db.assert_integrity(conn, [
                "facility_types", "research_areas", "networks", "facilities",
                "locations", "area_links", "network_membership", "provenance"])

        # final sanity counts
        n_fac = lto_db.scalar(conn, "SELECT COUNT(*) FROM facilities")
        n_loc = lto_db.scalar(conn, "SELECT COUNT(*) FROM locations")
        n_al = lto_db.scalar(conn, "SELECT COUNT(*) FROM area_links")
        n_nm = lto_db.scalar(conn, "SELECT COUNT(*) FROM network_membership")
        print(
            f"[r11] facilities={n_fac}  locations={n_loc}  "
            f"area_links={n_al}  network_membership={n_nm}",
            file=sys.stderr,
        )
    print("[r11] next: backfill_facility_state.py → qa.py → export_parquet.py "
          "→ export_view_caches.py", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
