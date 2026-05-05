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
    python scripts/compute_collaborations.py --db db/cod_kmap.duckdb
    python scripts/compute_collaborations.py --min-co-pubs 2
    python scripts/compute_collaborations.py --export-parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--min-co-pubs", type=int, default=1,
                    help="Only keep pairs with at least this many shared pubs")
    ap.add_argument("--export-parquet", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))

    # Rebuild from scratch — collaborations is a derived table, so
    # wiping it on every run keeps it trivially correct.
    conn.execute("DELETE FROM collaborations")

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
    conn.execute(sql, [args.min_co_pubs])

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
        for base in PARQUET_OUT:
            base.mkdir(parents=True, exist_ok=True)
            out = base / "collaborations.parquet"
            conn.execute(f"COPY collaborations TO '{out}' (FORMAT PARQUET)")
            print(f"[parquet] wrote {out}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
