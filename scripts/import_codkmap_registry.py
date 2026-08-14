#!/usr/bin/env python3
"""Import site-linked researchers from the cod-kmap registry — no API calls.

cod-kmap already harvested and identifier-resolved 152k researchers, and
its committed db/parquet/ carries the FULL population (its public/ ships
only the core tier). 143 coastal facilities exist in both catalogues
with identical facility_id hashes (LTO vendored them), so everything
upstream learned about researchers AT those facilities transfers by
parquet join instead of a second OpenAlex harvest:

  1. facilities.ror        45 shared facilities gain upstream's resolved
                           ROR (a head start on harvest step H10).
  2. person_registry       researchers linked to a shared facility via
                           upstream's ROR-joined registry_facilities
                           (~1,139), minus codp: local identities (LTO
                           mints no local-id form) and minus anyone
                           already in LTO's registry (LTO's row wins).
  3. registry_facilities   the researcher↔facility edges for imported +
                           existing identities at shared facilities.
  4. registry_collaborations
                           co-publication edges whose BOTH endpoints now
                           exist in LTO's registry.

Column policy: identifier / name / affiliation / bibliometric columns
copy verbatim (same canonical_id minting rule on both sides — 'orcid:…'
else 'openalex:A…'). Upstream's coastal_works_count / coastal_share are
NOT mapped onto lto_works_count / lto_share: they measure a different
topic set, and a wrong-basis number is worse than a NULL — the LTO-topic
measure lands with the M5 works harvest. cod-only columns (is_team,
scholar_id, person_id) are dropped; imports arrive is_scholar=true,
tier='archive' (rank_person_registry re-tiers).

Provenance: each imported row keeps its upstream source_url and gains a
person_identity_source assertion (method='cod-kmap-import') naming the
upstream parquet snapshot, so every import can be walked back.

Idempotent: existing canonical_ids are never overwritten; edge inserts
are keyed. Usage::

    python scripts/import_codkmap_registry.py [--dry-run]
    python scripts/import_codkmap_registry.py --upstream ../cod-kmap/db/parquet
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "lto.duckdb"
DEFAULT_UPSTREAM = ROOT.parent / "cod-kmap" / "db" / "parquet"
UPSTREAM_URL = "https://github.com/tyson-swetnam/cod-kmap"

# Columns copied verbatim from the upstream registry row.
COPY_COLS = [
    "canonical_id", "display_name", "name_family", "name_given",
    "orcid", "openalex_id", "google_scholar_id", "scopus_author_id",
    "wos_researcher_id", "homepage_url",
    "affiliation", "affiliation_ror", "affiliation_country",
    "works_count", "cited_by_count", "h_index", "i10_index",
    "two_yr_mean_citedness", "first_pub_year",
    "source_url", "confidence", "retrieved_at",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", type=Path, default=DEFAULT_UPSTREAM)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    up = args.upstream
    for req in ("person_registry", "registry_facilities", "facilities",
                "registry_collaborations"):
        if not (up / f"{req}.parquet").exists():
            print(f"[error] {up / req}.parquet not found", file=sys.stderr)
            return 2

    conn = duckdb.connect(str(DB))
    conn.execute("SET search_path = main;")
    pq = lambda t: f"read_parquet('{up / t}.parquet')"  # noqa: E731
    today = dt.date.today().isoformat()

    # Shared facilities = identical facility_id hashes on both sides.
    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _shared AS
        SELECT f.facility_id, u.ror AS upstream_ror
        FROM facilities f
        JOIN {pq('facilities')} u USING (facility_id)""")
    n_shared = conn.execute("SELECT count(*) FROM _shared").fetchone()[0]

    # 1. ROR backfill — only where LTO has none (never clobber).
    ror_new = conn.execute("""
        SELECT count(*) FROM facilities f JOIN _shared s USING (facility_id)
        WHERE f.ror IS NULL AND s.upstream_ror IS NOT NULL""").fetchone()[0]
    if not args.dry_run:
        conn.execute("""
            UPDATE facilities SET ror = s.upstream_ror
            FROM _shared s
            WHERE facilities.facility_id = s.facility_id
              AND facilities.ror IS NULL AND s.upstream_ror IS NOT NULL""")
    print(f"[ror] {ror_new} facility ROR(s) imported ({n_shared} shared facilities)")

    # 2. Site-linked upstream researchers not already ours, no codp: rows.
    conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _import AS
        SELECT DISTINCT r.*
        FROM {pq('person_registry')} r
        JOIN {pq('registry_facilities')} rf ON rf.canonical_id = r.canonical_id
        JOIN _shared s ON s.facility_id = rf.facility_id
        WHERE r.canonical_id NOT LIKE 'codp:%'
          AND (r.orcid IS NOT NULL OR r.openalex_id IS NOT NULL)
          AND r.canonical_id NOT IN (SELECT canonical_id FROM person_registry)""")
    n_import = conn.execute("SELECT count(*) FROM _import").fetchone()[0]
    if not args.dry_run and n_import:
        cols = ", ".join(COPY_COLS)
        conn.execute(f"""
            INSERT INTO person_registry
                ({cols}, is_site_personnel, is_scholar, tier, source, notes)
            SELECT {cols}, false, true, 'archive', 'cod-kmap-import',
                   'imported from the cod-kmap registry (site-linked via ROR); '
                   || 'lto_works_count pending the LTO-topic measure'
            FROM _import""")
        conn.execute(f"""
            INSERT INTO person_identity_source
                (canonical_id, field, value, method, evidence, source_url,
                 confidence, retrieved_at)
            SELECT canonical_id, 'merge', canonical_id, 'cod-kmap-import',
                   'site-linked researcher carried over from the upstream '
                   || 'registry parquet; identifiers resolved upstream by '
                   || 'identifier-equality rules',
                   '{UPSTREAM_URL}', 'high', '{today}'
            FROM _import""")
    print(f"[registry] {n_import} researcher(s) imported (site-linked, "
          "identifier-keyed, codp: excluded)")

    # 3. Researcher↔facility edges at shared facilities, both ends known.
    n_edges = conn.execute(f"""
        SELECT count(*) FROM {pq('registry_facilities')} rf
        JOIN _shared s USING (facility_id)
        WHERE rf.canonical_id IN (SELECT canonical_id FROM person_registry)
          AND (rf.canonical_id, rf.facility_id) NOT IN
              (SELECT canonical_id, facility_id FROM registry_facilities)""").fetchone()[0]
    if not args.dry_run and n_edges:
        conn.execute(f"""
            INSERT INTO registry_facilities
                (canonical_id, facility_id, method, ror, source_url,
                 retrieved_at, confidence)
            SELECT rf.canonical_id, rf.facility_id, 'ror-equality',
                   s.upstream_ror, '{UPSTREAM_URL}', '{today}', 'high'
            FROM {pq('registry_facilities')} rf
            JOIN _shared s USING (facility_id)
            WHERE rf.canonical_id IN (SELECT canonical_id FROM person_registry)
              AND (rf.canonical_id, rf.facility_id) NOT IN
                  (SELECT canonical_id, facility_id FROM registry_facilities)""")
    print(f"[links] {n_edges} researcher↔facility edge(s) imported")

    # 4. Collaboration edges with both endpoints in our registry.
    n_collab = conn.execute(f"""
        SELECT count(*) FROM {pq('registry_collaborations')} e
        WHERE e.canonical_id_a IN (SELECT canonical_id FROM person_registry)
          AND e.canonical_id_b IN (SELECT canonical_id FROM person_registry)
          AND (e.canonical_id_a, e.canonical_id_b) NOT IN
              (SELECT canonical_id_a, canonical_id_b FROM registry_collaborations)""").fetchone()[0]
    if not args.dry_run and n_collab:
        conn.execute(f"""
            INSERT INTO registry_collaborations
            SELECT e.* FROM {pq('registry_collaborations')} e
            WHERE e.canonical_id_a IN (SELECT canonical_id FROM person_registry)
              AND e.canonical_id_b IN (SELECT canonical_id FROM person_registry)
              AND (e.canonical_id_a, e.canonical_id_b) NOT IN
                  (SELECT canonical_id_a, canonical_id_b FROM registry_collaborations)""")
    print(f"[collab] {n_collab} co-publication edge(s) imported")

    total = conn.execute("SELECT count(*) FROM person_registry").fetchone()[0]
    print(f"[done] person_registry now {total:,} rows"
          + (" (dry run — no writes)" if args.dry_run else ""))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
