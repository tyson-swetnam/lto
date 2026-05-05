#!/usr/bin/env python3
"""Compute primary research area per facility and per person.

For the Map (MVG) view we need each facility/person to live in exactly
one polygon. Algorithm (per facility):

  1. Weighted vote across two sources:
       direct area_links               → weight 2.0 per (facility, area)
       personnel-mediated person_areas → weight (pa.weight × pa.evidence_count)
  2. Pick area_id with the highest summed score (ties broken by area_id
     lexicographic order so the result is deterministic).
  3. Collapse: any area whose primary-count is below `--min-facilities`
     (default 3) is folded into its `research_areas.parent_id` if one
     exists. Iterate until stable. Top-level areas with low counts stay
     as their own polygon (they have nowhere to fold into).

Per-person primary area is derived directly from the highest-weight
person_areas row when one exists; falls back to the primary area of
the person's primary facility (via facility_personnel) otherwise.

Output:
  db/parquet/facility_primary_groups.parquet
    facility_id, primary_area_id, primary_area_label, score
  db/parquet/person_primary_groups.parquet
    person_id, primary_area_id, primary_area_label, score, source
  db/parquet/research_areas_active.parquet
    area_id, label, parent_id, n_facilities, collapsed_into
  Public copies in public/parquet/ for the web app.

Idempotent — overwrites the parquets on every run.

Usage::
    python scripts/compute_primary_groups.py
    python scripts/compute_primary_groups.py --min-facilities 5
    python scripts/compute_primary_groups.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]


def compute_facility_primaries(conn) -> list[tuple]:
    """Returns [(facility_id, area_id, score), ...].
    One row per facility (the winning area). Includes facilities with
    no area linkage at all — they get NULL area_id."""
    rows = conn.execute("""
        WITH facility_area_score AS (
            -- direct area_links
            SELECT al.facility_id, al.area_id, 2.0 AS score
            FROM   area_links al
            UNION ALL
            -- personnel-mediated, weighted by topic confidence × evidence
            SELECT fp.facility_id, pa.area_id,
                   pa.weight * GREATEST(pa.evidence_count, 1) AS score
            FROM   facility_personnel fp
            JOIN   person_areas       pa ON pa.person_id = fp.person_id
        ),
        summed AS (
            SELECT facility_id, area_id, SUM(score) AS total
            FROM   facility_area_score
            GROUP  BY facility_id, area_id
        ),
        ranked AS (
            SELECT facility_id, area_id, total,
                   ROW_NUMBER() OVER (
                       PARTITION BY facility_id
                       ORDER BY total DESC, area_id ASC
                   ) AS rk
            FROM summed
        )
        SELECT f.facility_id,
               r.area_id,
               COALESCE(r.total, 0.0) AS score
        FROM   facilities f
        LEFT JOIN ranked r ON r.facility_id = f.facility_id AND r.rk = 1
    """).fetchall()
    return rows


def compute_person_primaries(conn, facility_primary: dict[str, str]) -> list[tuple]:
    """Returns [(person_id, area_id, score, source), ...]."""
    # Direct person_areas winner.
    rows = conn.execute("""
        WITH ranked AS (
            SELECT person_id, area_id,
                   weight * GREATEST(evidence_count, 1) AS score,
                   ROW_NUMBER() OVER (
                       PARTITION BY person_id
                       ORDER BY weight DESC,
                                evidence_count DESC,
                                area_id ASC
                   ) AS rk
            FROM   person_areas
        )
        SELECT p.person_id, r.area_id,
               COALESCE(r.score, 0.0) AS score
        FROM   people p
        LEFT JOIN ranked r ON r.person_id = p.person_id AND r.rk = 1
    """).fetchall()

    # Fall back to facility's primary for people without person_areas.
    fp_map = dict(conn.execute("""
        SELECT person_id, MIN(facility_id) AS facility_id
        FROM   facility_personnel
        GROUP  BY person_id
    """).fetchall())

    out: list[tuple] = []
    for person_id, area_id, score in rows:
        if area_id:
            out.append((person_id, area_id, float(score), "person_areas"))
            continue
        fid = fp_map.get(person_id)
        if fid and facility_primary.get(fid):
            out.append((person_id, facility_primary[fid], 0.0, "facility-fallback"))
        else:
            out.append((person_id, None, 0.0, "none"))
    return out


def collapse_areas(conn, primaries: list[tuple], min_facilities: int) -> tuple[
    list[tuple], dict[str, str | None]]:
    """Iteratively fold low-count areas into their parent. Returns
    (updated_primaries, collapse_map) where collapse_map[orig_area]
    = final_area (or None if it survived)."""
    parents = dict(conn.execute(
        "SELECT area_id, parent_id FROM research_areas"
    ).fetchall())

    # Counts per area_id from current primaries.
    def _count(plist):
        c: dict[str, int] = {}
        for _, area, _ in plist:
            if area:
                c[area] = c.get(area, 0) + 1
        return c

    collapse_map: dict[str, str] = {}
    cur = list(primaries)
    while True:
        counts = _count(cur)
        # Find the smallest below-threshold area that has a non-null
        # parent we can fold into (and the parent isn't itself collapsed).
        candidates = [
            (a, n) for a, n in counts.items()
            if n < min_facilities
            and parents.get(a) is not None
            and parents[a] not in collapse_map
        ]
        if not candidates:
            break
        # Smallest first — iterate one at a time so the parent's count
        # absorbs each child before we look again.
        candidates.sort(key=lambda x: (x[1], x[0]))
        victim, _ = candidates[0]
        target = parents[victim]
        # Follow any collapse-chain in target to its terminal area.
        seen = set()
        while target in collapse_map and target not in seen:
            seen.add(target)
            target = collapse_map[target]
        collapse_map[victim] = target
        # Apply: every primary at `victim` becomes `target`.
        cur = [
            (fid, target if a == victim else a, s)
            for (fid, a, s) in cur
        ]
    return cur, collapse_map


def export_parquet(conn, facility_rows, person_rows, area_rows, dry: bool):
    if dry:
        print("[dry-run] would write parquet files; skipping")
        return
    # Use temp tables so we can export with a single COPY each.
    conn.execute("DROP TABLE IF EXISTS _facility_primary_tmp")
    conn.execute("""
        CREATE TEMP TABLE _facility_primary_tmp (
            facility_id        VARCHAR,
            primary_area_id    VARCHAR,
            primary_area_label VARCHAR,
            score              DOUBLE
        )
    """)
    conn.executemany(
        "INSERT INTO _facility_primary_tmp VALUES (?, ?, ?, ?)",
        facility_rows,
    )
    conn.execute("DROP TABLE IF EXISTS _person_primary_tmp")
    conn.execute("""
        CREATE TEMP TABLE _person_primary_tmp (
            person_id          VARCHAR,
            primary_area_id    VARCHAR,
            primary_area_label VARCHAR,
            score              DOUBLE,
            source             VARCHAR
        )
    """)
    conn.executemany(
        "INSERT INTO _person_primary_tmp VALUES (?, ?, ?, ?, ?)",
        person_rows,
    )
    conn.execute("DROP TABLE IF EXISTS _research_areas_active_tmp")
    conn.execute("""
        CREATE TEMP TABLE _research_areas_active_tmp (
            area_id        VARCHAR,
            label          VARCHAR,
            parent_id      VARCHAR,
            n_facilities   INTEGER,
            collapsed_into VARCHAR
        )
    """)
    conn.executemany(
        "INSERT INTO _research_areas_active_tmp VALUES (?, ?, ?, ?, ?)",
        area_rows,
    )

    for base in PARQUET_OUT:
        base.mkdir(parents=True, exist_ok=True)
        for tmp, name in [
            ("_facility_primary_tmp",       "facility_primary_groups"),
            ("_person_primary_tmp",         "person_primary_groups"),
            ("_research_areas_active_tmp",  "research_areas_active"),
        ]:
            out = base / f"{name}.parquet"
            conn.execute(
                f"COPY {tmp} TO '{out}' (FORMAT PARQUET)"
            )
            print(f"[parquet] wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--min-facilities", type=int, default=3,
                    help="Areas with fewer than this many primary "
                         "facilities are folded into their parent. "
                         "Top-level areas (no parent) are exempt.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2
    conn = duckdb.connect(str(args.db))

    # 1. Facility primaries (uncollapsed).
    raw_fp = compute_facility_primaries(conn)
    print(f"[facilities] primary winners computed: "
          f"{sum(1 for r in raw_fp if r[1])}/{len(raw_fp)} have an area")

    # 2. Iterative parent-collapse.
    fp_collapsed, collapse_map = collapse_areas(
        conn, raw_fp, args.min_facilities,
    )
    print(f"[collapse] {len(collapse_map)} areas folded into parents:")
    for src, tgt in sorted(collapse_map.items()):
        print(f"  {src:35s} → {tgt}")

    # Build final facility output rows with labels.
    labels = dict(conn.execute(
        "SELECT area_id, label FROM research_areas"
    ).fetchall())
    facility_rows = [
        (fid, area, labels.get(area), score)
        for (fid, area, score) in fp_collapsed
    ]

    # 3. Person primaries → apply same collapse map.
    facility_primary_dict = {fid: area for fid, area, _ in fp_collapsed if area}
    raw_pp = compute_person_primaries(conn, facility_primary_dict)
    person_rows = [
        (pid, collapse_map.get(area, area) if area else None,
         labels.get(collapse_map.get(area, area)) if area else None,
         score, src)
        for (pid, area, score, src) in raw_pp
    ]

    # 4. Active areas (post-collapse) with counts.
    active_counts: dict[str, int] = {}
    for _, a, _ in fp_collapsed:
        if a:
            active_counts[a] = active_counts.get(a, 0) + 1
    parents = dict(conn.execute(
        "SELECT area_id, parent_id FROM research_areas"
    ).fetchall())
    area_rows = []
    for area_id, label in labels.items():
        if area_id in collapse_map:
            target = collapse_map[area_id]
            area_rows.append((area_id, label, parents.get(area_id), 0, target))
        else:
            area_rows.append((
                area_id, label, parents.get(area_id),
                active_counts.get(area_id, 0), None,
            ))

    print(f"[areas] active polygon count: "
          f"{sum(1 for r in area_rows if r[4] is None)}")
    print(f"[summary] facilities={len(facility_rows)}  "
          f"people={len(person_rows)}  active_areas="
          f"{sum(1 for r in area_rows if r[4] is None)}")

    # Top areas after collapse:
    print("\n[top-active] areas by primary facility count:")
    sorted_active = sorted(
        [(a, n) for a, l, p, n, c in area_rows if c is None],
        key=lambda x: -x[1],
    )
    for area, n in sorted_active[:15]:
        print(f"  {n:4d}  {labels.get(area, '?'):40s}  ({area})")

    export_parquet(conn, facility_rows, person_rows, area_rows, args.dry_run)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
