#!/usr/bin/env python3
"""Migrate the old `funding_links` table to the new `funding_events` schema.

The old table stored (funder_id, facility_id, amount_usd, fiscal_year,
award_id, relation, source_url) with no primary key and no multi-year
award support. The new `funding_events` table carries the same columns
plus:

  * event_id  — deterministic hash so re-ingests are idempotent
  * amount_currency, period_start, period_end
  * award_title, program
  * source, retrieved_at, confidence, notes

Run from the repo root, idempotent::

    python scripts/migrate_funding_events.py
    python scripts/migrate_funding_events.py --catalog db/lto_catalog.sqlite

This script, as one lake snapshot:
  1. Ensures funding_events + cpi_index_us + helper views exist
     (lto_db.ensure_schema reads schema/schema.sql so the definitions
     stay in one place).
  2. If the *table* funding_links still exists, copies its rows into
     funding_events with computed event_ids, then drops the old table.
     The backwards-compat VIEW funding_links is created by schema.sql.
  3. Publishing is export_parquet.py's job (the only writer of
     public/parquet); --export-parquet now just says so.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def event_id(funder_id: str, facility_id: str, award_id: str | None,
             fiscal_year: int | None) -> str:
    key = "|".join([
        funder_id or "",
        facility_id or "",
        (award_id or "").strip(),
        str(fiscal_year) if fiscal_year is not None else "",
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = conn.execute(
        "SELECT table_type FROM information_schema.tables "
        "WHERE table_catalog=? AND table_schema='main' AND table_name=?",
        [lto_db.LAKE, name],
    ).fetchone()
    return bool(row) and row[0] == "BASE TABLE"


def view_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = conn.execute(
        "SELECT table_type FROM information_schema.tables "
        "WHERE table_catalog=? AND table_schema='main' AND table_name=?",
        [lto_db.LAKE, name],
    ).fetchone()
    return bool(row) and row[0] == "VIEW"


def apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the new tables if they don't exist and (re)create the views,
    all from schema/schema.sql. Never drops or retypes a pre-existing
    table — safe to run against a populated lake. schema.sql itself is
    never executed against the lake (its PRIMARY KEYs would fail)."""
    # The funding_links VIEW creation must happen AFTER the legacy
    # funding_links table is renamed/dropped (caller handles that).
    for change in lto_db.ensure_schema(conn):
        print(f"[schema] {change}")
    print("[schema] ensured funding_events + cpi_index_us + helper views")


def migrate_rows(conn: duckdb.DuckDBPyConnection) -> int:
    """Copy rows from the legacy funding_links table (if still a real
    table) into funding_events. Returns the number of rows inserted."""
    # After schema.sql runs, funding_links is now a VIEW. If the
    # original BASE TABLE is still around (first migration run), we
    # need to copy from a renamed backup. We handle that via a pre-step
    # in main(). Here we just trust that `_funding_links_legacy`
    # exists when there's work to do.
    if not table_exists(conn, "_funding_links_legacy"):
        return 0

    rows = conn.execute("""
        SELECT funder_id, facility_id, amount_usd, fiscal_year, award_id,
               relation, source_url
        FROM _funding_links_legacy
    """).fetchall()

    # Stage once, then one insert-only MERGE (the old ON CONFLICT DO
    # NOTHING): an event_id already in funding_events is left alone.
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE _stage_legacy_events (
            event_id VARCHAR, funder_id VARCHAR, facility_id VARCHAR,
            amount_usd DOUBLE, fiscal_year INTEGER, award_id VARCHAR,
            relation VARCHAR, source_url VARCHAR, source VARCHAR,
            confidence VARCHAR, _seq INTEGER)
    """)
    conn.executemany(
        "INSERT INTO _stage_legacy_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(event_id(funder_id, facility_id, award_id, fiscal_year),
          funder_id, facility_id, amount_usd, fiscal_year, award_id,
          relation, source_url, "legacy:funding_links", "medium", i)
         for i, (funder_id, facility_id, amount_usd, fiscal_year, award_id,
                 relation, source_url) in enumerate(rows)])
    if rows:
        stats = lto_db.merge_upsert(conn, "funding_events", ["event_id"],
                                    "_stage_legacy_events", insert_only=True,
                                    order_by="_seq")
        print(f"[migrate] merge: {stats}")
    conn.execute("DROP TABLE _stage_legacy_events")
    conn.execute("DROP TABLE _funding_links_legacy")
    return len(rows)


def _migrate(conn: duckdb.DuckDBPyConnection) -> int:
    """Steps 1-3; returns the number of legacy rows copied."""
    # Step 1: if funding_links is still a real table (old schema), rename
    # it out of the way so schema.sql's CREATE VIEW doesn't complain.
    if table_exists(conn, "funding_links"):
        conn.execute("ALTER TABLE funding_links RENAME TO _funding_links_legacy")
        print("[migrate] renamed funding_links -> _funding_links_legacy")

    # Step 2: apply schema (defines funding_events, cpi_index_us, views,
    # and the funding_links compatibility view). Skipped when all of it is
    # already there, so an already-migrated lake gets no empty snapshot.
    if (table_exists(conn, "_funding_links_legacy")
            or not view_exists(conn, "funding_links")
            or not table_exists(conn, "funding_events")
            or not table_exists(conn, "cpi_index_us")):
        apply_schema(conn)
    else:
        print("[schema] funding_events + cpi_index_us + funding_links view present")

    # Step 3: copy old rows -> new table.
    return migrate_rows(conn)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--export-parquet", action="store_true",
                    help="Deprecated: publishing is export_parquet.py's job; "
                         "this flag only prints that reminder.")
    args = ap.parse_args()

    try:
        conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    with lto_db.transaction(conn, "migrate_funding_events: funding_links -> "
                                  "funding_events + helper views"):
        n = _migrate(conn)
        lto_db.assert_integrity(conn, ["funding_events", "cpi_index_us"])
    if n:
        print(f"[migrate] copied {n} legacy rows into funding_events")
    else:
        print("[migrate] no legacy rows to copy (already migrated)")

    # Step 4: summary.
    stats = conn.execute("""
        SELECT COUNT(*)                                    AS total,
               COUNT(amount_usd)                           AS with_amount,
               COUNT(fiscal_year)                          AS with_fy,
               COUNT(DISTINCT facility_id)                 AS facilities_touched,
               COUNT(DISTINCT funder_id)                   AS funders_touched,
               MIN(fiscal_year), MAX(fiscal_year)
        FROM funding_events
    """).fetchone()
    print(f"[summary] funding_events rows={stats[0]}, with_amount={stats[1]}, "
          f"with_fiscal_year={stats[2]}, facilities={stats[3]}, "
          f"funders={stats[4]}, year range=[{stats[5]}..{stats[6]}]")

    if args.export_parquet:
        print("[parquet] --export-parquet is deprecated: run "
              "scripts/export_parquet.py (and export_view_caches.py) to publish")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
