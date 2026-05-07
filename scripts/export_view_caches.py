#!/usr/bin/env python3
"""Pre-compute the People + Browse view-card JSON caches.

Both views run multi-CTE aggregation queries against DuckDB-Wasm on
first paint. On a high-RTT mobile link that means: download 8+
parquet files, parse the Arrow result, deserialize ~600 rows of nested
list/struct columns. End-to-end ~3-10 seconds.

This script runs the SAME SQL the views run, materialises the result
as a static JSON file under `public/cache/`, and the views fetch it
on first paint with a single HTTP request. Render becomes
fetch + JSON.parse + DOM build — sub-second on mobile.

DuckDB stays as the fallback path if the cache is missing or stale,
so the SQL tab keeps working and any future filtered queries still
go through the full DuckDB path.

Usage::

    python scripts/export_view_caches.py
    python scripts/export_view_caches.py --db db/cod_kmap.duckdb \
        --out public/cache
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
DEFAULT_OUT = ROOT / "public" / "cache"


PEOPLE_SQL = """
WITH per_pa AS (
  SELECT person_id,
         MAX(n_publications)  AS n_pubs,
         MAX(total_citations) AS total_citations,
         MAX(h_index)         AS h_index,
         MAX(n_co_authors)    AS n_coauth,
         SUM(composite_z)     AS composite_z
  FROM person_area_metrics
  GROUP BY person_id
),
per_pa_areas AS (
  SELECT pam.person_id,
         list(struct_pack(
           area_id   := pam.area_id,
           area      := ra.label,
           n_pubs    := pam.n_publications,
           citations := pam.total_citations,
           h         := pam.h_index
         ) ORDER BY pam.composite_z DESC) AS areas
  FROM person_area_metrics pam
  LEFT JOIN research_areas ra ON ra.area_id = pam.area_id
  GROUP BY pam.person_id
),
per_fund AS (
  SELECT fp.person_id,
         SUM(faf.total_usd_nominal) AS facility_funding_usd
  FROM facility_personnel fp
  JOIN facility_area_funding faf ON faf.facility_id = fp.facility_id
  GROUP BY fp.person_id
),
per_aff AS (
  SELECT fp.person_id,
         list(struct_pack(
           role        := fp.role,
           title       := fp.title,
           facility    := COALESCE(f.acronym || ' — ' || f.canonical_name,
                                   f.canonical_name),
           facility_id := f.facility_id,
           url         := f.url,
           country     := f.country,
           is_key      := fp.is_key_personnel
         ) ORDER BY fp.is_key_personnel DESC, fp.role) AS affiliations
  FROM facility_personnel fp
  JOIN facilities f ON f.facility_id = fp.facility_id
  GROUP BY fp.person_id
)
SELECT p.person_id  AS id,
       p.name,
       p.orcid,
       p.openalex_id,
       p.google_scholar_id,
       p.homepage_url,
       p.research_interests,
       p.bio,
       g.primary_area_id,
       ra.label                            AS primary_area_label,
       COALESCE(pa.n_pubs, 0)              AS n_pubs,
       COALESCE(pa.total_citations, 0)     AS total_citations,
       COALESCE(pa.h_index, 0)             AS h_index,
       COALESCE(pa.n_coauth, 0)            AS n_coauth,
       COALESCE(pa.composite_z, 0)         AS composite_z,
       COALESCE(pf.facility_funding_usd, 0) AS facility_funding_usd,
       paa.areas                           AS areas,
       pa2.affiliations                    AS affiliations
FROM   people p
LEFT JOIN person_primary_groups g  ON g.person_id  = p.person_id
LEFT JOIN research_areas       ra  ON ra.area_id   = g.primary_area_id
LEFT JOIN per_pa               pa  ON pa.person_id = p.person_id
LEFT JOIN per_pa_areas         paa ON paa.person_id = p.person_id
LEFT JOIN per_fund             pf  ON pf.person_id = p.person_id
LEFT JOIN per_aff              pa2 ON pa2.person_id = p.person_id
"""


# Browse-card SQL. Mirrors src/views/list.js fetchEnrichedFacilities
# but materialises ALL facilities (no IN-list filter — applyFilters runs
# client-side from the cache, same way the people view filters).
BROWSE_SQL = """
WITH base AS (
  SELECT f.facility_id        AS id,
         f.canonical_name     AS name,
         f.acronym,
         f.facility_type      AS type,
         f.country,
         f.region,
         f.hq_lat             AS lat,
         f.hq_lng             AS lng,
         f.url,
         f.parent_org,
         f.established,
         f.record_length_years,
         f.long_term_threshold_met,
         f.data_portal_url,
         (SELECT sphere_slug FROM facility_spheres
          WHERE facility_id = f.facility_id AND role = 'primary'
          LIMIT 1)            AS primary_sphere,
         (SELECT list(sphere_slug) FROM facility_spheres
          WHERE facility_id = f.facility_id AND role = 'secondary')
                              AS secondary_spheres
  FROM facilities f
),
nets AS (
  SELECT nm.facility_id,
         list(struct_pack(slug := n.network_id, label := n.label, url := n.url))
                              AS networks
  FROM network_membership nm
  JOIN networks n ON n.network_id = nm.network_id
  GROUP BY nm.facility_id
),
archives AS (
  SELECT fa.facility_id,
         count(DISTINCT fa.archive_id) AS n_archives,
         list(struct_pack(
           archive_id := fa.archive_id,
           name       := da.name,
           base_url   := da.base_url,
           scope_url  := fa.scope_url,
           sample_doi := fa.sample_doi
         ) ORDER BY da.name) AS archive_list
  FROM facility_archives fa
  LEFT JOIN data_archives da ON da.archive_id = fa.archive_id
  GROUP BY fa.facility_id
),
products AS (
  SELECT facility_id, count(*) AS n_products
  FROM data_products GROUP BY facility_id
),
personnel AS (
  SELECT fp.facility_id,
         count(DISTINCT fp.person_id) AS n_personnel,
         list(struct_pack(
           person_id := p.person_id,
           name      := p.name,
           role      := fp.role,
           title     := fp.title,
           orcid     := p.orcid,
           openalex  := p.openalex_id,
           homepage  := p.homepage_url,
           is_key    := fp.is_key_personnel
         ) ORDER BY fp.is_key_personnel DESC, fp.role) AS personnel_list
  FROM facility_personnel fp
  JOIN people p ON p.person_id = fp.person_id
  GROUP BY fp.facility_id
),
pubs AS (
  SELECT fp.facility_id,
         count(DISTINCT a.publication_id) AS n_pubs
  FROM authorship a
  JOIN facility_personnel fp ON fp.person_id = a.person_id
  GROUP BY fp.facility_id
),
funding AS (
  SELECT fe.facility_id,
         count(*) AS n_funding,
         sum(coalesce(fe.amount_usd, 0)) AS total_funding,
         list(struct_pack(
           funder := fr.name,
           program := fe.program,
           amount := fe.amount_usd,
           fy := fe.fiscal_year
         ) ORDER BY coalesce(fe.amount_usd, 0) DESC) AS funding_list
  FROM funding_events fe
  JOIN funders fr ON fr.funder_id = fe.funder_id
  GROUP BY fe.facility_id
),
areas AS (
  SELECT al.facility_id, list(DISTINCT ra.label) AS research_areas
  FROM area_links al
  JOIN research_areas ra ON ra.area_id = al.area_id
  GROUP BY al.facility_id
)
SELECT b.*,
       coalesce(n.networks, [])                  AS networks,
       coalesce(a.n_archives, 0)                 AS n_archives,
       coalesce(a.archive_list, [])              AS archive_list,
       coalesce(pr.n_products, 0)                AS n_products,
       coalesce(pe.n_personnel, 0)               AS n_personnel,
       coalesce(pe.personnel_list, [])           AS personnel_list,
       coalesce(pu.n_pubs, 0)                    AS n_pubs,
       coalesce(fu.n_funding, 0)                 AS n_funding,
       coalesce(fu.total_funding, 0)             AS total_funding,
       coalesce(fu.funding_list, [])             AS funding_list,
       coalesce(ar.research_areas, [])           AS research_areas
FROM base b
LEFT JOIN nets      n  ON n.facility_id  = b.id
LEFT JOIN archives  a  ON a.facility_id  = b.id
LEFT JOIN products  pr ON pr.facility_id = b.id
LEFT JOIN personnel pe ON pe.facility_id = b.id
LEFT JOIN pubs      pu ON pu.facility_id = b.id
LEFT JOIN funding   fu ON fu.facility_id = b.id
LEFT JOIN areas     ar ON ar.facility_id = b.id
"""


def to_jsonable(v):
    """Recursively convert DuckDB results to plain JSON-friendly Python.

    DuckDB returns LIST<STRUCT> as nested dicts/lists already; the only
    fixups needed are bytes (none here) and Decimals (we only have ints
    + floats). Drop nulls inside list items so the JS view doesn't have
    to defend against {} placeholders.
    """
    if v is None:
        return None
    if isinstance(v, list):
        return [to_jsonable(x) for x in v if x is not None]
    if isinstance(v, dict):
        return {k: to_jsonable(val) for k, val in v.items()}
    return v


def export_query(conn, sql: str, out_path: Path) -> int:
    # Use DuckDB's native dict-row fetcher (no pyarrow dependency).
    # `fetchall()` returns tuples; combine with the cursor's description
    # to build per-row dicts. LIST<STRUCT> columns come back as nested
    # Python lists/dicts already.
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    payload = [
        {col: to_jsonable(val) for col, val in zip(cols, row)}
        for row in cur.fetchall()
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Compact JSON — every byte saved is a byte mobile users don't pay
    # for. The browser does JSON.parse anyway so whitespace adds no
    # value. Use ensure_ascii=False so unicode (Guánica, Pu'u Maka'ala)
    # stays as UTF-8 instead of \u escapes.
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(args.db), read_only=True) as conn:
        n_people = export_query(conn, PEOPLE_SQL, args.out / "people_cards.json")
        print(f"[cache] wrote {n_people:4d} rows → {args.out / 'people_cards.json'}"
              f"  ({(args.out / 'people_cards.json').stat().st_size // 1024} KB)")

        n_browse = export_query(conn, BROWSE_SQL, args.out / "browse_cards.json")
        print(f"[cache] wrote {n_browse:4d} rows → {args.out / 'browse_cards.json'}"
              f"  ({(args.out / 'browse_cards.json').stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
