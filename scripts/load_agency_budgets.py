#!/usr/bin/env python3
"""Load hand-curated agency-budget CSVs into funding_events.

Phase 2 of the funding research effort: 76 US federal facility units
(NMS sanctuaries, NPS coastal units, EPA NEPs, NERR reserves, NOAA OAR
labs, USGS science centers) don't appear as USAspending recipients
because they receive intramural appropriations from their parent
agency, not competitive grants. The amounts live in agency
Congressional Justification PDFs and annual reports.

This script reads CSVs in data/funding_research/agency_budgets/*.csv
and inserts them into funding_events. CSV format:

    facility_id,fiscal_year,amount_usd,funder_name,funder_type,
    program,relation,source_url,confidence,notes

Header is required. Columns:
    facility_id    — must match an existing facilities.facility_id
    fiscal_year    — 4-digit US fiscal year (Oct 1 of prev cal yr to Sep 30)
    amount_usd     — numeric, positive
    funder_name    — display name (auto-creates funder row if absent)
    funder_type    — federal | state | foundation | private (default federal)
    program        — agency program / line-item name (e.g. "NMS operating
                     allocation", "NERR Section 315 award + state match")
    relation       — appropriation | allocation | award | grant | match
                     | endowment | other (default 'appropriation')
    source_url     — direct URL to the budget book / annual report page
                     where this number was sourced
    confidence     — high | medium | low
    notes          — free-text qualifier

Idempotent via event_id = hash(funder|facility|"agency-budget"|fiscal_year).
Re-running an updated CSV REPLACES rows for the same (facility, fy)
that came from this loader. Rows from other sources (NSF, USAspending,
ProPublica) are untouched.

Usage::

    python scripts/load_agency_budgets.py
    python scripts/load_agency_budgets.py --csv data/funding_research/agency_budgets/noaa_nerr.csv
    python scripts/load_agency_budgets.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
DEFAULT_DIR = ROOT / "data" / "funding_research" / "agency_budgets"


def _hash(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=8).hexdigest()


def funder_id_for(name: str) -> str:
    return _hash((name or "").lower().strip())


def event_id_for(funder_id: str, facility_id: str,
                 fiscal_year: int) -> str:
    return _hash(f"{funder_id}|{facility_id}|agency-budget|{fiscal_year}")


def ensure_funder(conn, name: str, ftype: str) -> str:
    fid = funder_id_for(name)
    hit = conn.execute(
        "SELECT funder_id FROM funders WHERE funder_id = ?", [fid]
    ).fetchone()
    if hit:
        # Backfill type if missing.
        conn.execute(
            "UPDATE funders SET type = COALESCE(type, ?) WHERE funder_id = ?",
            [ftype or "federal", fid],
        )
        return fid
    conn.execute(
        "INSERT INTO funders (funder_id, name, type, country) "
        "VALUES (?, ?, ?, 'US')",
        [fid, name, ftype or "federal"],
    )
    return fid


def load_csv(conn, path: Path, dry: bool) -> dict:
    """Returns {csv_path, rows_read, rows_written, rows_replaced, errors}."""
    stats = {"path": str(path), "rows_read": 0, "rows_written": 0,
             "rows_replaced": 0, "errors": 0}
    if not path.exists():
        print(f"[error] CSV not found: {path}")
        stats["errors"] += 1
        return stats

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(
            (line for line in fh if not line.lstrip().startswith("#")),
        )
        for ln, row in enumerate(reader, 2):  # header is row 1
            stats["rows_read"] += 1
            try:
                fid = (row.get("facility_id") or "").strip()
                fy = int((row.get("fiscal_year") or "0").strip() or 0)
                amt = float((row.get("amount_usd") or "0").strip() or 0)
                fname = (row.get("funder_name") or "").strip()
                ftype = (row.get("funder_type") or "federal").strip()
                program = (row.get("program") or "")[:200]
                relation = (row.get("relation") or "appropriation").strip()
                src_url = (row.get("source_url") or "").strip() or None
                confidence = (row.get("confidence") or "medium").strip()
                notes = (row.get("notes") or "")[:500]
                if not (fid and fy and amt and fname):
                    print(f"[warn] {path.name}:{ln} missing required field — skip")
                    stats["errors"] += 1
                    continue

                # Validate that facility_id exists.
                hit = conn.execute(
                    "SELECT 1 FROM facilities WHERE facility_id = ?",
                    [fid],
                ).fetchone()
                if not hit:
                    print(f"[warn] {path.name}:{ln} unknown facility_id={fid} — skip")
                    stats["errors"] += 1
                    continue

                if dry:
                    continue

                funder_id = ensure_funder(conn, fname, ftype)
                eid = event_id_for(funder_id, fid, fy)

                # REPLACE-on-conflict: this loader's rows are
                # authoritative, so updating an amount in the CSV (e.g.
                # because a more accurate source was found) actually
                # updates the row instead of being silently dropped.
                # Only this loader's rows are touched — event_id is
                # deterministic on (funder, facility, fy) so it can't
                # collide with NSF / USAspending / 990 events (which
                # use different hash inputs).
                existing = conn.execute(
                    "SELECT 1 FROM funding_events WHERE event_id = ?", [eid]
                ).fetchone()
                if existing:
                    conn.execute("""
                        UPDATE funding_events
                        SET amount_usd = ?, program = ?, relation = ?,
                            source_url = ?, confidence = ?, notes = ?,
                            retrieved_at = current_date
                        WHERE event_id = ?
                    """, [amt, program, relation, src_url, confidence,
                          notes, eid])
                    stats["rows_replaced"] += 1
                else:
                    conn.execute("""
                        INSERT INTO funding_events (
                            event_id, funder_id, facility_id,
                            amount_usd, amount_currency,
                            fiscal_year, period_start, period_end,
                            award_id, award_title, program, relation,
                            source, source_url, retrieved_at,
                            confidence, notes
                        )
                        VALUES (?, ?, ?, ?, 'USD', ?, NULL, NULL,
                                NULL, NULL, ?, ?,
                                'agency budget research', ?,
                                current_date, ?, ?)
                    """, [eid, funder_id, fid, amt, fy,
                          program, relation, src_url, confidence, notes])
                    stats["rows_written"] += 1
            except Exception as e:
                print(f"[error] {path.name}:{ln} {e}")
                stats["errors"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--csv", type=Path, action="append",
                    help="Specific CSV file to load. Repeatable. Default "
                         "is to glob data/funding_research/agency_budgets/*.csv")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))

    if args.csv:
        files = list(args.csv)
    else:
        if not args.dir.exists():
            print(f"[info] no agency-budget CSVs yet at {args.dir}")
            return 0
        files = sorted(args.dir.glob("*.csv"))

    if not files:
        print("[info] no CSVs to load")
        return 0

    grand = {"rows_read": 0, "rows_written": 0, "rows_replaced": 0,
             "errors": 0}
    for f in files:
        print(f"[load] {f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}")
        s = load_csv(conn, f, args.dry_run)
        for k in grand:
            grand[k] += s[k]
        print(f"  read={s['rows_read']}  wrote={s['rows_written']}  "
              f"replaced={s['rows_replaced']}  errors={s['errors']}")

    print(f"\n[done] read={grand['rows_read']}  wrote={grand['rows_written']}  "
          f"replaced={grand['rows_replaced']}  errors={grand['errors']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
