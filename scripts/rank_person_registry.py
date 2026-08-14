#!/usr/bin/env python3
"""Rank the registry and split it into a shipped core tier and a local archive.

The browser loads parquet directly into DuckDB-Wasm, so the site cannot
serve the whole harvested population — upstream cod-kmap saw 190k authors
match its topic filter, and the LTO topic set harvests at the same order
of magnitude. This script scores every registry row and promotes the top
``--core-size`` to ``tier='core'``; only that tier is exported to
public/parquet. The full population stays in db/lto.duckdb (and its
db/parquet mirror) for analysis.

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

    python scripts/rank_person_registry.py --core-size 10000 --export-parquet
    python scripts/rank_person_registry.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
DB_PARQUET = ROOT / "db" / "parquet"
SITE_PARQUET = ROOT / "public" / "parquet"

DEFAULT_WEIGHTS = dict(lto_output=0.35, impact=0.35,
                       recency=0.15, connectivity=0.15)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--core-size", type=int, default=10000)
    ap.add_argument("--w-lto", type=float, default=DEFAULT_WEIGHTS["lto_output"])
    ap.add_argument("--w-impact", type=float, default=DEFAULT_WEIGHTS["impact"])
    ap.add_argument("--w-recency", type=float, default=DEFAULT_WEIGHTS["recency"])
    ap.add_argument("--w-connectivity", type=float,
                    default=DEFAULT_WEIGHTS["connectivity"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-parquet", action="store_true")
    args = ap.parse_args()

    conn = duckdb.connect(str(args.db))
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

    conn.executemany(
        "UPDATE person_registry SET tier = ?, tier_rank = ?, tier_score = ? "
        "WHERE canonical_id = ?", updates)

    if args.export_parquet:
        DB_PARQUET.mkdir(parents=True, exist_ok=True)
        SITE_PARQUET.mkdir(parents=True, exist_ok=True)
        # Full population to db/parquet — the analysis mirror.
        conn.execute(f"COPY person_registry TO "
                     f"'{DB_PARQUET / 'person_registry.parquet'}' (FORMAT PARQUET)")
        conn.execute(f"COPY person_identity_source TO "
                     f"'{DB_PARQUET / 'person_identity_source.parquet'}' (FORMAT PARQUET)")
        conn.execute(f"COPY registry_collaborations TO "
                     f"'{DB_PARQUET / 'registry_collaborations.parquet'}' (FORMAT PARQUET)")
        # Core tier only to public/parquet — this is what the browser loads.
        conn.execute(f"""COPY (SELECT * FROM person_registry WHERE tier = 'core')
                         TO '{SITE_PARQUET / 'person_registry.parquet'}' (FORMAT PARQUET)""")
        conn.execute(f"""COPY (SELECT s.* FROM person_identity_source s
                         JOIN person_registry r USING (canonical_id)
                         WHERE r.tier = 'core')
                         TO '{SITE_PARQUET / 'person_identity_source.parquet'}' (FORMAT PARQUET)""")
        # Edges are kept only when BOTH endpoints ship, or the browser
        # would hold edges pointing at absent nodes — which qa.py's
        # orphan-edge invariant would (correctly) fail on a site rebuild.
        conn.execute(f"""COPY (SELECT c.* FROM registry_collaborations c
                         JOIN person_registry a ON a.canonical_id = c.canonical_id_a
                         JOIN person_registry b ON b.canonical_id = c.canonical_id_b
                         WHERE a.tier = 'core' AND b.tier = 'core')
                         TO '{SITE_PARQUET / 'registry_collaborations.parquet'}' (FORMAT PARQUET)""")
        for p in (SITE_PARQUET / "person_registry.parquet",
                  SITE_PARQUET / "registry_collaborations.parquet"):
            print(f"[parquet] site {p.name}: {p.stat().st_size / 1e6:.1f} MB")
        print("[note] parquet is gitignored; stage with `git add -f`")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
