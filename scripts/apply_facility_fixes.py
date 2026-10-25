#!/usr/bin/env python3
"""Apply reviewed, sourced corrections to facilities and the rows that hang off them.

Input
  data/seed/facility_fixes.csv   one fact per row:
      facility_id, table, key, action, field, value, source_url, retrieved_at, evidence

  table / key / action / field / value:
    facilities          -        set     <column>        new value (cast to the column
                                                         type; blank = NULL)
    facility_spheres    -        add     primary|secondary  sphere slug
    facility_spheres    -        remove  (blank)         sphere slug
    network_membership  -        add|remove (blank)      network_id
    area_links          -        add|remove (blank)      research area slug
    provenance          -        add     <confidence>    <agent>: a provenance row for the
                                                         facility citing source_url, replacing
                                                         an earlier row of the same agent
    locations           location_id  set <column>        new value (label, address, lat,
                                                         lng, role; blank = NULL)
    locations           location_id  remove (blank)      (blank)
    facility_personnel  person_id:role  set <column>     new value (title, is_current,
                                                         end_date, ...; blank = NULL)
    facility_personnel  person_id:role  remove (blank)   (blank)
    facility_archives   archive_id   set <column>        new value (role, scope_url,
                                                         scope_id, sample_doi, notes)
    funding_events      event_id     remove (blank)      (blank): delete the event
    funding_events      event_id     remove superseded-by-award  <source>: delete the
                                                         event only once the facility has
                                                         an event from that source (e.g.
                                                         'NSF Award Search') with an
                                                         award_id and an amount (an
                                                         award-less stub that a fetched
                                                         award replaces; run the funding
                                                         fetch first)

  The keyed tables name one existing row of the facility; a set on a row the
  facility does not have stops the run, a remove of a row already gone is a
  no-op (that is what makes a second run change nothing). --dry-run lists
  the removes whose key matches no row, so a mistyped key is visible.

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
# Keyed tables: the key column(s) the CSV `key` names (':'-separated), the
# actions each takes, and the columns a `set` may not touch.
KEYED = {
    "locations": (["location_id"], {"set", "remove"}),
    "facility_personnel": (["person_id", "role"], {"set", "remove"}),
    "facility_archives": (["archive_id"], {"set"}),
    "funding_events": (["event_id"], {"remove"}),
}
REMOVE_GUARDS = {"", "superseded-by-award"}
NO_SET = {"facility_id", "created_at"}


class _DryRun(Exception):
    pass


def read_fixes(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]


def column_types(con, table: str) -> dict[str, str]:
    return dict(lto_db.rows(
        con, "SELECT column_name, data_type FROM duckdb_columns() WHERE database_name = ? "
             "AND schema_name = 'main' AND table_name = ?", [lto_db.LAKE, table]))


def key_where(table: str, key: str) -> tuple[str, list[str]]:
    cols = KEYED[table][0]
    parts = key.split(":", len(cols) - 1)
    return " AND ".join(f"{c} = ?" for c in cols), parts


def validate(con, fixes: list[dict]) -> list[str]:
    errors = []
    types = {t: column_types(con, t) for t in ["facilities", *KEYED]}
    have = {r[0] for r in lto_db.rows(con, "SELECT facility_id FROM facilities")}
    for i, f in enumerate(fixes, start=2):
        where = (f"line {i} ({f.get('table')} {f.get('key') or ''} {f.get('action')} "
                 f"{f.get('field')} {f.get('value')!r})")
        if not f["source_url"] or not f["evidence"]:
            errors.append(f"{where}: no source_url / evidence")
        if f["facility_id"] not in have:
            errors.append(f"{where}: unknown facility_id {f['facility_id']}")
        t, a = f["table"], f["action"]
        if t == "facilities":
            if a != "set" or f["field"] not in types[t] or f["field"] in NO_SET:
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
        elif t in KEYED:
            cols, actions = KEYED[t]
            if a not in actions:
                errors.append(f"{where}: {t} takes {' / '.join(sorted(actions))}")
                continue
            if len(f["key"].split(":", len(cols) - 1)) != len(cols) or not all(
                    f["key"].split(":", len(cols) - 1)):
                errors.append(f"{where}: {t} needs key {':'.join(cols)}")
                continue
            if a == "set":
                if f["field"] not in types[t] or f["field"] in NO_SET | set(cols):
                    errors.append(f"{where}: {t} takes 'set <column>' (not a key column)")
                    continue
                cond, params = key_where(t, f["key"])
                if not lto_db.scalar(con, f"SELECT count(*) FROM {t} WHERE facility_id = ? "
                                          f"AND {cond}", [f["facility_id"], *params]):
                    errors.append(f"{where}: {f['facility_id']} has no {t} row {f['key']}")
            elif t == "funding_events":
                if f["field"] not in REMOVE_GUARDS or bool(f["field"]) != bool(f["value"]):
                    errors.append(f"{where}: funding_events remove takes field and value "
                                  f"blank, or 'superseded-by-award <source>'")
            elif f["field"] or f["value"]:
                errors.append(f"{where}: {t} remove takes no field / value")
        else:
            errors.append(f"{where}: unknown table {t!r}")
    return errors


def apply(con, fixes: list[dict], absent: list[str] | None = None) -> Counter:
    """Apply the fixes; returns per-change counts. A keyed remove whose row is
    already gone is appended to ``absent`` (``facility_id table key``)."""
    n: Counter = Counter()
    types = {t: column_types(con, t) for t in ["facilities", *KEYED]}

    def changed(sql: str, params) -> int:
        return lto_db.scalar(con, sql, params) or 0

    # Removals first, so a primary sphere can be swapped in one file.
    order = sorted(fixes, key=lambda f: (f["action"] != "remove"))
    for f in order:
        fid, t, a, field, value = (f["facility_id"], f["table"], f["action"],
                                   f["field"], f["value"])
        if t == "facilities" or (t in KEYED and a == "set"):
            typ = types[t][field]
            val = value if value != "" else None
            cond, params = ("1 = 1", []) if t == "facilities" else key_where(t, f["key"])
            if changed(f"SELECT count(*) FROM {t} WHERE facility_id = ? AND {cond} "
                       f"AND {field} IS DISTINCT FROM CAST(? AS {typ})", [fid, *params, val]):
                con.execute(f"UPDATE {t} SET {field} = CAST(? AS {typ}) "
                            f"WHERE facility_id = ? AND {cond}", [val, fid, *params])
                n[f"{t}.{field}"] += 1
        elif t in KEYED:          # remove
            cond, params = key_where(t, f["key"])
            k = changed(f"SELECT count(*) FROM {t} WHERE facility_id = ? AND {cond}",
                        [fid, *params])
            if not k:
                if absent is not None:
                    absent.append(f"{fid} {t} {f['key']}")
                continue
            if t == "funding_events" and field == "superseded-by-award" and not changed(
                    "SELECT count(*) FROM funding_events WHERE facility_id = ? "
                    "AND source = ? AND award_id IS NOT NULL AND amount_usd IS NOT NULL",
                    [fid, value]):
                n[f"{t}.kept_no_award_yet"] += 1
                continue
            con.execute(f"DELETE FROM {t} WHERE facility_id = ? AND {cond}", [fid, *params])
            n[f"{t}.removed"] += k
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
    absent: list[str] = []
    fids = sorted({f["facility_id"] for f in fixes})
    try:
        with lto_db.transaction(con, f"apply_facility_fixes: {len(fixes)} sourced fact(s) "
                                     f"for {len(fids)} facilities ({args.fixes.name})"):
            n = apply(con, fixes, absent)
            lto_db.assert_integrity(con, ["facilities", "provenance", *LINKS, *KEYED])
            if args.dry_run:
                raise _DryRun
    except _DryRun:
        pass
    summary = ", ".join(f"{k} {v}" for k, v in sorted(n.items()) if v) or "nothing to change"
    if args.dry_run and absent:
        print(f"[dry-run] {len(absent)} remove(s) name a row that is not there (already "
              f"removed, or a mistyped key):")
        for a in absent:
            print(f"    {a}")
    print(f"{'[dry-run] would apply' if args.dry_run else '[fixes]'} {summary} "
          f"({len(fixes)} rows, {len(fids)} facilities)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
