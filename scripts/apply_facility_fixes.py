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
    facility_ecosystems -        add|remove (blank)      ecosystem type slug
    provenance          -        add     <confidence>    <agent>: a provenance row for the
                                                         facility citing source_url. The
                                                         facility's rows of that agent become
                                                         exactly the CSV's rows for it and that
                                                         agent (one row replaces an earlier
                                                         row; several rows are all kept)
    locations           location_id  set <column>        new value (label, address, lat,
                                                         lng, role; blank = NULL)
    locations           location_id  remove (blank)      (blank)
    facility_personnel  person_id:role  set <column>     new value (title, is_current,
                                                         end_date, ...; blank = NULL)
    facility_personnel  person_id:role  remove (blank)   (blank)
    facility_personnel  person_id:role  set role         new role slug: the row's role
                                                         is renamed (a key change; the
                                                         other rows for that person then
                                                         name the new role in their key).
                                                         Applied before every other set;
                                                         a no-op once the old key is gone
                                                         and the new one is there
    facility_archives   archive_id   set <column>        new value (role, scope_url,
                                                         scope_id, sample_doi, notes)
    facility_archives   archive_id   remove (blank)      (blank)
    data_products       product_id   set <column>        new value (url, title, ...)
    data_products       product_id   remove (blank)      (blank)
    data_products       product_id   assign (blank)      (blank): the product belongs to
                                                         this row's facility_id; it is
                                                         moved there from whichever
                                                         facility holds it (no-op once it
                                                         is there)
    funding_events      event_id     set <column>        new value (source_url, ...)
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
facility it was kept as (lto_db.canonical_facility_id), except a keyed
remove on the duplicate: that is cleanup run before the merge
(data/seed/facility_fixes_premerge.csv, passed with --fixes), applied to the duplicate while it is in the lake and skipped
once it is gone, since its key may name a row the survivor holds itself.
Values are written
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
    "facility_ecosystems": ("ecosystem_slug", "ecosystem_types", "slug"),
}
# Keyed tables: the key column(s) the CSV `key` names (':'-separated), the
# actions each takes, and the columns a `set` may not touch.
KEYED = {
    "locations": (["location_id"], {"set", "remove"}),
    "facility_personnel": (["person_id", "role"], {"set", "remove"}),
    "facility_archives": (["archive_id"], {"set", "remove"}),
    "data_products": (["product_id"], {"set", "remove", "assign"}),
    "funding_events": (["event_id"], {"set", "remove"}),
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


def is_role_rename(f: dict) -> bool:
    return f["table"] == "facility_personnel" and f["action"] == "set" and f["field"] == "role"


def renamed_keys(fixes: list[dict]) -> set[tuple[str, str]]:
    """(facility_id, person_id:new_role) for every role rename in the file."""
    return {(f["facility_id"], f"{f['key'].split(':', 1)[0]}:{f['value']}")
            for f in fixes if is_role_rename(f)}


def validate(con, fixes: list[dict]) -> list[str]:
    errors = []
    types = {t: column_types(con, t) for t in ["facilities", *KEYED]}
    have = {r[0] for r in lto_db.rows(con, "SELECT facility_id FROM facilities")}
    renamed = renamed_keys(fixes)
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
            if a == "set" and is_role_rename(f):
                cond, params = key_where(t, f["key"])
                new_key = f"{f['key'].split(':', 1)[0]}:{f['value']}"
                ncond, nparams = key_where(t, new_key)
                old_n = lto_db.scalar(con, f"SELECT count(*) FROM {t} WHERE facility_id = ? "
                                           f"AND {cond}", [f["facility_id"], *params])
                new_n = lto_db.scalar(con, f"SELECT count(*) FROM {t} WHERE facility_id = ? "
                                           f"AND {ncond}", [f["facility_id"], *nparams])
                roles = {r["slug"] for r in csv.DictReader(
                    (ROOT / "schema" / "vocab" / "personnel_roles.csv").open(encoding="utf-8"))}
                if f["value"] not in roles:
                    errors.append(f"{where}: {f['value']!r} not in personnel_roles.csv")
                if not f["value"] or (old_n and new_n) or not (old_n or new_n):
                    errors.append(f"{where}: a role rename needs the old row and not the new "
                                  f"one (or, once applied, only the new one)")
            elif a == "set":
                if f["field"] not in types[t] or f["field"] in NO_SET | set(cols):
                    errors.append(f"{where}: {t} takes 'set <column>' (not a key column)")
                    continue
                cond, params = key_where(t, f["key"])
                if not lto_db.scalar(con, f"SELECT count(*) FROM {t} WHERE facility_id = ? "
                                          f"AND {cond}", [f["facility_id"], *params]) \
                        and (f["facility_id"], f["key"]) not in renamed:
                    errors.append(f"{where}: {f['facility_id']} has no {t} row {f['key']}")
            elif a == "assign":
                if f["field"] or f["value"]:
                    errors.append(f"{where}: {t} assign takes no field / value")
                elif not lto_db.scalar(con, f"SELECT count(*) FROM {t} WHERE product_id = ?",
                                       [f["key"]]):
                    errors.append(f"{where}: no {t} row {f['key']}")
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

    # Removals first, so a primary sphere can be swapped in one file; then
    # role renames, so a set keyed on the new role finds its row.
    order = sorted(fixes, key=lambda f: (f["action"] != "remove", not is_role_rename(f)))
    for f in order:
        fid, t, a, field, value = (f["facility_id"], f["table"], f["action"],
                                   f["field"], f["value"])
        if is_role_rename(f):
            cond, params = key_where(t, f["key"])
            if changed(f"SELECT count(*) FROM {t} WHERE facility_id = ? AND {cond}",
                       [fid, *params]):
                pid = f["key"].split(":", 1)[0]
                if changed(f"SELECT count(*) FROM {t} WHERE facility_id = ? AND person_id = ? "
                           f"AND role = ?", [fid, pid, value]):
                    raise RuntimeError(f"{fid} {t} {f['key']}: role rename to {value!r} "
                                       f"collides with an existing row")
                con.execute(f"UPDATE {t} SET role = ? WHERE facility_id = ? AND {cond}",
                            [value, fid, *params])
                n[f"{t}.role"] += 1
        elif t == "data_products" and a == "assign":
            if changed("SELECT count(*) FROM data_products WHERE product_id = ? "
                       "AND facility_id IS DISTINCT FROM ?", [f["key"], fid]):
                con.execute("UPDATE data_products SET facility_id = ? WHERE product_id = ?",
                            [fid, f["key"]])
                n[f"{t}.assigned"] += 1
        elif t == "facilities" or (t in KEYED and a == "set"):
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
    # Provenance: per (facility, agent), the lake's rows become the CSV's rows.
    want: dict[tuple[str, str], list[tuple]] = {}
    for f in fixes:
        if f["table"] == "provenance":
            row = (f["source_url"], f["retrieved_at"] or None, f["field"])
            rows_ = want.setdefault((f["facility_id"], f["value"]), [])
            if row not in rows_:
                rows_.append(row)
    for (fid, agent), rows_ in want.items():
        have = lto_db.rows(con, "SELECT source_url, CAST(retrieved_at AS VARCHAR), confidence "
                                "FROM provenance WHERE record_type = 'facility' "
                                "AND record_id = ? AND agent = ?", [fid, agent])
        if sorted(map(tuple, have), key=str) == sorted(rows_, key=str):
            continue
        con.execute("DELETE FROM provenance WHERE record_type = 'facility' "
                    "AND record_id = ? AND agent = ?", [fid, agent])
        for row in rows_:
            con.execute("INSERT INTO provenance (record_type, record_id, source_url, "
                        "retrieved_at, confidence, agent) VALUES ('facility', ?, ?, "
                        "CAST(? AS DATE), ?, ?)", [fid, *row, agent])
        n["provenance.added"] += len(rows_)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="apply inside the transaction, report, roll back")
    ap.add_argument("--fixes", type=Path, default=FIXES)
    args = ap.parse_args()

    con = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    present = {r[0] for r in lto_db.rows(con, "SELECT facility_id FROM facilities")}

    def target(f: dict) -> str | None:
        # A keyed remove on a merged duplicate is pre-merge cleanup (a row
        # merge_facilities must not move): while the duplicate is still in
        # the lake it applies there, even once the merge log already names
        # the merge (a replay from older parquet). Once the duplicate is gone
        # the row is skipped, never redirected: its key (an archive_id, a
        # person_id:role) can name a row the survivor holds in its own right.
        # Every other row follows the merge log to the survivor.
        fid = (f["facility_id"] or "").strip()
        if f["action"] == "remove" and f["table"] in KEYED:
            if fid in present:
                return fid
            if lto_db.canonical_facility_id(fid) != fid:
                return None
        return lto_db.canonical_facility_id(fid)

    fixes, skipped = [], []
    for f in read_fixes(args.fixes):
        t = target(f)
        if t is None:
            skipped.append(f)
        else:
            fixes.append(dict(f, facility_id=t))
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
    if skipped:
        print(f"[{'dry-run' if args.dry_run else 'skip'}] {len(skipped)} pre-merge "
              f"remove(s) skipped (their facility is merged away):")
        for f in skipped:
            print(f"    {f['facility_id']} {f['table']} {f['key']}")
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
