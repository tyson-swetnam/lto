#!/usr/bin/env python3
"""Self-evaluate LTO database coverage against agents/WORLD_MODEL.md.

Writes `agents/PROGRESS.md` — a structured gap report:
  * overall coverage percentages per checklist item
  * per-sphere coverage breakdown
  * per-facility row showing which checklist items are still empty
  * "next-loop targets" — the worst-covered facility cluster

Run idempotently after every wave / loop:

    python scripts/eval_progress.py
    python scripts/eval_progress.py --db db/cod_kmap.duckdb

The output file is git-tracked so future Claude sessions can read it
on startup and pick up where the previous loop left off.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
OUT = ROOT / "agents" / "PROGRESS.md"


CHECKLIST = [
    # (column-name in the materialized view, label, weight in score)
    ("has_funding",        "Funding lineage",        1),
    ("has_funding_amount", "Funding amount(s)",      2),
    ("has_personnel",      "≥1 PI / director",       1),
    ("has_publications",   "≥1 publication credit",  2),
    ("has_archive",        "Linked data archive",    3),
    ("has_data_product",   "≥1 catalogued dataset",  3),
    ("has_endpoint",       "API endpoint",           2),
    ("has_bucket",         "Cloud bucket",           1),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()

    with duckdb.connect(str(args.db), read_only=True) as conn:
        # Materialize the per-facility coverage matrix.
        coverage = conn.execute("""
            WITH base AS (
                SELECT f.facility_id, f.canonical_name, f.acronym,
                       fs.sphere_slug AS sphere,
                       (SELECT count(*) FROM funding_events fe
                          WHERE fe.facility_id = f.facility_id) AS n_funding,
                       (SELECT count(*) FROM funding_events fe
                          WHERE fe.facility_id = f.facility_id
                            AND fe.amount_usd IS NOT NULL) AS n_funding_amount,
                       (SELECT count(*) FROM facility_personnel fp
                          WHERE fp.facility_id = f.facility_id) AS n_personnel,
                       (SELECT count(DISTINCT a.publication_id)
                        FROM authorship a
                        JOIN facility_personnel fp ON fp.person_id = a.person_id
                        WHERE fp.facility_id = f.facility_id) AS n_pubs
                FROM facilities f
                LEFT JOIN facility_spheres fs
                  ON fs.facility_id = f.facility_id AND fs.role = 'primary'
            ),
            arch AS (
                SELECT facility_id, count(*) AS n_archives
                FROM facility_archives GROUP BY facility_id
            ),
            prod AS (
                SELECT facility_id, count(*) AS n_products
                FROM data_products GROUP BY facility_id
            ),
            endp AS (
                SELECT facility_id, count(*) AS n_endpoints
                FROM api_endpoints GROUP BY facility_id
            ),
            buck AS (
                SELECT facility_id, count(*) AS n_buckets
                FROM cloud_buckets GROUP BY facility_id
            )
            SELECT b.facility_id, b.canonical_name, b.acronym, b.sphere,
                   b.n_funding > 0           AS has_funding,
                   b.n_funding_amount > 0    AS has_funding_amount,
                   b.n_personnel > 0         AS has_personnel,
                   b.n_pubs > 0              AS has_publications,
                   coalesce(a.n_archives, 0) > 0   AS has_archive,
                   coalesce(p.n_products, 0) > 0   AS has_data_product,
                   coalesce(e.n_endpoints, 0) > 0  AS has_endpoint,
                   coalesce(bu.n_buckets, 0) > 0   AS has_bucket
            FROM base b
            LEFT JOIN arch a  ON a.facility_id = b.facility_id
            LEFT JOIN prod p  ON p.facility_id = b.facility_id
            LEFT JOIN endp e  ON e.facility_id = b.facility_id
            LEFT JOIN buck bu ON bu.facility_id = b.facility_id
        """).fetchall()

        n_total = len(coverage)
        cols = [c[0] for c in CHECKLIST]
        idx_map = {
            "has_funding": 4, "has_funding_amount": 5, "has_personnel": 6,
            "has_publications": 7, "has_archive": 8, "has_data_product": 9,
            "has_endpoint": 10, "has_bucket": 11,
        }
        sums = {c: sum(1 for r in coverage if r[idx_map[c]]) for c in cols}

        # Per-sphere
        spheres = sorted({r[3] or "(unassigned)" for r in coverage})
        per_sphere = {}
        for s in spheres:
            rows = [r for r in coverage if (r[3] or "(unassigned)") == s]
            per_sphere[s] = {
                "n": len(rows),
                **{c: sum(1 for r in rows if r[idx_map[c]]) for c in cols},
            }

        # Per-facility score (weighted)
        weights = {c: w for (c, _, w) in CHECKLIST}
        scored = []
        for r in coverage:
            score = sum(weights[c] for c in cols if r[idx_map[c]])
            scored.append((score, r))
        scored.sort(key=lambda x: (x[0], (x[1][3] or "")))

        # Emit markdown
        lines = []
        lines.append(f"# LTO Progress Report")
        lines.append("")
        lines.append(f"_Generated by `scripts/eval_progress.py` at "
                     f"{datetime.utcnow().isoformat(timespec='seconds')}Z._")
        lines.append("")
        lines.append("> Read at the start of every session. The "
                     "[WORLD_MODEL.md](./WORLD_MODEL.md) defines what a "
                     "\"complete\" record looks like; this file shows how "
                     "close we are.")
        lines.append("")
        lines.append(f"## Headline coverage ({n_total} facilities total)")
        lines.append("")
        lines.append("| Checklist item | Covered | % |")
        lines.append("|---|---:|---:|")
        for col, label, _w in CHECKLIST:
            covered = sums[col]
            pct = 100.0 * covered / n_total if n_total else 0
            lines.append(f"| {label} | {covered} / {n_total} | {pct:.1f}% |")
        lines.append("")

        lines.append("## Per-sphere coverage")
        lines.append("")
        lines.append("| Sphere | n | " + " | ".join(label for _c, label, _ in CHECKLIST) + " |")
        lines.append("|---|---:|" + "|".join(":---:" for _ in CHECKLIST) + "|")
        for s in spheres:
            row = per_sphere[s]
            cells = []
            for col, _label, _w in CHECKLIST:
                cells.append(f"{row[col]} / {row['n']}")
            lines.append(f"| {s} | {row['n']} | " + " | ".join(cells) + " |")
        lines.append("")

        lines.append("## Worst-covered facilities (top 30)")
        lines.append("")
        lines.append("Facilities sorted by the weighted-coverage score (low → high). "
                     "Target these in the next loop.")
        lines.append("")
        lines.append("| Score | Sphere | Facility | Acronym | Missing |")
        lines.append("|---:|---|---|---|---|")
        for score, r in scored[:30]:
            missing = [label for col, label, _w in CHECKLIST if not r[idx_map[col]]]
            lines.append(
                f"| {score} | {r[3] or '?'} | {r[1]} | {r[2] or '—'} | "
                f"{', '.join(missing) if missing else '✓ complete'} |"
            )
        lines.append("")

        # Suggest next-loop targets — facilities with missing data archive
        # are the highest priority for Wave J.
        no_archive = [r for r in coverage if not r[idx_map['has_archive']]]
        no_archive.sort(key=lambda r: (r[3] or "", r[1]))
        lines.append(f"## Next-loop targets — facilities missing a data archive ({len(no_archive)})")
        lines.append("")
        lines.append("These are the priority for the next J-A research loop. "
                     "Group by sphere and fan out:")
        lines.append("")
        # Group + count by sphere.
        from collections import Counter
        by_sphere = Counter((r[3] or '?') for r in no_archive)
        lines.append("| Sphere | Facilities missing data archive |")
        lines.append("|---|---:|")
        for s, n in sorted(by_sphere.items(), key=lambda x: -x[1]):
            lines.append(f"| {s} | {n} |")
        lines.append("")

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text("\n".join(lines) + "\n")
        print(f"[eval_progress] wrote {OUT} ({len(coverage)} facilities, "
              f"{sum(sums.values())} checklist hits across "
              f"{len(CHECKLIST)} items)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
