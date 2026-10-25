#!/usr/bin/env python3
"""Apply reviewed, sourced corrections to facilities and their facet tables.

Input
  data/seed/facility_fixes.csv   one fact per row:
      facility_id, table, action, field, value, source_url, retrieved_at, evidence

  table / action / field / value:
    facilities          set     <column>        new value (cast to the column type)
    facility_spheres    add     primary|secondary  sphere slug
    facility_spheres    remove  (blank)         sphere slug
    network_membership  add|remove (blank)      network_id
    area_links          add|remove (blank)      research area slug
    provenance          add     <confidence>    <agent>: a provenance row for the
                                                facility citing source_url, replacing
                                                an earlier row of the same agent

Every row needs a source_url and evidence (what the source says); a row
without them, a slug missing from its vocab table, an unknown column or an
unknown facility stops the run. A facility merged away is read as the
facility it was kept as (lto_db.canonical_facility_id). Values are written
as given — this script never derives one.

One lake transaction (one snapshot), checked with lto_db.assert_integrity.
Idempotent: a second run changes nothing.

Usage::

    python scripts/apply_facility_fixes.py --dry-run
    python scripts/apply_facility_fixes.py
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXES = ROOT / "data" / "seed" / "facility_fixes.csv"

# Link table -> (slug column, vocab table, vocab key)
LINKS = {
    "facility_spheres": ("sphere_slug", "spheres", "slug"),
    "network_membership": ("network_id", "networks", "network_id"),
    "area_links": ("area_id", "research_areas", "area_id"),
}
NO_SET = {"facility_id", "created_at"}


class _DryRun(Exception):
    pass


def read_fixes(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]


def validate(con, fixes: list[dict]) -> list[str]:
    errors = []
    cols = dict(lto_db.rows(
        con, "SELECT column_name, data_type FROM duckdb_columns() WHERE database_name = ? "
             "AND schema_name = 'main' AND table_name = 'facilities'", [lto_db.LAKE]))
    have = {r[0] for r in lto_db.rows(con, "SELECT facility_id FROM facilities")}
    for i, f in enumerate(fixes, start=2):
        where = f"line {i} ({f.get('table')} {f.get('action')} {f.get('field')} {f.get('value')!r})"
        if not f["source_url"] or not f["evidence"]:
            errors.append(f"{where}: no source_url / evidence")
        if f["facility_id"] not in have:
            errors.append(f"{where}: unknown facility_id {f['facility_id']}")
        t, a = f["table"], f["action"]
        if t == "facilities":
            if a != "set" or f["field"] not in cols or f["field"] in NO_SET:
                errors.append(f"{where}: facilities takes 'set <column>'")
        elif t in LINKS:
            slug, vocab, key = LINKS[t]
            if a not in ("add", "remove"):
                errors.append(f"{where}: {t} takes add / remove")
            if t == "facility_spheres" and a == "add" and f["field"] not in ("primary", "secondary"):
                errors.append(f"{where}: a sphere is added as primary or secondary")
            if a == "add" and not lto_db.scalar(
                    con, f"SELECT count(*) FROM {vocab} WHERE {key} = ?", [f["value"]]):
                errors.append(f"{where}: {f['value']!r} not in {vocab}")
        elif t == "provenance":
            if a != "add" or f["field"] not in ("high", "medium", "low") or not f["value"]:
                errors.append(f"{where}: provenance takes 'add <confidence> <agent>'")
        else:
            errors.append(f"{where}: unknown table {t!r}")
    return errors


def apply(con, fixes: list[dict]) -> Counter:
    n: Counter = Counter()
    types = dict(lto_db.rows(
        con, "SELECT column_name, data_type FROM duckdb_columns() WHERE database_name = ? "
             "AND schema_name = 'main' AND table_name = 'facilities'", [lto_db.LAKE]))

    def changed(sql: str, params) -> int:
        return lto_db.scalar(con, sql, params) or 0

    # Removals first, so a primary sphere can be swapped in one file.
    order = sorted(fixes, key=lambda f: (f["action"] != "remove"))
    for f in order:
        fid, t, a, field, value = (f["facility_id"], f["table"], f["action"],
                                   f["field"], f["value"])
        if t == "facilities":
            typ = types[field]
            if changed(f"SELECT count(*) FROM facilities WHERE facility_id = ? "
                       f"AND {field} IS DISTINCT FROM CAST(? AS {typ})", [fid, value]):
                con.execute(f"UPDATE facilities SET {field} = CAST(? AS {typ}) "
                            f"WHERE facility_id = ?", [value, fid])
                n[f"facilities.{field}"] += 1
        elif t in LINKS:
            slug = LINKS[t][0]
            if a == "remove":
                k = changed(f"SELECT count(*) FROM {t} WHERE facility_id = ? AND {slug} = ?",
                            [fid, value])
                con.execute(f"DELETE FROM {t} WHERE facility_id = ? AND {slug} = ?", [fid, value])
                n[f"{t}.removed"] += k
            elif t == "facility_spheres":
                cur = lto_db.rows(con, "SELECT role FROM facility_spheres WHERE facility_id = ? "
                                       "AND sphere_slug = ?", [fid, value])
                if not cur:
                    con.execute("INSERT INTO facility_spheres (facility_id, sphere_slug, role) "
                                "VALUES (?, ?, ?)", [fid, value, field])
                    n[f"{t}.added"] += 1
                elif cur[0][0] != field:
                    con.execute("UPDATE facility_spheres SET role = ? WHERE facility_id = ? "
                                "AND sphere_slug = ?", [field, fid, value])
                    n[f"{t}.role"] += 1
            elif not changed(f"SELECT count(*) FROM {t} WHERE facility_id = ? AND {slug} = ?",
                             [fid, value]):
                con.execute(f"INSERT INTO {t} (facility_id, {slug}) VALUES (?, ?)", [fid, value])
                n[f"{t}.added"] += 1
        elif t == "provenance":
            row = [f["source_url"], f["retrieved_at"] or None, field]
            if not changed("SELECT count(*) FROM provenance WHERE record_type = 'facility' "
                           "AND record_id = ? AND agent = ? AND source_url = ? "
                           "AND retrieved_at IS NOT DISTINCT FROM CAST(? AS DATE) "
                           "AND confidence = ?", [fid, value, *row]):
                con.execute("DELETE FROM provenance WHERE record_type = 'facility' "
                            "AND record_id = ? AND agent = ?", [fid, value])
                con.execute("INSERT INTO provenance (record_type, record_id, source_url, "
                            "retrieved_at, confidence, agent) VALUES ('facility', ?, ?, "
                            "CAST(? AS DATE), ?, ?)", [fid, *row, value])
                n["provenance.added"] += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="apply inside the transaction, report, roll back")
    ap.add_argument("--fixes", type=Path, default=FIXES)
    args = ap.parse_args()

    fixes = [dict(f, facility_id=lto_db.canonical_facility_id(f["facility_id"]))
             for f in read_fixes(args.fixes)]
    con = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    errors = validate(con, fixes)
    if errors:
        for e in errors:
            print(f"[error] {e}", file=sys.stderr)
        return 1
    n: Counter = Counter()
    fids = sorted({f["facility_id"] for f in fixes})
    try:
        with lto_db.transaction(con, f"apply_facility_fixes: {len(fixes)} sourced fact(s) "
                                     f"for {len(fids)} facilities ({args.fixes.name})"):
            n = apply(con, fixes)
            lto_db.assert_integrity(con, ["facilities", "provenance", *LINKS])
            if args.dry_run:
                raise _DryRun
    except _DryRun:
        pass
    summary = ", ".join(f"{k} {v}" for k, v in sorted(n.items()) if v) or "nothing to change"
    print(f"{'[dry-run] would apply' if args.dry_run else '[fixes]'} {summary} "
          f"({len(fixes)} rows, {len(fids)} facilities)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
