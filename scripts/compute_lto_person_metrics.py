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
    python scripts/compute_lto_person_metrics.py --catalog db/lto_catalog.sqlite

Both tables are written into the lake in one snapshot; run
scripts/export_parquet.py afterwards to publish them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    args = ap.parse_args()

    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    with lto_db.transaction(conn, "compute_lto_person_metrics: person_areas + "
                                  "person_area_metrics from facility area_links"):
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
                   -- DOUBLE, as published (SUM(BIGINT) is HUGEINT).
                   CAST(sum(coalesce(p.cited_by_count, 0)) AS DOUBLE) AS total_citations,
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
        n_pam = lto_db.replace_table(conn, "person_area_metrics", """
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
            -- Mean and sample sd from exact integer sums: a windowed
            -- stddev() is order-dependent in its last bits, which made
            -- composite_z (and the published parquet) differ run to run.
            sums AS (
                SELECT area_id,
                       count(*)::HUGEINT                                     AS n,
                       sum(n_publications::HUGEINT)                          AS p1,
                       sum(n_publications::HUGEINT * n_publications)         AS p2,
                       sum(total_citations::HUGEINT)                         AS c1,
                       sum(total_citations::HUGEINT * total_citations::HUGEINT) AS c2,
                       sum(n_co_authors::HUGEINT)                            AS o1,
                       sum(n_co_authors::HUGEINT * n_co_authors)             AS o2
                FROM base GROUP BY area_id
            ),
            with_stats AS (
                SELECT base.*,
                       s.p1::DOUBLE / s.n AS pub_mu,
                       CASE WHEN s.n > 1 THEN sqrt((s.n * s.p2 - s.p1 * s.p1)::DOUBLE / (s.n * (s.n - 1))) END AS pub_sd,
                       s.c1::DOUBLE / s.n AS cit_mu,
                       CASE WHEN s.n > 1 THEN sqrt((s.n * s.c2 - s.c1 * s.c1)::DOUBLE / (s.n * (s.n - 1))) END AS cit_sd,
                       s.o1::DOUBLE / s.n AS co_mu,
                       CASE WHEN s.n > 1 THEN sqrt((s.n * s.o2 - s.o1 * s.o1)::DOUBLE / (s.n * (s.n - 1))) END AS co_sd
                FROM base JOIN sums s USING (area_id)
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
        print(f"[person_area_metrics] {n_pam} rows written")

        # 6. Refresh person_areas.evidence_count from publication count.
        conn.execute("""
            UPDATE person_areas
            SET evidence_count = coalesce(
                (SELECT n_pubs FROM _person_pub_totals
                 WHERE person_id = person_areas.person_id), 0)
        """)

        lto_db.assert_integrity(conn, ["person_areas", "person_area_metrics"])

    # 7. Publishing is export_parquet.py's job; both tables are in the lake.
    print("[done] person_areas + person_area_metrics written to the lake "
          "(run export_parquet.py to publish)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
