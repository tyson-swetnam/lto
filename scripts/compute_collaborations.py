#!/usr/bin/env python3
"""Derive the `collaborations` table from `authorship` co-occurrence.

No network calls — pure SQL over the existing tables. Run after any
enrichment pass that adds authorship rows so the co-authorship edges
stay in sync.

For every pair (A, B) of distinct people who appear together on any
publication::

  co_pub_count = number of shared publications
  first_year   = earliest pub_year across those shared publications
  last_year    = latest pub_year
  strength     = min(co_pub_count / 20, 1.0)   # 0..1, same formula as
                                                 the unm_kmap kmap.html
                                                 edge-strength encoding

Rows are stored with person_a_id < person_b_id so each pair has one
canonical entry.

Usage::

    python scripts/compute_collaborations.py
    python scripts/compute_collaborations.py --catalog db/lto_catalog.sqlite
    python scripts/compute_collaborations.py --min-co-pubs 2

The table is rebuilt in the lake in one snapshot; scripts/export_parquet.py
publishes it. --export-parquet is accepted for old callers and does nothing.
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
    ap.add_argument("--min-co-pubs", type=int, default=1,
                    help="Only keep pairs with at least this many shared pubs")
    ap.add_argument("--export-parquet", action="store_true",
                    help="deprecated no-op: run scripts/export_parquet.py")
    args = ap.parse_args()

    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)

    # Self-join authorship on publication_id; keep only a<b so each
    # pair appears once. Join publications for pub_year so we can
    # compute first_year / last_year.
    sql = """
    INSERT INTO collaborations (
        person_a_id, person_b_id, co_pub_count,
        first_year, last_year, strength
    )
    SELECT
        a.person_id                 AS person_a_id,
        b.person_id                 AS person_b_id,
        COUNT(*)                    AS co_pub_count,
        MIN(p.pub_year)             AS first_year,
        MAX(p.pub_year)             AS last_year,
        LEAST(COUNT(*) / 20.0, 1.0) AS strength
    FROM authorship     a
    JOIN authorship     b ON b.publication_id = a.publication_id
                         AND a.person_id < b.person_id
    LEFT JOIN publications p ON p.publication_id = a.publication_id
    GROUP BY a.person_id, b.person_id
    HAVING COUNT(*) >= ?
    """
    # Rebuild from scratch — collaborations is a derived table, so
    # wiping it on every run keeps it trivially correct. It is also a
    # schema.sql table, so DELETE + INSERT (not replace_table) keeps its
    # column definitions. One transaction = one snapshot.
    with lto_db.transaction(conn, f"compute_collaborations: rebuild from "
                                  f"authorship (min_co_pubs={args.min_co_pubs})"):
        conn.execute("DELETE FROM collaborations")
        conn.execute(sql, [args.min_co_pubs])
        lto_db.assert_integrity(conn, ["collaborations"])

    stats = conn.execute("""
        SELECT COUNT(*), MIN(first_year), MAX(last_year),
               MAX(co_pub_count), AVG(co_pub_count)::DECIMAL(10,2)
        FROM collaborations
    """).fetchone()
    print(f"[collaborations] pairs={stats[0]}, "
          f"year_range=[{stats[1]}..{stats[2]}], "
          f"max_shared={stats[3]}, avg_shared={stats[4]}")

    # Top-10 heaviest pairs for sanity.
    print("\n[top 10 collaborations by co_pub_count]")
    for r in conn.execute("""
        SELECT pa.name, pb.name, c.co_pub_count,
               c.first_year, c.last_year
        FROM collaborations c
        JOIN people pa ON pa.person_id = c.person_a_id
        JOIN people pb ON pb.person_id = c.person_b_id
        ORDER BY c.co_pub_count DESC LIMIT 10
    """).fetchall():
        print(f"  {r[0]:<26} <-> {r[1]:<26} "
              f"{r[2]:>3} pubs  [{r[3]}..{r[4]}]")

    if args.export_parquet:
        print("[note] --export-parquet is a no-op now; run "
              "scripts/export_parquet.py to publish the lake")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
