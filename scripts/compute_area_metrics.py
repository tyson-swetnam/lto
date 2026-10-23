#!/usr/bin/env python3
"""Compute per-research-area dashboard metrics for the Stats view.

Reads the DuckLake (scripts/lto_db.py) and writes three derived tables
back into it; export_parquet.py ships them as the parquets that drive the
per-area dashboards in src/views/stats.js:

  1. person_area_metrics — composite researcher score per
     (area_id, person_id):
        n_publications  : COUNT(DISTINCT publications) tagged to that
                          area via publication_topics × crosswalk
        n_co_authors    : COUNT(DISTINCT co-author) restricted to area
        total_citations : SUM(publications.cited_by_count)
        h_index         : Hirsch h on the person's pub × citation list
        composite_z     : z-scored sum of pubs + coauthors + citations
                          (within-area normalised so areas with thin
                          publication coverage don't disadvantage their
                          own top researchers)

  2. facility_area_funding — per (area_id, facility_id):
        n_funding_events
        total_usd_nominal      (FY2015-FY2024)
        n_distinct_funders
        funder_top1_name + funder_top1_usd  (largest funder for the
                                              facility within this area)
     Plus a per (area_id, funder_id) table, funder_area_funding,
     showing each area's largest contributors.

  3. area_coverage_matrix — per (area_id, country) and per
     (area_id, region_kind) facility counts, used by the gap-analysis
     callouts. (region_kind = sanctuary | nerr-reserve | nep-program |
     nps-unit | neon-domain | epa-region.)

Idempotent — replaces every table on each run, in one lake snapshot.
Run scripts/export_parquet.py afterwards to publish them.

Usage::
    python scripts/compute_area_metrics.py
    python scripts/compute_area_metrics.py --catalog db/lto_catalog.sqlite
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def sync_research_areas(conn) -> None:
    """Add research areas the vocab CSV has gained since the DB was built.

    A lake rebuilt from parquet carries research_areas as of the last
    export, so an area added to schema/vocab/research_areas.csv (and used
    by the crosswalk) would otherwise produce metrics rows with no label.
    """
    csv_path = ROOT / "schema" / "vocab" / "research_areas.csv"
    before = conn.execute("SELECT COUNT(*) FROM research_areas").fetchone()[0]
    conn.execute(f"""
        INSERT INTO research_areas (area_id, label, gcmd_uri, parent_id)
        SELECT slug, label, NULLIF(gcmd_uri, ''), NULLIF(parent_slug, '')
        FROM read_csv_auto('{csv_path}', header=true, all_varchar=true)
        WHERE slug NOT IN (SELECT area_id FROM research_areas)
    """)
    added = conn.execute("SELECT COUNT(*) FROM research_areas").fetchone()[0] - before
    if added:
        print(f"[research_areas] added {added} area(s) from the vocab CSV")


def compute_person_area_metrics(conn) -> None:
    """Build per (area, person) composite score table.

    Joins authorship × publication_topics × crosswalk → for each
    person we know which areas their work hits and how strongly.
    Then aggregates.
    """
    print("[person_area_metrics] computing…")

    # Load the OpenAlex → research_area crosswalk into a temp table so
    # the SQL joins stay clean.
    cw_csv = ROOT / "data" / "vocab_crosswalk" / "openalex_to_area.csv"
    if not cw_csv.exists():
        print(f"[error] crosswalk missing: {cw_csv}", file=sys.stderr)
        return
    conn.execute("DROP TABLE IF EXISTS _crosswalk")
    conn.execute(f"""
        CREATE TEMP TABLE _crosswalk AS
        SELECT openalex_id, area_id,
               CASE confidence
                 WHEN 'high'   THEN 1.0
                 WHEN 'medium' THEN 0.7
                 WHEN 'low'    THEN 0.4
                 ELSE 0.4
               END AS conf_mult
        FROM read_csv_auto('{cw_csv}', ignore_errors=true, header=true,
                           skip=0, all_varchar=true)
        WHERE openalex_id IS NOT NULL AND area_id IS NOT NULL
          AND length(openalex_id) > 0 AND length(area_id) > 0
          AND openalex_id NOT LIKE '#%'
          AND area_id IN (SELECT area_id FROM research_areas)
    """)
    n_cw = conn.execute("SELECT COUNT(*) FROM _crosswalk").fetchone()[0]
    print(f"  crosswalk rows loaded: {n_cw}")

    # 1. (publication_id, area_id, score) — publication-area mapping.
    conn.execute("DROP TABLE IF EXISTS _pub_area")
    conn.execute("""
        CREATE TEMP TABLE _pub_area AS
        WITH pa_raw AS (
          SELECT pt.publication_id, cw.area_id,
                 MAX(COALESCE(pt.score, 0.5) * cw.conf_mult) AS score
          FROM   publication_topics pt
          JOIN   _crosswalk cw ON cw.openalex_id = pt.concept_id
          GROUP  BY pt.publication_id, cw.area_id
        )
        SELECT * FROM pa_raw
    """)
    n_pa = conn.execute("SELECT COUNT(*) FROM _pub_area").fetchone()[0]
    print(f"  publication-area rows: {n_pa}")

    # 2. (area_id, person_id, n_pubs, total_citations) — direct counts.
    conn.execute("DROP TABLE IF EXISTS _person_area_pubs")
    conn.execute("""
        CREATE TEMP TABLE _person_area_pubs AS
        SELECT pa.area_id, a.person_id,
               COUNT(DISTINCT pa.publication_id)     AS n_publications,
               -- DOUBLE, not the HUGEINT SUM(BIGINT) gives: the published
               -- parquet (and a lake rebuilt from it) holds DOUBLE, and a
               -- HUGEINT reaches duckdb-wasm as a non-number.
               CAST(SUM(COALESCE(p.cited_by_count, 0)) AS DOUBLE) AS total_citations,
               array_agg(COALESCE(p.cited_by_count, 0)
                         ORDER BY COALESCE(p.cited_by_count, 0) DESC)
                                                     AS cite_list
        FROM   _pub_area pa
        JOIN   authorship    a ON a.publication_id = pa.publication_id
        JOIN   publications  p ON p.publication_id = pa.publication_id
        GROUP  BY pa.area_id, a.person_id
    """)
    n = conn.execute("SELECT COUNT(*) FROM _person_area_pubs").fetchone()[0]
    print(f"  (area, person) base rows: {n}")

    # 3. h-index per (area, person) computed from cite_list.
    #    h = max k such that cite_list[k-1] >= k.
    conn.execute("DROP TABLE IF EXISTS _h_indexes")
    conn.execute("""
        CREATE TEMP TABLE _h_indexes AS
        SELECT area_id, person_id,
               (SELECT MAX(idx) FROM (
                  SELECT generate_subscripts(cite_list, 1) AS idx,
                         unnest(cite_list)               AS c
               ) WHERE c >= idx) AS h_index
        FROM _person_area_pubs
    """)

    # 4. per-area co-author counts (collaborations restricted to people
    #    who published in that area).
    conn.execute("DROP TABLE IF EXISTS _person_area_coauth")
    conn.execute("""
        CREATE TEMP TABLE _person_area_coauth AS
        WITH per_area_people AS (
            SELECT DISTINCT area_id, person_id FROM _person_area_pubs
        )
        SELECT pap.area_id, pap.person_id,
               COUNT(DISTINCT
                     CASE WHEN c.person_a_id = pap.person_id
                          THEN c.person_b_id
                          ELSE c.person_a_id END) AS n_co_authors
        FROM   per_area_people pap
        LEFT  JOIN collaborations c
               ON c.person_a_id = pap.person_id
               OR c.person_b_id = pap.person_id
        GROUP  BY pap.area_id, pap.person_id
    """)

    # 5. Combine + composite z-score (within-area normalisation).
    # Pre-flight: if _person_area_pubs has no rows (e.g. publication_topics
    # is empty because OpenAlex topics were never harvested), DO NOT
    # clobber person_area_metrics — the LTO-native compute_lto_person_metrics.py
    # populates the same table from authorship + publications and we
    # don't want this script's empty result to overwrite it.
    n_pap = conn.execute("SELECT count(*) FROM _person_area_pubs").fetchone()[0]
    if n_pap == 0:
        print("[person_area_metrics] _person_area_pubs is empty "
              "(publication_topics not harvested?); SKIPPING write — "
              "leaving existing person_area_metrics rows intact "
              "(populated by compute_lto_person_metrics.py).")
        return
    n = lto_db.replace_table(conn, "person_area_metrics", """
        WITH base AS (
          SELECT b.area_id, b.person_id, p.name AS person_name,
                 b.n_publications,
                 b.total_citations,
                 COALESCE(h.h_index, 0)        AS h_index,
                 COALESCE(c.n_co_authors, 0)   AS n_co_authors
          FROM   _person_area_pubs b
          JOIN   people p             ON p.person_id = b.person_id
          LEFT  JOIN _h_indexes h     ON h.area_id = b.area_id
                                     AND h.person_id = b.person_id
          LEFT  JOIN _person_area_coauth c
                                      ON c.area_id = b.area_id
                                     AND c.person_id = b.person_id
        ),
        -- Per-area mean and sample standard deviation for z-scoring,
        -- computed from exact integer sums (every input is a count).
        -- stddev() over a window accumulates in floating point in
        -- whatever order the rows arrive, so composite_z changed in its
        -- last bits from run to run and every re-run rewrote the
        -- published parquet. Same values to ~1e-14; now reproducible.
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
        stats AS (
          SELECT area_id,
                 p1::DOUBLE / n AS pub_mu,
                 CASE WHEN n > 1 THEN sqrt((n * p2 - p1 * p1)::DOUBLE / (n * (n - 1))) END AS pub_sd,
                 c1::DOUBLE / n AS cit_mu,
                 CASE WHEN n > 1 THEN sqrt((n * c2 - c1 * c1)::DOUBLE / (n * (n - 1))) END AS cit_sd,
                 o1::DOUBLE / n AS co_mu,
                 CASE WHEN n > 1 THEN sqrt((n * o2 - o1 * o1)::DOUBLE / (n * (n - 1))) END AS co_sd
          FROM sums
        ),
        with_stats AS (
          SELECT base.*, stats.* EXCLUDE (area_id)
          FROM base JOIN stats USING (area_id)
        )
        SELECT area_id, person_id, person_name,
               n_publications, total_citations, h_index, n_co_authors,
               -- z-score sum; defend against sd=0 in tiny areas
               (CASE WHEN COALESCE(pub_sd, 0) > 0
                     THEN (n_publications  - pub_mu) / pub_sd ELSE 0 END) +
               (CASE WHEN COALESCE(cit_sd, 0) > 0
                     THEN (total_citations - cit_mu) / cit_sd ELSE 0 END) +
               (CASE WHEN COALESCE(co_sd, 0)  > 0
                     THEN (n_co_authors    - co_mu) / co_sd  ELSE 0 END)
                 AS composite_z
        FROM with_stats
    """)
    print(f"  person_area_metrics rows: {n}")


def compute_facility_area_funding(conn) -> None:
    """Per (area, facility) funding rollup + per (area, funder) breakdown.

    Joins funding_events × facility_primary_groups so each facility's
    funding shows up under its primary research area. Excludes
    'annual-revenue-990' rows (which are org-total context, not
    per-grant)."""
    print("[area funding] computing…")

    n = lto_db.replace_table(conn, "facility_area_funding", """
        WITH events AS (
          SELECT g.primary_area_id AS area_id,
                 fe.facility_id,
                 fe.funder_id,
                 fe.amount_usd,
                 fe.fiscal_year
          FROM   funding_events fe
          JOIN   facility_primary_groups g
            ON   g.facility_id = fe.facility_id
          WHERE  COALESCE(fe.relation, '') <> 'annual-revenue-990'
            AND  fe.amount_usd IS NOT NULL
            AND  g.primary_area_id IS NOT NULL
        ),
        per_fac AS (
          SELECT area_id, facility_id,
                 COUNT(*)                       AS n_funding_events,
                 SUM(amount_usd)                AS total_usd_nominal,
                 COUNT(DISTINCT funder_id)      AS n_distinct_funders,
                 MIN(fiscal_year)               AS min_fy,
                 MAX(fiscal_year)               AS max_fy
          FROM events
          GROUP BY area_id, facility_id
        ),
        per_fac_funder AS (
          SELECT area_id, facility_id, funder_id,
                 SUM(amount_usd) AS funder_usd
          FROM events
          GROUP BY area_id, facility_id, funder_id
        ),
        top_funder AS (
          SELECT area_id, facility_id, funder_id, funder_usd,
                 ROW_NUMBER() OVER (
                   PARTITION BY area_id, facility_id
                   ORDER BY funder_usd DESC, funder_id ASC
                 ) AS rk
          FROM per_fac_funder
        )
        SELECT pf.area_id, pf.facility_id,
               f.canonical_name           AS facility_name,
               f.acronym                  AS facility_acronym,
               f.country,
               pf.n_funding_events,
               pf.total_usd_nominal,
               pf.n_distinct_funders,
               pf.min_fy, pf.max_fy,
               fu.name                    AS funder_top1_name,
               tf.funder_usd              AS funder_top1_usd
        FROM   per_fac pf
        JOIN   facilities f ON f.facility_id = pf.facility_id
        LEFT  JOIN top_funder tf
               ON tf.area_id = pf.area_id
              AND tf.facility_id = pf.facility_id
              AND tf.rk = 1
        LEFT  JOIN funders fu ON fu.funder_id = tf.funder_id
    """)
    print(f"  facility_area_funding rows: {n}")

    # Per (area, funder)
    n = lto_db.replace_table(conn, "funder_area_funding", """
        WITH events AS (
          SELECT g.primary_area_id AS area_id,
                 fe.funder_id,
                 fe.facility_id,
                 fe.amount_usd
          FROM   funding_events fe
          JOIN   facility_primary_groups g
            ON   g.facility_id = fe.facility_id
          WHERE  COALESCE(fe.relation, '') <> 'annual-revenue-990'
            AND  fe.amount_usd IS NOT NULL
            AND  g.primary_area_id IS NOT NULL
        )
        SELECT e.area_id, e.funder_id, fu.name AS funder_name,
               fu.type AS funder_type,
               COUNT(*) AS n_events,
               SUM(e.amount_usd) AS total_usd,
               COUNT(DISTINCT e.facility_id) AS n_facilities
        FROM events e
        JOIN funders fu ON fu.funder_id = e.funder_id
        GROUP BY e.area_id, e.funder_id, fu.name, fu.type
    """)
    print(f"  funder_area_funding rows: {n}")


def compute_coverage_matrix(conn) -> None:
    """Per (area, country) + per (area, region_kind) facility counts.

    Lets the dashboard call out 'no facility in this area for the
    Pacific Northwest' style gaps."""
    print("[coverage matrix] computing…")

    n = lto_db.replace_table(conn, "area_coverage_matrix", """
        SELECT g.primary_area_id    AS area_id,
               'country'             AS dim,
               f.country             AS bucket,
               COUNT(DISTINCT f.facility_id) AS n_facilities
        FROM   facilities f
        JOIN   facility_primary_groups g ON g.facility_id = f.facility_id
        WHERE  g.primary_area_id IS NOT NULL
        GROUP  BY g.primary_area_id, f.country
        UNION ALL
        SELECT g.primary_area_id    AS area_id,
               'region_kind'         AS dim,
               r.kind                AS bucket,
               COUNT(DISTINCT f.facility_id) AS n_facilities
        FROM   facilities f
        JOIN   facility_primary_groups g ON g.facility_id = f.facility_id
        JOIN   facility_regions  fr ON fr.facility_id = f.facility_id
        JOIN   regions           r  ON r.region_id    = fr.region_id
        WHERE  g.primary_area_id IS NOT NULL
        GROUP  BY g.primary_area_id, r.kind
        UNION ALL
        SELECT g.primary_area_id    AS area_id,
               'facility_type'       AS dim,
               f.facility_type       AS bucket,
               COUNT(DISTINCT f.facility_id) AS n_facilities
        FROM   facilities f
        JOIN   facility_primary_groups g ON g.facility_id = f.facility_id
        WHERE  g.primary_area_id IS NOT NULL
        GROUP  BY g.primary_area_id, f.facility_type
    """)
    print(f"  area_coverage_matrix rows: {n}")


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    args = ap.parse_args()

    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)

    # facility_primary_groups / person_primary_groups / research_areas_active
    # are lake tables now (scripts/compute_primary_groups.py writes them
    # there), so the old "register the exported parquet as a view" step is
    # gone: reading db/parquet here would see the previous export, not the
    # latest compute.
    with lto_db.transaction(conn, "compute_area_metrics: person_area_metrics, "
                                  "facility/funder_area_funding, area_coverage_matrix"):
        sync_research_areas(conn)
        compute_person_area_metrics(conn)
        compute_facility_area_funding(conn)
        compute_coverage_matrix(conn)
        lto_db.assert_integrity(conn, ["research_areas", "person_area_metrics",
                                       "facility_area_funding", "funder_area_funding",
                                       "area_coverage_matrix"])

    print("[done] tables written to the lake (run export_parquet.py to publish)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
