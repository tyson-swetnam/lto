#!/usr/bin/env python3
"""Create / refresh the people-side tables + views in cod_kmap.duckdb.

Run this once (idempotent) before any of the enrichment scripts. It
adds:

  * people                — person master record
  * facility_personnel    — who holds which role at which facility, when
  * publications          — paper records (from OpenAlex / Scopus / WoS)
  * authorship            — many-to-many: person wrote publication
  * person_areas          — person ↔ research_area (topic weighting)
  * collaborations        — pairwise co-authorship counts
  * v_facility_key_personnel  — current Directors / Chief Scientists view
  * v_person_enriched     — person rollup for the web app's people tab

We deliberately do NOT re-run schema/schema.sql in full because it uses
CREATE OR REPLACE TABLE for facilities/research_areas, which cascades
over dependents. Instead this script inlines just the new DDL so the
existing facilities / research_areas / etc. tables are untouched.

Usage::

    python scripts/init_people_tables.py
    python scripts/init_people_tables.py --db db/cod_kmap.duckdb
    python scripts/init_people_tables.py --export-parquet

The `--export-parquet` flag re-exports people/facility_personnel and
friends into db/parquet + public/parquet so the web app's DuckDB-Wasm
can read them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]

PEOPLE_TABLES_DDL = r"""
CREATE TABLE IF NOT EXISTS people (
    person_id           VARCHAR PRIMARY KEY,
    name                VARCHAR NOT NULL,
    name_family         VARCHAR,
    name_given          VARCHAR,
    email               VARCHAR,
    orcid               VARCHAR,
    openalex_id         VARCHAR,
    scopus_author_id    VARCHAR,
    wos_researcher_id   VARCHAR,
    google_scholar_id   VARCHAR,
    homepage_url        VARCHAR,
    photo_url           VARCHAR,
    research_interests  VARCHAR,
    bio                 VARCHAR,
    status              VARCHAR,
    notes               VARCHAR,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS facility_personnel (
    person_id           VARCHAR NOT NULL,
    facility_id         VARCHAR NOT NULL,
    role                VARCHAR NOT NULL,
    title               VARCHAR,
    is_key_personnel    BOOLEAN DEFAULT false,
    start_date          DATE,
    end_date            DATE,
    source              VARCHAR,
    source_url          VARCHAR,
    retrieved_at        DATE,
    confidence          VARCHAR,
    notes               VARCHAR,
    PRIMARY KEY (person_id, facility_id, role)
);

CREATE TABLE IF NOT EXISTS publications (
    publication_id      VARCHAR PRIMARY KEY,
    doi                 VARCHAR UNIQUE,
    title               VARCHAR,
    abstract            VARCHAR,
    pub_year            INTEGER,
    pub_type            VARCHAR,
    journal             VARCHAR,
    venue               VARCHAR,
    cited_by_count      INTEGER DEFAULT 0,
    openalex_id         VARCHAR,
    scopus_eid          VARCHAR,
    wos_uid             VARCHAR,
    url                 VARCHAR,
    source              VARCHAR,
    retrieved_at        DATE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS authorship (
    person_id           VARCHAR NOT NULL,
    publication_id      VARCHAR NOT NULL,
    author_position     INTEGER,
    is_corresponding    BOOLEAN DEFAULT false,
    raw_name            VARCHAR,
    PRIMARY KEY (person_id, publication_id)
);

CREATE TABLE IF NOT EXISTS person_areas (
    person_id           VARCHAR NOT NULL,
    area_id             VARCHAR NOT NULL,
    weight              DOUBLE DEFAULT 1.0,
    evidence_count      INTEGER DEFAULT 0,
    source              VARCHAR,
    PRIMARY KEY (person_id, area_id)
);

-- Per-publication OpenAlex topics / concepts / keywords. See
-- schema/schema.sql for the design rationale; in short, we store
-- all three OpenAlex ontologies so the crosswalk can match against
-- whichever best identifies a research area.
CREATE TABLE IF NOT EXISTS publication_topics (
    publication_id      VARCHAR NOT NULL,
    concept_id          VARCHAR NOT NULL,
    concept_name        VARCHAR NOT NULL,
    score               DOUBLE,
    level               INTEGER,
    kind                VARCHAR DEFAULT 'concept',
    source              VARCHAR DEFAULT 'openalex',
    PRIMARY KEY (publication_id, concept_id)
);

CREATE TABLE IF NOT EXISTS collaborations (
    person_a_id         VARCHAR NOT NULL,
    person_b_id         VARCHAR NOT NULL,
    co_pub_count        INTEGER DEFAULT 0,
    first_year          INTEGER,
    last_year           INTEGER,
    strength            DOUBLE DEFAULT 0.0,
    PRIMARY KEY (person_a_id, person_b_id)
);
"""

# Migration: older databases were created before evidence_count was
# added to person_areas. ALTER TABLE is idempotent here (DuckDB ≥0.10
# accepts IF NOT EXISTS on ADD COLUMN).
PERSON_AREAS_MIGRATION = """
ALTER TABLE person_areas ADD COLUMN IF NOT EXISTS evidence_count INTEGER DEFAULT 0;
"""

PEOPLE_VIEWS_DDL = r"""
CREATE OR REPLACE VIEW v_person_areas_enriched AS
SELECT
    p.person_id,
    p.name                       AS person,
    ra.area_id,
    ra.label                     AS area,
    pa.weight,
    pa.evidence_count,
    pa.source
FROM person_areas pa
JOIN people         p  ON p.person_id  = pa.person_id
JOIN research_areas ra ON ra.area_id   = pa.area_id;

CREATE OR REPLACE VIEW v_facility_key_personnel AS
SELECT
    f.facility_id,
    f.canonical_name         AS facility,
    f.acronym                AS facility_acronym,
    p.person_id,
    p.name,
    fp.role,
    fp.title,
    p.orcid,
    p.openalex_id,
    p.email,
    p.homepage_url,
    fp.start_date,
    fp.source_url
FROM facility_personnel fp
JOIN people     p ON p.person_id   = fp.person_id
JOIN facilities f ON f.facility_id = fp.facility_id
WHERE fp.is_key_personnel = true
  AND (fp.end_date IS NULL OR fp.end_date > CURRENT_DATE);

CREATE OR REPLACE VIEW v_person_enriched AS
SELECT
    p.person_id,
    p.name,
    p.name_family,
    p.orcid,
    p.openalex_id,
    p.email,
    p.homepage_url,
    p.research_interests,
    p.status,
    list(DISTINCT f.canonical_name)  AS facilities,
    list(DISTINCT fp.role)           AS roles,
    list(DISTINCT ra.label)          AS research_areas,
    COUNT(DISTINCT a.publication_id) AS n_publications,
    MAX(pub.pub_year)                AS latest_pub_year
FROM people p
LEFT JOIN facility_personnel fp ON fp.person_id   = p.person_id
LEFT JOIN facilities         f  ON f.facility_id  = fp.facility_id
LEFT JOIN person_areas       pa ON pa.person_id   = p.person_id
LEFT JOIN research_areas     ra ON ra.area_id     = pa.area_id
LEFT JOIN authorship         a  ON a.person_id    = p.person_id
LEFT JOIN publications       pub ON pub.publication_id = a.publication_id
GROUP BY p.person_id, p.name, p.name_family, p.orcid, p.openalex_id,
         p.email, p.homepage_url, p.research_interests, p.status;
"""


def apply(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(PEOPLE_TABLES_DDL)
    # Migration: older DBs created before evidence_count was added.
    # ALTER TABLE ADD COLUMN IF NOT EXISTS is a no-op on fresh DBs.
    try:
        conn.execute(PERSON_AREAS_MIGRATION)
    except Exception as e:
        # Some older DuckDB versions don't accept IF NOT EXISTS on
        # ADD COLUMN; fall back to a probe-then-add pattern.
        try:
            cols = [r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'person_areas'"
            ).fetchall()]
            if "evidence_count" not in cols:
                conn.execute(
                    "ALTER TABLE person_areas "
                    "ADD COLUMN evidence_count INTEGER DEFAULT 0"
                )
        except Exception as e2:
            print(f"[warn] person_areas migration: {e2}")
    conn.execute(PEOPLE_VIEWS_DDL)
    print("[people] tables + views applied")


def export_parquet(conn: duckdb.DuckDBPyConnection) -> None:
    tables = ["people", "facility_personnel", "publications",
              "authorship", "person_areas", "publication_topics",
              "collaborations"]
    for base in PARQUET_OUT:
        base.mkdir(parents=True, exist_ok=True)
        for t in tables:
            out = base / f"{t}.parquet"
            conn.execute(f"COPY {t} TO '{out}' (FORMAT PARQUET)")
            print(f"[parquet] wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--export-parquet", action="store_true")
    args = ap.parse_args()
    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2
    conn = duckdb.connect(str(args.db))
    apply(conn)

    stats = conn.execute("""
        SELECT (SELECT COUNT(*) FROM people)             AS n_people,
               (SELECT COUNT(*) FROM facility_personnel) AS n_personnel,
               (SELECT COUNT(*) FROM publications)       AS n_pubs,
               (SELECT COUNT(*) FROM authorship)         AS n_authorship,
               (SELECT COUNT(*) FROM collaborations)     AS n_collabs
    """).fetchone()
    print(f"[summary] people={stats[0]}  facility_personnel={stats[1]}  "
          f"publications={stats[2]}  authorship={stats[3]}  "
          f"collaborations={stats[4]}")

    if args.export_parquet:
        export_parquet(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
