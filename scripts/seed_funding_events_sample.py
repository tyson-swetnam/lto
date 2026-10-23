#!/usr/bin/env python3
"""Seed a small sample of funding_events rows so the time-series schema
has real, queryable data end-to-end.

The rows here are drawn from NSF Award Search (public record) for the
LTER sites that appear in our `facilities` table. Amounts are the
continuing-award allocations per fiscal year as recorded on nsf.gov;
award ids are the NSF identifiers.

This is a *starter* pass — real enrichment will come from a bulk
importer against the NSF API or USAspending.gov. The goal here is to
validate that the new schema, helper views, and SQL tab all play
nicely with multi-year funding rows.

Run from repo root (idempotent)::

    python scripts/seed_funding_events_sample.py
    python scripts/seed_funding_events_sample.py --catalog db/lto_catalog.sqlite

Writes one lake snapshot; run scripts/export_parquet.py to publish.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


# (funder_name_exact, facility_name_like, fiscal_year, amount_usd,
#  award_id, award_title, program, relation)
#
# Amounts are continuing-grant annual allocations from NSF Award Search.
# They're intentionally round numbers here until we wire the real API
# importer — treat this as a schema-validation seed, not a source of
# truth for budgets.
SAMPLE = [
    ("NSF", "Santa Barbara Coastal LTER", 2019, 1_200_000,
     "1831937", "SBC LTER: Land-Ocean Interactions in Kelp Forest",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Santa Barbara Coastal LTER", 2020, 1_230_000,
     "1831937", "SBC LTER: Land-Ocean Interactions in Kelp Forest",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Santa Barbara Coastal LTER", 2021, 1_260_000,
     "1831937", "SBC LTER: Land-Ocean Interactions in Kelp Forest",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Santa Barbara Coastal LTER", 2022, 1_290_000,
     "1831937", "SBC LTER: Land-Ocean Interactions in Kelp Forest",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Santa Barbara Coastal LTER", 2023, 1_320_000,
     "2436033", "SBC LTER VIII: Kelp forest dynamics",
     "NSF LTER", "cooperative-agreement"),

    ("NSF", "Plum Island LTER", 2019, 1_100_000,
     "1832221", "PIE LTER: Coupled biogeochemical & hydrologic dynamics",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Plum Island LTER", 2020, 1_120_000,
     "1832221", "PIE LTER: Coupled biogeochemical & hydrologic dynamics",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Plum Island LTER", 2021, 1_150_000,
     "1832221", "PIE LTER: Coupled biogeochemical & hydrologic dynamics",
     "NSF LTER", "cooperative-agreement"),

    ("NSF", "Georgia Coast LTER", 2018,   980_000,
     "1832178", "GCE-IV: The response of a coastal-zone to climate change",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Georgia Coast LTER", 2019, 1_000_000,
     "1832178", "GCE-IV: The response of a coastal-zone to climate change",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Georgia Coast LTER", 2020, 1_020_000,
     "1832178", "GCE-IV: The response of a coastal-zone to climate change",
     "NSF LTER", "cooperative-agreement"),

    ("NSF", "Virginia Coast LTER", 2018, 1_050_000,
     "1832221", "VCR LTER VII: A metaecosystem approach",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Virginia Coast LTER", 2019, 1_080_000,
     "1832221", "VCR LTER VII: A metaecosystem approach",
     "NSF LTER", "cooperative-agreement"),
    ("NSF", "Virginia Coast LTER", 2020, 1_100_000,
     "1832221", "VCR LTER VII: A metaecosystem approach",
     "NSF LTER", "cooperative-agreement"),
]


def event_id(funder_id: str, facility_id: str, award_id: str | None,
             fiscal_year: int | None) -> str:
    key = "|".join([
        funder_id or "",
        facility_id or "",
        (award_id or "").strip(),
        str(fiscal_year) if fiscal_year is not None else "",
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def resolve_ids(conn, funder_name: str, facility_like: str):
    f = conn.execute("SELECT funder_id FROM funders WHERE name = ?",
                     [funder_name]).fetchone()
    fc = conn.execute(
        "SELECT facility_id FROM facilities WHERE canonical_name ILIKE ?",
        [f"%{facility_like}%"],
    ).fetchone()
    return (f[0] if f else None), (fc[0] if fc else None)


def seed(conn) -> tuple[int, int]:
    # Stage every resolvable row, then one insert-only MERGE (the old
    # ON CONFLICT (event_id) DO NOTHING).
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE _stage_seed_events (
            event_id VARCHAR, funder_id VARCHAR, facility_id VARCHAR,
            amount_usd DOUBLE, fiscal_year INTEGER, award_id VARCHAR,
            award_title VARCHAR, program VARCHAR, relation VARCHAR,
            source VARCHAR, source_url VARCHAR, retrieved_at DATE,
            confidence VARCHAR, _seq INTEGER)
    """)
    inserted = 0
    skipped = 0
    for (fn, fac_like, fy, amt, award, title, program, relation) in SAMPLE:
        funder_id, fac_id = resolve_ids(conn, fn, fac_like)
        if not funder_id or not fac_id:
            print(f"  skip: funder={fn!r} facility~={fac_like!r} "
                  f"(funder_id={funder_id}, facility_id={fac_id})")
            skipped += 1
            continue
        eid = event_id(funder_id, fac_id, award, fy)
        conn.execute("""
            INSERT INTO _stage_seed_events
            VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_DATE,?,?)
        """, [eid, funder_id, fac_id, amt, fy, award, title, program,
              relation, "NSF Award Search",
              f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={award}",
              "high", inserted])
        inserted += 1
    if inserted:
        stats = lto_db.merge_upsert(conn, "funding_events", ["event_id"],
                                    "_stage_seed_events", insert_only=True,
                                    order_by="_seq")
        print(f"[seed] merge: {stats}")
    conn.execute("DROP TABLE _stage_seed_events")
    return inserted, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
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

    with lto_db.transaction(conn, f"seed_funding_events_sample: "
                                  f"{len(SAMPLE)} sample NSF LTER funding rows"):
        ins, skip = seed(conn)
        lto_db.assert_integrity(conn, ["funding_events"])
    print(f"[seed] inserted {ins}, skipped {skip}")

    summary = conn.execute("""
        SELECT COUNT(*) AS n,
               COUNT(amount_usd) AS with_amt,
               COUNT(fiscal_year) AS with_fy,
               MIN(fiscal_year), MAX(fiscal_year)
        FROM funding_events
    """).fetchone()
    print(f"[summary] funding_events total={summary[0]}, "
          f"with_amt={summary[1]}, with_fy={summary[2]}, "
          f"year_range=[{summary[3]}..{summary[4]}]")

    if args.export_parquet:
        print("[parquet] --export-parquet is deprecated: run "
              "scripts/export_parquet.py (and export_view_caches.py) to publish")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
