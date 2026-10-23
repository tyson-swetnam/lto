#!/usr/bin/env python3
"""Rank the registry and split it into a shipped core tier and a local archive.

The browser loads parquet directly into DuckDB-Wasm, so the site cannot
serve the whole harvested population — upstream cod-kmap saw 190k authors
match its topic filter, and the LTO topic set harvests at the same order
of magnitude. This script scores every registry row and promotes the top
``--core-size`` to ``tier='core'``; only that tier is exported to
public/parquet (by scripts/export_parquet.py, which filters on tier). The
full population stays in the lake (db/lto_catalog.sqlite + db/lake/) for
analysis.

Scoring
-------
Four components, each converted to a percentile within the scored
population. Percentiles rather than raw values because the components have
incomparable ranges — cited_by_count runs to six figures while
lto_share is bounded at 1.0 — so a raw-weighted sum would be decided
almost entirely by the citation term.

  lto_output       lto_works_count           — how much work on the LTO topic set
  impact           h_index                   — how well cited
  recency          two_yr_mean_citedness     — recent citation rate
  connectivity     registry co-author degree — embedded in the community

Note on `recency`: two_yr_mean_citedness is OpenAlex's 2-year mean
citedness, i.e. how heavily the author's recent work is being cited. It is
a recency-weighted *impact* measure, not a measure of recent output
volume. A recent-output rate would be the better signal here — the harvest
already computes one from counts_by_year — but person_registry has no
column for it yet, so this is the best proxy the stored schema supports.
Adding a recent_works column and switching this term is the obvious next
refinement.

Weights are a parameter, not a constant, because "most important" is an
editorial judgement the project owns. The defaults weight LTO output
and impact equally and treat recency and connectivity as tiebreakers.

Anyone staffing a catalogued facility (is_site_personnel) is pinned into
the core tier regardless of score. They are the roster the site exists to
show, and a metric threshold must never drop them.

Usage::

    python scripts/rank_person_registry.py --core-size 10000
    python scripts/rank_person_registry.py --dry-run

A real run writes tier/tier_rank/tier_score in one lake snapshot; then run
scripts/export_parquet.py. --export-parquet is accepted for old callers and
does nothing.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

DEFAULT_WEIGHTS = dict(lto_output=0.35, impact=0.35,
                       recency=0.15, connectivity=0.15)


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--core-size", type=int, default=10000)
    ap.add_argument("--w-lto", type=float, default=DEFAULT_WEIGHTS["lto_output"])
    ap.add_argument("--w-impact", type=float, default=DEFAULT_WEIGHTS["impact"])
    ap.add_argument("--w-recency", type=float, default=DEFAULT_WEIGHTS["recency"])
    ap.add_argument("--w-connectivity", type=float,
                    default=DEFAULT_WEIGHTS["connectivity"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-parquet", action="store_true",
                    help="deprecated no-op: run scripts/export_parquet.py")
    args = ap.parse_args()

    conn = lto_db.connect(read_only=args.dry_run,
                          catalog=args.catalog, data=args.lake_data)
    total = conn.execute("SELECT COUNT(*) FROM person_registry").fetchone()[0]
    print(f"[rank] scoring {total:,} registry row(s)")

    # Degree within the co-authorship graph, as a scoring input.
    conn.execute("""
        CREATE OR REPLACE TEMP VIEW _degree AS
        SELECT canonical_id, COUNT(*) AS deg FROM (
            SELECT canonical_id_a AS canonical_id FROM registry_collaborations
            UNION ALL
            SELECT canonical_id_b FROM registry_collaborations)
        GROUP BY canonical_id""")

    # PERCENT_RANK puts every component on [0,1] regardless of native
    # units. COALESCE to 0 first so a null metric scores at the floor
    # rather than dropping the row from the window.
    conn.execute(f"""
        CREATE OR REPLACE TEMP VIEW _scored AS
        SELECT r.canonical_id,
               r.is_site_personnel                                 AS pinned,
               PERCENT_RANK() OVER (ORDER BY COALESCE(r.lto_works_count,0))     AS p_lto,
               PERCENT_RANK() OVER (ORDER BY COALESCE(r.h_index,0))             AS p_impact,
               PERCENT_RANK() OVER (ORDER BY COALESCE(r.two_yr_mean_citedness,0))AS p_recency,
               PERCENT_RANK() OVER (ORDER BY COALESCE(d.deg,0))                 AS p_conn
        FROM person_registry r
        LEFT JOIN _degree d USING (canonical_id)""")

    conn.execute(f"""
        CREATE OR REPLACE TEMP VIEW _final AS
        SELECT canonical_id, pinned,
               {args.w_lto} * p_lto + {args.w_impact} * p_impact
             + {args.w_recency} * p_recency + {args.w_connectivity} * p_conn AS score
        FROM _scored""")

    ranked = conn.execute("""
        SELECT canonical_id, pinned, score,
               ROW_NUMBER() OVER (ORDER BY pinned DESC, score DESC) AS rk
        FROM _final ORDER BY rk""").fetchall()

    n_pinned = sum(1 for _, p, _, _ in ranked if p)
    core_size = max(args.core_size, n_pinned)
    if core_size > args.core_size:
        print(f"[rank] {n_pinned:,} pinned row(s) exceed --core-size "
              f"{args.core_size:,}; core widened to {core_size:,} so no "
              f"site-personnel row is dropped")

    updates = [("core" if rk <= core_size else "archive", rk, sc, cid)
               for cid, _, sc, rk in ranked]
    n_core = sum(1 for t, *_ in updates if t == "core")
    print(f"[rank] core={n_core:,} ({n_pinned:,} pinned) archive={total - n_core:,}")

    if args.dry_run:
        top = conn.execute("""
            SELECT r.display_name, r.h_index, r.lto_works_count, f.score
            FROM _final f JOIN person_registry r USING (canonical_id)
            WHERE NOT f.pinned ORDER BY f.score DESC LIMIT 8""").fetchall()
        print("[rank] top unpinned by score:")
        for name, h, lw, sc in top:
            print(f"    {sc:.3f}  h={h:<4} lto={lw:<5} {name}")
        conn.close()
        return 0

    # One set-based UPDATE from a staged table: a per-row UPDATE against
    # the lake is far slower at harvest scale (100k+ rows).
    conn.execute("CREATE OR REPLACE TEMP TABLE _tier_stage "
                 "(tier VARCHAR, tier_rank INTEGER, tier_score DOUBLE, "
                 "canonical_id VARCHAR)")
    conn.executemany("INSERT INTO _tier_stage VALUES (?, ?, ?, ?)", updates)
    with lto_db.transaction(conn, f"rank_person_registry: core={n_core} "
                                  f"archive={total - n_core} (core_size={core_size})"):
        conn.execute("""
            UPDATE person_registry
            SET tier = s.tier, tier_rank = s.tier_rank, tier_score = s.tier_score
            FROM _tier_stage s
            WHERE person_registry.canonical_id = s.canonical_id""")
        lto_db.assert_integrity(conn, ["person_registry"])

    # Shipping is export_parquet.py's job: it exports tier='core' only, and
    # keeps registry_collaborations / registry_facilities / coauthor_edges
    # rows only when both endpoints ship (EXPORT_WHERE), or the browser
    # would hold edges pointing at absent nodes — which qa.py's orphan-edge
    # invariant would (correctly) fail on a site rebuild.
    print("[rank] tiers written to the lake (run export_parquet.py to publish)")
    if args.export_parquet:
        print("[note] --export-parquet is a no-op now; run "
              "scripts/export_parquet.py to publish the lake")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
