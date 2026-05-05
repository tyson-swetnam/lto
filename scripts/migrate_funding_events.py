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
    python scripts/migrate_funding_events.py --db db/cod_kmap.duckdb
    python scripts/migrate_funding_events.py --export-parquet

This script:
  1. Ensures funding_events + cpi_index_us + helper views exist
     (reads schema/schema.sql so the definitions stay in one place).
  2. If the *table* funding_links still exists, copies its rows into
     funding_events with computed event_ids, then drops the old table.
     The backwards-compat VIEW funding_links is created by schema.sql.
  3. Optionally re-exports the relevant parquet files under db/parquet/
     and public/parquet/ (so the web app picks up the new schema).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
SCHEMA_SQL = ROOT / "schema" / "schema.sql"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]


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
        "WHERE table_schema='main' AND table_name=?",
        [name],
    ).fetchone()
    return bool(row) and row[0] == "BASE TABLE"


def view_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = conn.execute(
        "SELECT table_type FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?",
        [name],
    ).fetchone()
    return bool(row) and row[0] == "VIEW"


# Inline DDL for the pieces this migration owns. We intentionally do
# NOT re-run schema/schema.sql against an existing DB: CREATE OR REPLACE
# TABLE would cascade-fail on facility_types (which everything else
# references), and we don't want to risk dropping good data.
NEW_TABLES_DDL = r"""
CREATE TABLE IF NOT EXISTS funding_events (
    event_id        VARCHAR PRIMARY KEY,
    funder_id       VARCHAR NOT NULL REFERENCES funders(funder_id),
    facility_id     VARCHAR NOT NULL REFERENCES facilities(facility_id),
    amount_usd      DOUBLE,
    amount_currency VARCHAR DEFAULT 'USD',
    fiscal_year     INTEGER,
    period_start    DATE,
    period_end      DATE,
    award_id        VARCHAR,
    award_title     VARCHAR,
    program         VARCHAR,
    relation        VARCHAR,
    source          VARCHAR,
    source_url      VARCHAR,
    retrieved_at    DATE,
    confidence      VARCHAR,
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cpi_index_us (
    year    INTEGER PRIMARY KEY,
    cpi_u   DOUBLE NOT NULL,
    source  VARCHAR DEFAULT 'BLS CPI-U'
);
"""

VIEWS_DDL = r"""
CREATE OR REPLACE VIEW funding_links AS
SELECT funder_id, facility_id, amount_usd, fiscal_year, award_id,
       relation, source_url
FROM   funding_events;

CREATE OR REPLACE VIEW v_facility_funding_by_year AS
SELECT  f.facility_id,
        f.canonical_name              AS facility,
        f.acronym,
        fe.fiscal_year,
        SUM(fe.amount_usd)            AS total_usd_nominal,
        COUNT(*)                      AS n_awards,
        list(DISTINCT fu.name)        AS funders
FROM facilities       f
JOIN funding_events   fe ON fe.facility_id = f.facility_id
JOIN funders          fu ON fu.funder_id   = fe.funder_id
WHERE fe.fiscal_year IS NOT NULL AND fe.amount_usd IS NOT NULL
GROUP BY f.facility_id, f.canonical_name, f.acronym, fe.fiscal_year;

CREATE OR REPLACE VIEW v_funder_funding_by_year AS
SELECT  fu.funder_id,
        fu.name                       AS funder,
        fu.type                       AS funder_type,
        fe.fiscal_year,
        SUM(fe.amount_usd)            AS total_usd_nominal,
        COUNT(*)                      AS n_awards,
        COUNT(DISTINCT fe.facility_id) AS n_facilities
FROM funders         fu
JOIN funding_events  fe ON fe.funder_id = fu.funder_id
WHERE fe.fiscal_year IS NOT NULL AND fe.amount_usd IS NOT NULL
GROUP BY fu.funder_id, fu.name, fu.type, fe.fiscal_year;

CREATE OR REPLACE VIEW v_funding_ledger AS
SELECT  fe.event_id, fe.fiscal_year, fe.period_start, fe.period_end,
        fu.name AS funder, fu.type AS funder_type,
        f.canonical_name AS facility, f.acronym AS facility_acronym,
        f.facility_type  AS facility_kind, f.country,
        fe.amount_usd    AS amount_usd_nominal, fe.amount_currency,
        fe.award_id, fe.award_title, fe.program, fe.relation,
        fe.source, fe.source_url, fe.retrieved_at, fe.confidence, fe.notes
FROM funding_events fe
JOIN funders    fu ON fu.funder_id  = fe.funder_id
JOIN facilities f  ON f.facility_id = fe.facility_id;

CREATE OR REPLACE VIEW v_facility_funding_by_year_real AS
SELECT v.*,
       CASE
         WHEN cpi_yr.cpi_u IS NOT NULL AND cpi_anchor.cpi_u IS NOT NULL
         THEN v.total_usd_nominal * (cpi_anchor.cpi_u / cpi_yr.cpi_u)
         ELSE NULL
       END AS total_usd_real_2024
FROM v_facility_funding_by_year v
LEFT JOIN cpi_index_us cpi_yr     ON cpi_yr.year     = v.fiscal_year
LEFT JOIN cpi_index_us cpi_anchor ON cpi_anchor.year = 2024;
"""


def apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the new tables if they don't exist and (re)create the views.
    Does not touch any pre-existing table — safe to run against a
    populated database."""
    conn.execute(NEW_TABLES_DDL)
    # The funding_links VIEW creation must happen AFTER the legacy
    # funding_links table is renamed/dropped (caller handles that).
    conn.execute(VIEWS_DDL)
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

    n = 0
    for (funder_id, facility_id, amount_usd, fiscal_year, award_id,
         relation, source_url) in rows:
        eid = event_id(funder_id, facility_id, award_id, fiscal_year)
        conn.execute("""
            INSERT INTO funding_events (
                event_id, funder_id, facility_id, amount_usd, fiscal_year,
                award_id, relation, source_url, source, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (event_id) DO NOTHING
        """, [eid, funder_id, facility_id, amount_usd, fiscal_year,
              award_id, relation, source_url,
              "legacy:funding_links", "medium"])
        n += 1
    conn.execute("DROP TABLE _funding_links_legacy")
    return n


def export_parquet(conn: duckdb.DuckDBPyConnection) -> None:
    """Re-export the tables the web app loads. We also re-export
    `funding_links` (which is now a view) as a parquet so the existing
    db.js keeps working without a schema refactor on the client."""
    for base in PARQUET_OUT:
        base.mkdir(parents=True, exist_ok=True)
        for table in ("funding_events", "funders", "facilities"):
            out = base / f"{table}.parquet"
            conn.execute(f"COPY {table} TO '{out}' (FORMAT PARQUET)")
            print(f"[parquet] wrote {out}")
        # funding_links is a VIEW; COPY works on both tables and views.
        out = base / "funding_links.parquet"
        conn.execute(f"COPY funding_links TO '{out}' (FORMAT PARQUET)")
        print(f"[parquet] wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB,
                    help="Path to cod_kmap.duckdb (default: db/cod_kmap.duckdb)")
    ap.add_argument("--export-parquet", action="store_true",
                    help="Re-export the funding_events/funders/facilities/"
                         "funding_links parquet files under db/parquet/ "
                         "and public/parquet/ after migration.")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] database not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))

    # Step 1: if funding_links is still a real table (old schema), rename
    # it out of the way so schema.sql's CREATE VIEW doesn't complain.
    if table_exists(conn, "funding_links"):
        conn.execute("ALTER TABLE funding_links RENAME TO _funding_links_legacy")
        print("[migrate] renamed funding_links -> _funding_links_legacy")

    # Step 2: apply schema (defines funding_events, cpi_index_us, views,
    # and the funding_links compatibility view).
    apply_schema(conn)

    # Step 3: copy old rows -> new table.
    n = migrate_rows(conn)
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
        export_parquet(conn)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
