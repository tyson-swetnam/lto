#!/usr/bin/env python3
"""Load a facility_personnel seed CSV into people + facility_personnel.

Workflow:
  1. User fills in data/seed/facility_personnel_seed.csv (or any CSV with
     the same columns) by hand from institutional webpages.
  2. Run this script — each row becomes a people row (upserted on
     person_id = hash(lower(name) || orcid-or-email-or-idx)) plus a
     facility_personnel row tying the person to the facility.

Facility matching:
  - If `facility_acronym` is set, match facilities.acronym exactly.
  - Else if `facility_name_like` is set, match canonical_name ILIKE %…%
    and require exactly one hit; otherwise skip the row with a warning.

Usage::

    python scripts/load_facility_personnel.py
    python scripts/load_facility_personnel.py --csv data/seed/facility_personnel_seed.csv
    python scripts/load_facility_personnel.py --export-parquet

Idempotent: re-running with the same CSV updates existing rows in
place (UPDATE on the primary keys) rather than duplicating.
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
DEFAULT_CSV = ROOT / "data" / "seed" / "facility_personnel_seed.csv"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]

# Roles that default to is_key_personnel=true when the CSV cell is blank.
KEY_ROLE_DEFAULTS = {
    "Director",
    "Deputy Director",
    "Associate Director",
    "Chief Scientist",
    "Principal Investigator",
    "Head Administrator",
    "Program Manager",
    "President & Director",
    "Executive Director",
}


def person_id(name: str, orcid: str = "", email: str = "") -> str:
    """Stable hash so re-runs upsert instead of duplicating. ORCID is the
    strongest disambiguator; fall back to email, then name alone."""
    key = f"{name.strip().lower()}|{(orcid or '').strip()}|{(email or '').strip().lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def split_name(full: str) -> tuple[str, str]:
    """Rough 'First Middle Last' split. Tolerates unusual names by
    returning ('', full) if no space."""
    parts = full.strip().split()
    if len(parts) < 2:
        return "", full.strip()
    return " ".join(parts[:-1]), parts[-1]


def resolve_facility(conn, acronym: str, name_like: str) -> str | None:
    if acronym:
        row = conn.execute(
            "SELECT facility_id FROM facilities WHERE acronym = ?",
            [acronym.strip()],
        ).fetchone()
        if row:
            return row[0]
    if name_like:
        rows = conn.execute(
            "SELECT facility_id, canonical_name FROM facilities "
            "WHERE canonical_name ILIKE ? ORDER BY canonical_name",
            [f"%{name_like.strip()}%"],
        ).fetchall()
        if len(rows) == 1:
            return rows[0][0]
        if len(rows) > 1:
            names = ", ".join(r[1] for r in rows)
            print(f"[warn] ambiguous name_like={name_like!r} matched: {names}")
    return None


def upsert_person(conn, row: dict) -> str:
    name = (row.get("person_name") or "").strip()
    orcid = (row.get("orcid") or "").strip()
    email = (row.get("email") or "").strip()
    pid = person_id(name, orcid, email)
    given, family = split_name(name)

    # DuckDB: INSERT ... ON CONFLICT (person_id) DO UPDATE
    conn.execute(
        """
        INSERT INTO people (
            person_id, name, name_family, name_given, email, orcid,
            openalex_id, homepage_url, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, now())
        ON CONFLICT (person_id) DO UPDATE SET
            name         = excluded.name,
            name_family  = excluded.name_family,
            name_given   = excluded.name_given,
            email        = COALESCE(excluded.email, people.email),
            orcid        = COALESCE(excluded.orcid, people.orcid),
            openalex_id  = COALESCE(excluded.openalex_id, people.openalex_id),
            homepage_url = COALESCE(excluded.homepage_url, people.homepage_url),
            updated_at   = now()
        """,
        [pid, name, family, given, email or None, orcid or None,
         (row.get("openalex_id") or "").strip() or None,
         (row.get("homepage_url") or "").strip() or None],
    )
    return pid


def upsert_role(conn, pid: str, fid: str, row: dict) -> None:
    role = (row.get("role") or "").strip()
    title = (row.get("title") or "").strip() or None
    raw_key = (row.get("is_key_personnel") or "").strip().lower()
    if raw_key in ("true", "1", "yes", "y"):
        is_key = True
    elif raw_key in ("false", "0", "no", "n"):
        is_key = False
    else:
        is_key = role in KEY_ROLE_DEFAULTS
    conn.execute(
        """
        INSERT INTO facility_personnel (
            person_id, facility_id, role, title, is_key_personnel,
            source, source_url, retrieved_at, confidence, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, current_date, ?, ?)
        ON CONFLICT (person_id, facility_id, role) DO UPDATE SET
            title            = excluded.title,
            is_key_personnel = excluded.is_key_personnel,
            source           = excluded.source,
            source_url       = excluded.source_url,
            retrieved_at     = excluded.retrieved_at,
            confidence       = excluded.confidence,
            notes            = excluded.notes
        """,
        [pid, fid, role, title, is_key,
         (row.get("source") or "manual").strip(),
         (row.get("source_url") or "").strip() or None,
         (row.get("confidence") or "medium").strip(),
         (row.get("notes") or "").strip() or None],
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--export-parquet", action="store_true")
    args = ap.parse_args()
    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2
    if not args.csv.exists():
        print(f"[error] csv not found: {args.csv}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))
    ok = skipped = 0
    with args.csv.open() as fh:
        rdr = csv.DictReader(fh)
        for row in rdr:
            # Support '#'-prefixed comment rows.
            fac_acr  = (row.get("facility_acronym")  or "").strip()
            name_lk  = (row.get("facility_name_like") or "").strip()
            pname    = (row.get("person_name")       or "").strip()
            role     = (row.get("role")              or "").strip()
            if fac_acr.startswith("#") or not pname or not role:
                skipped += 1
                continue
            fid = resolve_facility(conn, fac_acr, name_lk)
            if not fid:
                print(f"[skip] could not resolve facility for "
                      f"acronym={fac_acr!r}, name_like={name_lk!r}")
                skipped += 1
                continue
            pid = upsert_person(conn, row)
            upsert_role(conn, pid, fid, row)
            ok += 1

    print(f"[load] ok={ok} skipped={skipped}")

    if args.export_parquet:
        for base in PARQUET_OUT:
            base.mkdir(parents=True, exist_ok=True)
            for t in ("people", "facility_personnel"):
                out = base / f"{t}.parquet"
                conn.execute(f"COPY {t} TO '{out}' (FORMAT PARQUET)")
                print(f"[parquet] wrote {out}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
