#!/usr/bin/env python3
"""Compact the DuckLake store of record and prune its old history.

Every write to the lake leaves something behind. Small writes are
"inlined" into the SQLite catalog; larger ones add parquet files, and
updates/deletes add delete files on top of them; every committed
transaction adds a snapshot. None of that is reclaimed on its own. This
script runs DuckLake's maintenance calls in the order that makes each one
useful to the next:

  1. ``ducklake_flush_inlined_data``   inlined rows → parquet data files
  2. ``ducklake_merge_adjacent_files`` many small files → fewer large ones
  3. ``ducklake_rewrite_data_files``   fold delete files back into data
                                       files (threshold: --delete-threshold)
  4. ``ducklake_expire_snapshots``     forget snapshots older than
                                       --older-than-days (default 90)
  5. ``ducklake_cleanup_old_files``    delete the files that no remaining
                                       snapshot references

Steps 1–3 change the physical layout only; table contents at the newest
snapshot are identical before and after (checked: a per-table row count
and an order-independent content hash are compared, and a mismatch exits
non-zero). Step 4 is the only one that loses anything — time travel
(``AT (VERSION => n)``, ``ducklake_table_changes``) to an expired snapshot
stops working. 90 days keeps a season of loader history; the lake itself
is rebuildable from public/parquet at any time, so nothing here is the
last copy of the data.

Run it before export_parquet.py in a long-lived checkout, or whenever
``db/lake/`` has grown a lot of small files::

    python scripts/lake_maintenance.py
    python scripts/lake_maintenance.py --older-than-days 30
    python scripts/lake_maintenance.py --dry-run          # report only
    python scripts/lake_maintenance.py --catalog /tmp/x/cat.sqlite

Do not run it while another process is writing to the same lake.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

L = lto_db.LAKE


def disk_usage(data: Path) -> tuple[int, int]:
    files = [p for p in data.rglob("*") if p.is_file()] if data.exists() else []
    return len(files), sum(p.stat().st_size for p in files)


def fingerprint(con) -> dict[str, tuple[int, int]]:
    """table -> (rows, order-independent content hash) at the newest snapshot.

    Reads every column (``count(*)`` alone is answered from catalog
    statistics and would not notice a missing data file).
    """
    out = {}
    for t in lto_db.lake_tables(con):
        q = lto_db.qident(t)
        out[t] = tuple(lto_db.rows(
            con, f"SELECT count(*), coalesce(bit_xor(hash(t)), 0) FROM {q} AS t")[0])
    return out


def state(con, data: Path) -> str:
    snaps = lto_db.scalar(con, f"SELECT count(*) FROM {L}.snapshots()")
    n, size = disk_usage(data)
    return f"{snaps} snapshots, {n} files on disk, {size / 1e6:.1f} MB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--older-than-days", type=int, default=90,
                    help="expire snapshots older than this many days (default 90)")
    ap.add_argument("--delete-threshold", type=float, default=0.0,
                    help="rewrite a data file once this fraction of its rows is "
                         "deleted (default 0.0: fold every delete file)")
    ap.add_argument("--no-expire", action="store_true",
                    help="compact only; keep all snapshots and old files")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be expired/cleaned; change nothing")
    args = ap.parse_args()
    if args.older_than_days < 0:
        ap.error("--older-than-days must be >= 0")

    data = lto_db.data_path(args.catalog, args.lake_data)
    con = lto_db.connect(read_only=args.dry_run, catalog=args.catalog,
                         data=args.lake_data)
    cutoff = f"now() - INTERVAL {int(args.older_than_days)} DAY"
    print(f"[before] {state(con, data)}")

    if args.dry_run:
        expire = lto_db.rows(
            con, f"SELECT snapshot_id FROM {L}.snapshots() "
                 f"WHERE snapshot_time < {cutoff} AND snapshot_id < "
                 f"(SELECT max(snapshot_id) FROM {L}.snapshots()) ORDER BY 1")
        print(f"[dry-run] would expire {len(expire)} snapshot(s) older than "
              f"{args.older_than_days} days"
              + (f": {[r[0] for r in expire][:10]}{' …' if len(expire) > 10 else ''}"
                 if expire else ""))
        print(f"[dry-run] would flush inlined data, merge adjacent files, rewrite "
              f"files with deletes (threshold {args.delete_threshold})")
        con.close()
        return 0

    before = fingerprint(con)
    steps = [
        ("flush inlined data", f"CALL ducklake_flush_inlined_data('{L}')"),
        ("merge adjacent files", f"CALL ducklake_merge_adjacent_files('{L}')"),
        ("rewrite data files",
         f"CALL ducklake_rewrite_data_files('{L}', "
         f"delete_threshold => {float(args.delete_threshold)})"),
    ]
    if not args.no_expire:
        steps += [
            (f"expire snapshots older than {args.older_than_days} days",
             f"CALL ducklake_expire_snapshots('{L}', older_than => {cutoff})"),
            ("clean up unreferenced files",
             f"CALL ducklake_cleanup_old_files('{L}', cleanup_all => true)"),
        ]
    for i, (label, sql) in enumerate(steps):
        if i < 3:
            # The compaction steps each write a snapshot; give it an author
            # and a commit message like every other lake write. (Expire and
            # cleanup write no snapshot.) A step with nothing to do commits
            # nothing.
            with lto_db.transaction(con, f"lake_maintenance: {label}"):
                r = lto_db.rows(con, sql)
        else:
            r = lto_db.rows(con, sql)
        print(f"[step] {label}: {len(r)} item(s)")

    after = fingerprint(con)
    print(f"[after]  {state(con, data)}")
    con.close()
    changed = sorted(t for t in before.keys() | after.keys()
                     if before.get(t) != after.get(t))
    if changed:
        print(f"[error] table contents changed during maintenance: {changed}",
              file=sys.stderr)
        return 1
    print(f"[ok] {len(after)} tables unchanged in content")
    return 0


if __name__ == "__main__":
    sys.exit(main())
