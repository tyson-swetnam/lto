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

person_id is the name-only stable hash shared by every people loader
(load_people_research.resolve_person_id): an existing person with the row's
ORCID / OpenAlex id, or under the pre-lake name|orcid|email hash, keeps
that id.

Usage::

    python scripts/load_facility_personnel_by_id.py --csv path.csv
    python scripts/load_facility_personnel_by_id.py --csv-glob 'data/seed/*.csv'

Roles are normalised to schema/vocab/personnel_roles.csv slugs
(load_people_research.normalize_role; the raw spelling is kept in title
when title is blank) and a row whose role has no mapping is skipped.
start_date / end_date accept YYYY, YYYY-MM or YYYY-MM-DD. retrieved_at
comes from a retrieved_at column or --retrieved-at, never the clock. A row
already backed by fetched evidence (load_people_research.py) is left alone.

Writes the DuckLake store of record (scripts/lto_db.py): one snapshot per
run, rolled back whole if a row breaks a schema.sql constraint.
"""
from __future__ import annotations

import argparse
import csv
import sys
from glob import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_people_research import (legacy_person_id, load_roles, normalize_role,  # noqa: E402
                                  parse_date, resolve_person_id)

ROOT = Path(__file__).resolve().parent.parent

KEY_ROLE_DEFAULTS = {
    "Director", "Executive Director", "Deputy Director", "Associate Director",
    "Chief Scientist", "Principal Investigator", "Co-Principal Investigator",
    "Reserve Manager", "Program Manager", "Head Administrator",
    "President & Director", "Research Coordinator", "Research Director",
    "Scientific Director", "Education Coordinator", "Stewardship Coordinator",
    "Manager",
}


def split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if len(parts) < 2:
        return "", full.strip()
    return " ".join(parts[:-1]), parts[-1]


def upsert_person(conn, name, orcid, email, openalex_id, homepage_url,
                  facility_id=None) -> str:
    pid = resolve_person_id(conn, name, orcid, openalex_id,
                            legacy_id=legacy_person_id(name, orcid, email),
                            facility_id=facility_id)
    given, family = split_name(name)
    lto_db.merge_upsert(
        conn, "people", ["person_id"],
        "SELECT ? AS person_id, ? AS name, ? AS name_family, ? AS name_given, "
        "CAST(NULL AS VARCHAR) AS email, ? AS orcid, ? AS openalex_id, ? AS homepage_url, now() AS updated_at",
        params=[pid, name, family, given, orcid or None,
                openalex_id or None, homepage_url or None],
        # An existing person keeps its name; identifiers and links are only
        # filled in where the lake has none (a research batch's sourced
        # homepage or a verified ORCID is never overwritten by a seed row).
        # The CSV's email only feeds the pre-lake id hash: contact details
        # are not stored (export_parquet.py would blank them anyway, and a
        # value the published parquet cannot carry would make every
        # rebuild-and-reload differ).
        update_cols=["orcid", "openalex_id", "homepage_url"],
        fill=["orcid", "openalex_id", "homepage_url"],
        extra_set={"updated_at": "CASE WHEN " + " OR ".join(
            f"(t.{c} IS NULL AND s.{c} IS NOT NULL)"
            for c in ("orcid", "openalex_id", "homepage_url"))
            + " THEN now() ELSE t.updated_at END"},)
    return pid


def upsert_role(conn, pid, fid, role, title, is_key, source, source_url,
                confidence, notes, start_date=None, end_date=None,
                retrieved_at=None) -> bool:
    """Upsert one affiliation; False (no write) when the row is already
    backed by fetched evidence (load_people_research.py), which a seed CSV
    must not overwrite."""
    if lto_db.scalar(conn, "SELECT count(*) FROM facility_personnel WHERE person_id = ? "
                           "AND facility_id = ? AND role = ? AND evidence IS NOT NULL",
                     [pid, fid, role]):
        return False
    lto_db.merge_upsert(
        conn, "facility_personnel", ["person_id", "facility_id", "role"],
        "SELECT ? AS person_id, ? AS facility_id, ? AS role, ? AS title, "
        "?::BOOLEAN AS is_key_personnel, ?::DATE AS start_date, ?::DATE AS end_date, "
        "? AS source, ? AS source_url, ?::DATE AS retrieved_at, ? AS confidence, ? AS notes",
        params=[pid, fid, role, title or None, is_key, start_date, end_date,
                (source or "facility-webpage"), source_url or None, retrieved_at,
                (confidence or "medium"), notes or None],
        # A NULL in the CSV never erases what a later loader appended
        # (dates); notes are appended to, never replaced, so a supersede or
        # repair note another loader added survives a re-run.
        update_cols=["title", "is_key_personnel", "start_date", "end_date", "source",
                     "source_url", "retrieved_at", "confidence"],
        coalesce=["title", "start_date", "end_date", "retrieved_at"],
        extra_set={"notes": "CASE WHEN s.notes IS NULL OR position(s.notes IN COALESCE(t.notes, '')) > 0 "
                         "THEN t.notes ELSE trim(COALESCE(t.notes, '') || ' ' || s.notes) END"})
    return True


def load_one(conn, path: Path, roles: dict, retrieved_at: str | None = None) -> dict:
    stats = {"path": str(path), "ok": 0, "skipped": 0, "errors": 0, "kept": 0}
    if not path.exists():
        print(f"[error] {path} not found")
        stats["errors"] += 1
        return stats
    with path.open(newline="", encoding="utf-8") as fh:
        for ln, row in enumerate(csv.DictReader(fh), 2):
            try:
                if None in row or any(v is None for v in row.values()):
                    # An unquoted comma shifts every later column: refuse the row.
                    print(f"[skip] {path.name}:{ln} wrong column count; quote fields "
                          f"that contain commas")
                    stats["skipped"] += 1
                    continue
                fid = (row.get("facility_id") or "").strip()
                name = (row.get("name") or "").strip()
                raw_role = (row.get("role") or "").strip()
                if not (fid and name and raw_role):
                    stats["skipped"] += 1
                    continue
                # Validate facility exists.
                hit = lto_db.scalar(
                    conn, "SELECT 1 FROM facilities WHERE facility_id = ?", [fid])
                if not hit:
                    print(f"[skip] {path.name}:{ln} unknown facility_id={fid}")
                    stats["skipped"] += 1
                    continue
                # Roles go through schema/vocab/personnel_roles.csv (with the
                # aliases in load_people_research.ROLE_ALIASES); a spelling
                # with no mapping is skipped and reported, never stored raw.
                role = normalize_role(raw_role, roles)
                if not role:
                    print(f"[skip] {path.name}:{ln} role {raw_role!r} not in personnel_roles.csv")
                    stats["skipped"] += 1
                    continue
                raw_key = (row.get("is_key_personnel") or "").strip().lower()
                if raw_key in ("true", "1", "yes", "y"):
                    is_key = True
                elif raw_key in ("false", "0", "no", "n"):
                    is_key = False
                else:
                    is_key = raw_role in KEY_ROLE_DEFAULTS
                pid = upsert_person(
                    conn, name,
                    (row.get("orcid") or "").strip(),
                    (row.get("email") or "").strip(),
                    (row.get("openalex_id") or "").strip(),
                    (row.get("homepage_url") or "").strip(),
                    facility_id=fid,
                )
                wrote = upsert_role(
                    conn, pid, fid, role,
                    (row.get("title") or "").strip() or raw_role,
                    is_key,
                    (row.get("source") or "").strip(),
                    (row.get("source_url") or "").strip(),
                    (row.get("confidence") or "").strip(),
                    (row.get("notes") or "").strip(),
                    parse_date(row.get("start_date")),
                    parse_date(row.get("end_date")),
                    parse_date(row.get("retrieved_at")) or retrieved_at,
                )
                stats["ok" if wrote else "kept"] += 1
            except (ValueError, KeyError) as e:
                # Row-level data problems skip the row. A database error is
                # not caught: it has aborted the run's transaction, so the
                # whole run rolls back instead of half-landing.
                print(f"[error] {path.name}:{ln} {e}")
                stats["errors"] += 1
    return stats


def catalog_arg(args) -> Path | None:
    """--db is the pre-lake flag, kept as an alias of --catalog. The retired
    db/lto.duckdb file itself is not a catalog, so it is ignored."""
    if args.db is None or args.catalog is not None:
        return args.catalog
    if args.db.suffix == ".duckdb":
        print(f"[deprecated] --db {args.db} ignored (db/lto.duckdb is retired); "
              f"use --catalog", file=sys.stderr)
        return None
    return args.db


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", type=Path, default=None,
                    help="deprecated alias of --catalog (a db/lto.duckdb path is ignored)")
    ap.add_argument("--csv", type=Path, action="append")
    ap.add_argument("--csv-glob", type=str, default=None)
    ap.add_argument("--retrieved-at", default=None,
                    help="date the CSV was compiled, when the file states one (YYYY-MM-DD); "
                         "a retrieved_at column wins. Default NULL — never the clock")
    args = ap.parse_args()

    paths: list[Path] = []
    if args.csv:
        paths.extend(args.csv)
    if args.csv_glob:
        paths.extend(Path(p) for p in glob(args.csv_glob))
    if not paths:
        print("[error] need --csv or --csv-glob")
        return 2

    try:
        conn = lto_db.connect(catalog=catalog_arg(args), data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}")
        return 2
    grand = {"ok": 0, "skipped": 0, "errors": 0, "kept": 0}
    roles = load_roles()
    names = ", ".join(p.name for p in paths[:3]) + (f" +{len(paths) - 3}" if len(paths) > 3 else "")
    with lto_db.transaction(conn, f"load_facility_personnel_by_id: {names}"):
        for p in paths:
            s = load_one(conn, p, roles, parse_date(args.retrieved_at))
            for k in grand:
                grand[k] += s[k]
            print(f"  {p.name}: ok={s['ok']} skipped={s['skipped']} errors={s['errors']} "
                  f"kept_evidence_rows={s['kept']}")
        lto_db.assert_integrity(conn, ["people", "facility_personnel"])
    print(f"[done] ok={grand['ok']} skipped={grand['skipped']} errors={grand['errors']} "
          f"kept_evidence_rows={grand['kept']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
