#!/usr/bin/env python3
"""Apply person homepage_url corrections from data/raw/P-URL-*/.

Reads every `data/raw/P-URL-*/url_corrections.json` produced by the
Loop-P URL-audit agents (per the never-fabricate rule), filters to
records where `suggested_url` is non-null AND `confidence` is "high"
(or per --min-confidence), and rewrites the matching `people` rows.

The audit JSON contains MANY rows where `suggested_url` is null —
those are *flagged* suspect URLs the agent couldn't replace from
training data. They stay in the audit output for CI's HTTP-HEAD
checker to verify and (if dead) drop.

Usage::

    python scripts/apply_url_corrections.py
    python scripts/apply_url_corrections.py --min-confidence high
    python scripts/apply_url_corrections.py --dry-run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
RAW_DIR = ROOT / "data" / "raw"
CONF_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--min-confidence", default="high",
                    choices=["high", "medium", "low"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    threshold = CONF_RANK[args.min_confidence]

    files = sorted(RAW_DIR.glob("P-URL-*/url_corrections.json"))
    print(f"[apply_url] reading {len(files)} audit files")

    candidates = []
    suspect_no_fix = 0
    for p in files:
        doc = json.loads(p.read_text())
        # Two output shapes: (a) bare list of correction objects, or
        # (b) top-level dict wrapping the list under one of {corrections,
        # rows, audits, items, results}.
        if isinstance(doc, list):
            rows = doc
        elif isinstance(doc, dict):
            rows = (doc.get("corrections") or doc.get("rows")
                    or doc.get("audits") or doc.get("items")
                    or doc.get("results") or [])
        else:
            rows = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if not r.get("suggested_url"):
                if r.get("suspect_reason"):
                    suspect_no_fix += 1
                continue
            if CONF_RANK.get(r.get("confidence")) < threshold:
                continue
            candidates.append(r)

    print(f"[apply_url] {len(candidates)} corrections >= '{args.min_confidence}', "
          f"{suspect_no_fix} suspect rows with no replacement")

    applied = 0
    skipped = 0
    with duckdb.connect(str(args.db)) as conn:
        for r in candidates:
            name = (r.get("name") or "").strip()
            new_url = r.get("suggested_url")
            old_url = r.get("current_url")
            if not name or not new_url:
                skipped += 1
                continue
            row = conn.execute(
                "SELECT person_id, homepage_url FROM people "
                "WHERE lower(name) = lower(?) LIMIT 1",
                [name],
            ).fetchone()
            if not row:
                print(f"  [skip] no person row for '{name}'")
                skipped += 1
                continue
            pid, current = row[0], row[1]
            if current != old_url:
                # Audit's "current_url" doesn't match what's actually
                # in the DB — could be a stale audit. Note + skip.
                print(f"  [skip] {name}: db has {current}, audit said {old_url}")
                skipped += 1
                continue
            if args.dry_run:
                print(f"  [dry-run] would update {name}: {old_url} -> {new_url}")
            else:
                conn.execute(
                    "UPDATE people SET homepage_url = ? WHERE person_id = ?",
                    [new_url, pid],
                )
                applied += 1
                print(f"  [ok] {name}: {old_url} -> {new_url}")

    mode = "[dry-run] would have" if args.dry_run else "[apply_url]"
    print(f"{mode} updated {applied} rows; skipped {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
