#!/usr/bin/env python3
"""Create / refresh the people-side tables + views in the DuckLake.

Run this once (idempotent) before any of the enrichment scripts. It
makes sure the lake has:

  * people                — person master record
  * facility_personnel    — who holds which role at which facility, when
  * publications          — paper records (from OpenAlex / Scopus / WoS)
  * authorship            — many-to-many: person wrote publication
  * person_areas          — person ↔ research_area (topic weighting)
  * publication_topics    — per-publication OpenAlex topics / concepts
  * collaborations        — pairwise co-authorship counts
  * v_facility_key_personnel  — current Directors / Chief Scientists view
  * v_person_enriched     — person rollup for the web app's people tab
  * v_person_areas_enriched

This script used to inline its own copy of that DDL, because re-running
schema/schema.sql in full would have dropped the populated tables. On the
lake schema.sql is never executed (DuckLake rejects its PRIMARY / FOREIGN
KEY clauses); lto_db.ensure_schema() reads it instead and adds whatever
tables and columns the lake is missing — e.g. people.bio_source_url or
facility_personnel.is_current — and re-creates the views, without
dropping or retyping anything. schema.sql is therefore the one definition.
(That covers the old person_areas.evidence_count migration too.)

Usage::

    python scripts/init_people_tables.py
    python scripts/init_people_tables.py --catalog /tmp/scratch/cat.sqlite

``--export-parquet`` is kept as a no-op: export_parquet.py is the only
writer of public/parquet.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def apply(conn) -> list[str]:
    """Bring the lake up to schema.sql. Run inside lto_db.transaction()."""
    changes = lto_db.ensure_schema(conn)
    for c in changes:
        print(f"[people] {c}")
    print("[people] tables + views applied")
    return changes


def catalog_arg(args) -> Path | None:
    """--db is the pre-lake flag, kept as an alias of --catalog. The retired
    db/lto.duckdb file itself is not a catalog, so it is ignored."""
    if args.db is None or args.catalog is not None:
        return args.catalog
    if args.db.suffix == ".duckdb":
        print(f"[deprecated] --db {args.db} ignored (db/lto.duckdb is retired); "
              f"use --catalog", file=sys.stderr)
        return None
    return args.db


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", type=Path, default=None,
                    help="deprecated alias of --catalog (a db/lto.duckdb path is ignored)")
    ap.add_argument("--export-parquet", action="store_true",
                    help="deprecated no-op: run scripts/export_parquet.py to publish")
    args = ap.parse_args()
    try:
        conn = lto_db.connect(catalog=catalog_arg(args), data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    with lto_db.transaction(conn, "init_people_tables: bring people tables + views "
                                  "up to schema.sql"):
        apply(conn)

    stats = conn.execute("""
        SELECT (SELECT COUNT(*) FROM people)             AS n_people,
               (SELECT COUNT(*) FROM facility_personnel) AS n_personnel,
               (SELECT COUNT(*) FROM publications)       AS n_pubs,
               (SELECT COUNT(*) FROM authorship)         AS n_authorship,
               (SELECT COUNT(*) FROM collaborations)     AS n_collabs
    """).fetchall()[0]
    print(f"[summary] people={stats[0]}  facility_personnel={stats[1]}  "
          f"publications={stats[2]}  authorship={stats[3]}  "
          f"collaborations={stats[4]}")

    if args.export_parquet:
        print("[parquet] --export-parquet is a no-op now: run scripts/export_parquet.py "
              "(the only writer of public/parquet)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
