#!/usr/bin/env python3
"""Apply L-URL-FIX-* agent emissions to people.homepage_url.

Reads every `data/raw/L-URL-FIX-*/homepage_updates.json` array and
runs UPDATE statements against `people`. Idempotent — re-running just
overwrites with the same values.

Strategy:

  1. Match by `person_id` (sha1[:16] hash) when supplied.
  2. Fall back to (lower(name) AND any matching facility_personnel.facility_acronym)
     in case an agent emitted a name-only row.
  3. Skip rows whose `confidence` is `"low"` AND whose
     `homepage_url_kind` is `"facility-home"`, because those are
     no-info-added fallbacks; the existing UI fallback chain in
     src/views/list.js already covers that case.

Usage::

    python scripts/apply_homepage_url_fixes.py
    python scripts/apply_homepage_url_fixes.py --verbose
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
RAW_DIR = ROOT / "data" / "raw"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = sorted(RAW_DIR.glob("L-URL-FIX-*/homepage_updates.json"))
    if not files:
        print("[apply_homepage_url_fixes] no L-URL-FIX-*/homepage_updates.json found")
        return 0

    applied = noop = name_fallback = skipped_facility_home = 0
    by_kind: dict[str, int] = {}
    by_conf: dict[str, int] = {}

    with duckdb.connect(str(args.db)) as conn:
        for path in files:
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                print(f"[skip] {path}: {e}", file=sys.stderr)
                continue
            if not isinstance(payload, list):
                print(f"[skip] {path}: not a JSON array", file=sys.stderr)
                continue
            for r in payload:
                pid = r.get("person_id")
                name = r.get("name")
                url = r.get("homepage_url")
                kind = r.get("homepage_url_kind") or ""
                conf = r.get("confidence") or "medium"
                if not url:
                    continue

                # Skip low-confidence facility-home no-ops; UI fallback
                # chain already handles those.
                if conf == "low" and kind == "facility-home":
                    skipped_facility_home += 1
                    continue

                # Resolve target row.
                row = None
                if pid:
                    row = conn.execute(
                        "SELECT person_id, homepage_url FROM people WHERE person_id = ?",
                        [pid],
                    ).fetchone()
                if not row and name:
                    row = conn.execute(
                        "SELECT person_id, homepage_url FROM people "
                        "WHERE lower(name) = lower(?) LIMIT 1",
                        [name],
                    ).fetchone()
                    if row:
                        name_fallback += 1
                if not row:
                    if args.verbose:
                        print(f"  [no person] {name!r} (pid={pid!r})")
                    continue

                pid_db, prev = row
                if prev == url:
                    noop += 1
                    continue
                conn.execute(
                    "UPDATE people SET homepage_url = ? WHERE person_id = ?",
                    [url, pid_db],
                )
                applied += 1
                by_kind[kind] = by_kind.get(kind, 0) + 1
                by_conf[conf] = by_conf.get(conf, 0) + 1
                if args.verbose:
                    print(f"  [{conf:6s} {kind:18s}] {name}: {prev} → {url}")

    print(f"[apply_homepage_url_fixes] applied {applied}, no-op {noop}, "
          f"name-fallback resolves {name_fallback}, "
          f"skipped facility-home low-conf {skipped_facility_home}")
    if by_kind:
        print("  by kind:", ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    if by_conf:
        print("  by confidence:", ", ".join(f"{k}={v}" for k, v in sorted(by_conf.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
