#!/usr/bin/env python3
"""Load a facility_personnel seed CSV into people + facility_personnel.

Workflow:
  1. User fills in data/seed/facility_personnel_seed.csv (or any CSV with
     the same columns) by hand from institutional webpages.
  2. Run this script — each row becomes a people row (upserted on
     person_id; see below) plus a facility_personnel row tying the
     person to the facility.

person_id is the name-only stable hash (load_people_research.stable_person_id).
A person who already carries the row's ORCID / OpenAlex id, or who exists
under the pre-lake hash(lower(name)|orcid|email), keeps that id, so
adding an ORCID or email to the CSV no longer mints a second person.

Roles are normalised to schema/vocab/personnel_roles.csv slugs (a role
with no mapping skips the row); retrieved_at comes from a retrieved_at
column or --retrieved-at, never the clock; a row already backed by fetched
evidence (load_people_research.py) is left alone.

Facility matching:
  - If `facility_acronym` is set and exactly one facility carries it,
    use that one (29 facilities share "NERR", 19 "NEP", ...: a shared
    acronym falls through to the name).
  - Else if `facility_name_like` is set, match canonical_name ILIKE %…%
    and require exactly one hit; otherwise skip the row with a warning.

Usage::

    python scripts/load_facility_personnel.py
    python scripts/load_facility_personnel.py --csv data/seed/facility_personnel_seed.csv

Writes the DuckLake store of record (scripts/lto_db.py), one snapshot per
run; publish with export_parquet.py (``--export-parquet`` is gone).

Idempotent: re-running with the same CSV updates existing rows in
place (MERGE on the primary keys) rather than duplicating.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_people_research import (legacy_person_id, load_roles, normalize_role,  # noqa: E402
                                  parse_date, resolve_person_id)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "seed" / "facility_personnel_seed.csv"

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


def split_name(full: str) -> tuple[str, str]:
    """Rough 'First Middle Last' split. Tolerates unusual names by
    returning ('', full) if no space."""
    parts = full.strip().split()
    if len(parts) < 2:
        return "", full.strip()
    return " ".join(parts[:-1]), parts[-1]


def resolve_facility(conn, acronym: str, name_like: str) -> str | None:
    if acronym:
        rows = conn.execute(
            "SELECT facility_id FROM facilities WHERE acronym = ? "
            "ORDER BY facility_id LIMIT 2",
            [acronym.strip()],
        ).fetchall()
        if len(rows) == 1:
            return rows[0][0]
        if rows:
            print(f"[warn] acronym {acronym!r} is shared by several facilities; "
                  f"trying name_like")
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


def upsert_person(conn, row: dict, facility_id: str | None = None) -> str:
    name = (row.get("person_name") or "").strip()
    orcid = (row.get("orcid") or "").strip()
    email = (row.get("email") or "").strip()
    openalex_id = (row.get("openalex_id") or "").strip() or None
    pid = resolve_person_id(conn, name, orcid, openalex_id,
                            legacy_id=legacy_person_id(name, orcid, email),
                            facility_id=facility_id)
    given, family = split_name(name)

    # Was INSERT ... ON CONFLICT (person_id) DO UPDATE; DuckLake has no keys.
    lto_db.merge_upsert(
        conn, "people", ["person_id"],
        "SELECT ? AS person_id, ? AS name, ? AS name_family, ? AS name_given, "
        "CAST(NULL AS VARCHAR) AS email, ? AS orcid, ? AS openalex_id, ? AS homepage_url, now() AS updated_at",
        params=[pid, name, family, given, orcid or None, openalex_id,
                (row.get("homepage_url") or "").strip() or None],
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
            + " THEN now() ELSE t.updated_at END"},
    )
    return pid


def upsert_role(conn, pid: str, fid: str, row: dict, role: str,
                retrieved_at: str | None = None) -> bool:
    """Upsert one affiliation under the vocab slug ``role``. False (no
    write) when the row is already backed by fetched evidence
    (load_people_research.py), which a seed CSV must not overwrite."""
    raw_role = (row.get("role") or "").strip()
    title = (row.get("title") or "").strip() or raw_role or None
    raw_key = (row.get("is_key_personnel") or "").strip().lower()
    if raw_key in ("true", "1", "yes", "y"):
        is_key = True
    elif raw_key in ("false", "0", "no", "n"):
        is_key = False
    else:
        is_key = raw_role in KEY_ROLE_DEFAULTS
    if lto_db.scalar(conn, "SELECT count(*) FROM facility_personnel WHERE person_id = ? "
                           "AND facility_id = ? AND role = ? AND evidence IS NOT NULL",
                     [pid, fid, role]):
        return False
    lto_db.merge_upsert(
        conn, "facility_personnel", ["person_id", "facility_id", "role"],
        "SELECT ? AS person_id, ? AS facility_id, ? AS role, ? AS title, "
        "?::BOOLEAN AS is_key_personnel, ?::DATE AS start_date, ?::DATE AS end_date, "
        "? AS source, ? AS source_url, ?::DATE AS retrieved_at, ? AS confidence, ? AS notes",
        params=[pid, fid, role, title, is_key,
         parse_date(row.get("start_date")), parse_date(row.get("end_date")),
         (row.get("source") or "manual").strip(),
         (row.get("source_url") or "").strip() or None,
         parse_date(row.get("retrieved_at")) or retrieved_at,
         (row.get("confidence") or "medium").strip(),
         (row.get("notes") or "").strip() or None],
        # A NULL in the CSV never erases what a later loader appended
        # (dates); notes are appended to, never replaced, so a supersede or
        # repair note another loader added survives a re-run.
        update_cols=["title", "is_key_personnel", "start_date", "end_date", "source",
                     "source_url", "retrieved_at", "confidence"],
        coalesce=["title", "start_date", "end_date", "retrieved_at"],
        extra_set={"notes": "CASE WHEN s.notes IS NULL OR position(s.notes IN COALESCE(t.notes, '')) > 0 "
                         "THEN t.notes ELSE trim(COALESCE(t.notes, '') || ' ' || s.notes) END"},
    )
    return True


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
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--export-parquet", action="store_true",
                    help="deprecated no-op: run scripts/export_parquet.py to publish")
    ap.add_argument("--retrieved-at", default=None,
                    help="date the CSV was compiled, when the file states one (YYYY-MM-DD); "
                         "a retrieved_at column wins. Default NULL — never the clock")
    args = ap.parse_args()
    if not args.csv.exists():
        print(f"[error] csv not found: {args.csv}", file=sys.stderr)
        return 2
    try:
        conn = lto_db.connect(catalog=catalog_arg(args), data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    ok = skipped = kept = 0
    roles = load_roles()
    retrieved_at = parse_date(args.retrieved_at)
    with args.csv.open() as fh, \
            lto_db.transaction(conn, f"load_facility_personnel: {args.csv.name}"):
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
            if None in row or any(v is None for v in row.values()):
                # An unquoted comma shifts every later column (a URL with
                # commas once landed in `confidence`): refuse the row.
                print(f"[skip] line {rdr.line_num}: {len(rdr.fieldnames)} columns expected; "
                      f"quote fields that contain commas")
                skipped += 1
                continue
            fid = resolve_facility(conn, fac_acr, name_lk)
            if not fid:
                print(f"[skip] could not resolve facility for "
                      f"acronym={fac_acr!r}, name_like={name_lk!r}")
                skipped += 1
                continue
            slug = normalize_role(role, roles)
            if not slug:
                print(f"[skip] role {role!r} ({pname}) not in personnel_roles.csv")
                skipped += 1
                continue
            pid = upsert_person(conn, row, fid)
            if upsert_role(conn, pid, fid, row, slug, retrieved_at):
                ok += 1
            else:
                kept += 1
        lto_db.assert_integrity(conn, ["people", "facility_personnel"])

    print(f"[load] ok={ok} skipped={skipped} kept_evidence_rows={kept}")

    if args.export_parquet:
        print("[parquet] --export-parquet is a no-op now: the lake is the store of "
              "record; run scripts/export_parquet.py (the only writer of public/parquet)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
