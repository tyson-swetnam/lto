#!/usr/bin/env python3
"""Compute person_area_metrics + person_areas directly from LTO data.

The cod-kmap `compute_area_metrics.py` requires `publication_topics`
(populated by `enrich_people_openalex.py` from the OpenAlex topics API)
and a GCMD ↔ OpenAlex crosswalk. In this LTO sandbox the OpenAlex API
is blocked at the network level, so `publication_topics` stays empty
and the People view renders 0/NaN for every metric.

This script bypasses OpenAlex by inferring research areas from each
person's *facility* affiliations (area_links). It writes:

  * person_areas             person × area weighted membership
  * person_area_metrics      n_pubs / total_citations / h_index /
                              n_co_authors / composite_z per (person, area)

For each person:
  1. areas = union of all area_ids for the facilities they are
     affiliated to (via facility_personnel → area_links).
  2. publications = all publications they authored (via authorship).
  3. citations[] = list of publications.cited_by_count for those pubs.
  4. h_index = max k such that the kth-largest citation is >= k.
  5. n_co_authors = distinct co-authors in `authorship` for the same
     publications.

Per-area rows are produced by attributing each (person, pub) to every
area in the person's set, so h-index and citations are *the person's
total* tagged to each of their areas. The composite_z is then
within-area z-scored across all people in that area.

Usage::

    python scripts/compute_lto_person_metrics.py
    python scripts/compute_lto_person_metrics.py --db db/cod_kmap.duckdb
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
PARQUET_DIRS = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()

    with duckdb.connect(str(args.db)) as conn:
        # 1. Seed person_areas from facility_personnel JOIN area_links.
        #    Each (person, area) row has weight = 1/len(facility_areas)
        #    so a single-facility person totals 1.0 across all their areas.
        conn.execute("DELETE FROM person_areas")
        conn.execute("""
            INSERT INTO person_areas (person_id, area_id, weight, evidence_count, source)
            WITH base AS (
                SELECT DISTINCT fp.person_id, al.area_id
                FROM facility_personnel fp
                JOIN area_links al ON al.facility_id = fp.facility_id
            ),
            per_person_n AS (
                SELECT person_id, count(*) AS n_areas FROM base GROUP BY person_id
            )
            SELECT b.person_id, b.area_id,
                   1.0 / NULLIF(p.n_areas, 0) AS weight,
                   0 AS evidence_count,
                   'facility-area-inheritance' AS source
            FROM base b
            JOIN per_person_n p ON p.person_id = b.person_id
        """)
        n_pa = conn.execute("SELECT count(*) FROM person_areas").fetchone()[0]
        print(f"[person_areas] {n_pa} rows seeded from facility area_links")

        # 2. Per-person totals from authorship + publications.
        conn.execute("DROP TABLE IF EXISTS _person_pub_totals")
        conn.execute("""
            CREATE TEMP TABLE _person_pub_totals AS
            SELECT a.person_id,
                   count(DISTINCT a.publication_id) AS n_pubs,
                   sum(coalesce(p.cited_by_count, 0)) AS total_citations,
                   array_agg(coalesce(p.cited_by_count, 0)
                             ORDER BY coalesce(p.cited_by_count, 0) DESC)
                                                    AS cite_list
            FROM authorship a
            JOIN publications p ON p.publication_id = a.publication_id
            GROUP BY a.person_id
        """)

        # 3. h-index per person from the citation list.
        conn.execute("DROP TABLE IF EXISTS _person_h")
        conn.execute("""
            CREATE TEMP TABLE _person_h AS
            SELECT person_id,
                   coalesce(
                       (SELECT max(idx) FROM (
                            SELECT generate_subscripts(cite_list, 1) AS idx,
                                   unnest(cite_list) AS c
                       ) WHERE c >= idx),
                       0
                   ) AS h_index
            FROM _person_pub_totals
        """)

        # 4. Per-person co-author count from the authorship graph.
        conn.execute("DROP TABLE IF EXISTS _person_coauth")
        conn.execute("""
            CREATE TEMP TABLE _person_coauth AS
            SELECT a1.person_id,
                   count(DISTINCT a2.person_id) AS n_co_authors
            FROM authorship a1
            JOIN authorship a2
              ON a1.publication_id = a2.publication_id
             AND a1.person_id <> a2.person_id
            GROUP BY a1.person_id
        """)

        # 5. Materialize person_area_metrics: cross person totals × person_areas.
        #    Each (person, area) row carries the person's TOTAL n_pubs / citations
        #    / co-authors (NOT divided), because src/views/people.js rolls up
        #    with `MAX(...)` (not `SUM(...)`) to get per-person totals. The
        #    composite_z is the within-area z-score so the area-list ordering
        #    still ranks people by their relative strength in each area.
        conn.execute("DROP TABLE IF EXISTS person_area_metrics")
        conn.execute("""
            CREATE TABLE person_area_metrics AS
            WITH base AS (
                SELECT pa.area_id,
                       p.person_id,
                       p.name AS person_name,
                       coalesce(t.n_pubs, 0)          AS n_publications,
                       coalesce(t.total_citations, 0) AS total_citations,
                       coalesce(h.h_index, 0)         AS h_index,
                       coalesce(c.n_co_authors, 0)    AS n_co_authors
                FROM person_areas pa
                JOIN people p ON p.person_id = pa.person_id
                LEFT JOIN _person_pub_totals t ON t.person_id = p.person_id
                LEFT JOIN _person_h           h ON h.person_id = p.person_id
                LEFT JOIN _person_coauth      c ON c.person_id = p.person_id
            ),
            with_stats AS (
                SELECT *,
                       avg(n_publications)  OVER (PARTITION BY area_id) AS pub_mu,
                       stddev(n_publications) OVER (PARTITION BY area_id) AS pub_sd,
                       avg(total_citations) OVER (PARTITION BY area_id) AS cit_mu,
                       stddev(total_citations) OVER (PARTITION BY area_id) AS cit_sd,
                       avg(n_co_authors)    OVER (PARTITION BY area_id) AS co_mu,
                       stddev(n_co_authors) OVER (PARTITION BY area_id) AS co_sd
                FROM base
            )
            SELECT area_id, person_id, person_name,
                   n_publications, total_citations, h_index, n_co_authors,
                   coalesce(
                       (n_publications  - pub_mu) / NULLIF(pub_sd, 0), 0
                   ) +
                   coalesce(
                       (total_citations - cit_mu) / NULLIF(cit_sd, 0), 0
                   ) +
                   coalesce(
                       (n_co_authors    - co_mu) / NULLIF(co_sd,  0), 0
                   ) AS composite_z
            FROM with_stats
        """)
        n_pam = conn.execute("SELECT count(*) FROM person_area_metrics").fetchone()[0]
        print(f"[person_area_metrics] {n_pam} rows written")

        # 6. Refresh person_areas.evidence_count from publication count.
        conn.execute("""
            UPDATE person_areas
            SET evidence_count = coalesce(
                (SELECT n_pubs FROM _person_pub_totals
                 WHERE person_id = person_areas.person_id), 0)
        """)

        # 7. Export the affected parquets.
        for table in ("person_areas", "person_area_metrics"):
            for d in PARQUET_DIRS:
                d.mkdir(parents=True, exist_ok=True)
                p = d / f"{table}.parquet"
                conn.execute(f"COPY (SELECT * FROM {table}) TO '{p}' (FORMAT PARQUET)")
                print(f"[parquet] wrote {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
