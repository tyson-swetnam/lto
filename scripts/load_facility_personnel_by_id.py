#!/usr/bin/env python3
"""Load a facility_personnel CSV that uses facility_id directly.

Adapter for round-2 personnel CSVs whose subagents emit `facility_id`
(stronger key) instead of `facility_acronym` / `facility_name_like`
(the legacy loader's fields). Same upsert semantics as
`load_facility_personnel.py` — idempotent on (person_id, facility_id,
role).

CSV header (in order, exactly):

    facility_id,role,name,title,is_key_personnel,start_date,end_date,
    source,source_url,confidence,notes,orcid,openalex_id,homepage_url,email

Usage::

    python scripts/load_facility_personnel_by_id.py --csv path.csv
    python scripts/load_facility_personnel_by_id.py --csv-glob 'data/seed/*.csv'
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from glob import glob
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"

KEY_ROLE_DEFAULTS = {
    "Director", "Executive Director", "Deputy Director", "Associate Director",
    "Chief Scientist", "Principal Investigator", "Co-Principal Investigator",
    "Reserve Manager", "Program Manager", "Head Administrator",
    "President & Director", "Research Coordinator", "Research Director",
    "Scientific Director", "Education Coordinator", "Stewardship Coordinator",
    "Manager",
}


def person_id(name: str, orcid: str = "", email: str = "") -> str:
    key = f"{name.strip().lower()}|{(orcid or '').strip()}|{(email or '').strip().lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if len(parts) < 2:
        return "", full.strip()
    return " ".join(parts[:-1]), parts[-1]


def upsert_person(conn, name, orcid, email, openalex_id, homepage_url) -> str:
    pid = person_id(name, orcid, email)
    given, family = split_name(name)
    conn.execute("""
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
    """, [pid, name, family, given, email or None, orcid or None,
          openalex_id or None, homepage_url or None])
    return pid


def upsert_role(conn, pid, fid, role, title, is_key, source, source_url,
                confidence, notes) -> None:
    conn.execute("""
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
    """, [pid, fid, role, title or None, is_key,
          (source or "facility-webpage"), source_url or None,
          (confidence or "medium"), notes or None])


def load_one(conn, path: Path) -> dict:
    stats = {"path": str(path), "ok": 0, "skipped": 0, "errors": 0}
    if not path.exists():
        print(f"[error] {path} not found")
        stats["errors"] += 1
        return stats
    with path.open(newline="", encoding="utf-8") as fh:
        for ln, row in enumerate(csv.DictReader(fh), 2):
            try:
                fid = (row.get("facility_id") or "").strip()
                name = (row.get("name") or "").strip()
                role = (row.get("role") or "").strip()
                if not (fid and name and role):
                    stats["skipped"] += 1
                    continue
                # Validate facility exists.
                hit = conn.execute(
                    "SELECT 1 FROM facilities WHERE facility_id = ?", [fid]
                ).fetchone()
                if not hit:
                    print(f"[skip] {path.name}:{ln} unknown facility_id={fid}")
                    stats["skipped"] += 1
                    continue
                raw_key = (row.get("is_key_personnel") or "").strip().lower()
                if raw_key in ("true", "1", "yes", "y"):
                    is_key = True
                elif raw_key in ("false", "0", "no", "n"):
                    is_key = False
                else:
                    is_key = role in KEY_ROLE_DEFAULTS
                pid = upsert_person(
                    conn, name,
                    (row.get("orcid") or "").strip(),
                    (row.get("email") or "").strip(),
                    (row.get("openalex_id") or "").strip(),
                    (row.get("homepage_url") or "").strip(),
                )
                upsert_role(
                    conn, pid, fid, role,
                    (row.get("title") or "").strip(),
                    is_key,
                    (row.get("source") or "").strip(),
                    (row.get("source_url") or "").strip(),
                    (row.get("confidence") or "").strip(),
                    (row.get("notes") or "").strip(),
                )
                stats["ok"] += 1
            except Exception as e:
                print(f"[error] {path.name}:{ln} {e}")
                stats["errors"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--csv", type=Path, action="append")
    ap.add_argument("--csv-glob", type=str, default=None)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}")
        return 2
    paths: list[Path] = []
    if args.csv:
        paths.extend(args.csv)
    if args.csv_glob:
        paths.extend(Path(p) for p in glob(args.csv_glob))
    if not paths:
        print("[error] need --csv or --csv-glob")
        return 2

    conn = duckdb.connect(str(args.db))
    grand = {"ok": 0, "skipped": 0, "errors": 0}
    for p in paths:
        s = load_one(conn, p)
        for k in grand:
            grand[k] += s[k]
        print(f"  {p.name}: ok={s['ok']} skipped={s['skipped']} errors={s['errors']}")
    print(f"[done] ok={grand['ok']} skipped={grand['skipped']} errors={grand['errors']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
