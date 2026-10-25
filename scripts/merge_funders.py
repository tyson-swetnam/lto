#!/usr/bin/env python3
"""Merge `funders` rows that are the same funder — on a reviewed pair.

Input
  data/seed/funder_merge_seed.csv   survivor_id, duplicate_id, aliases,
                                    evidence: one reviewed pair per row.
                                    aliases (optional, '|'-separated) are
                                    further spellings a writer may mint for
                                    the survivor (e.g. the USAspending
                                    top-tier name 'Environmental Protection
                                    Agency'); their ids are redirected too

The survivor is chosen so the live fetchers keep minting it (NSF's survivor
is the blake2b id fetch_funding_nsf mints, not ingest.py's sha1('nsf')).

For each pair whose duplicate is still in the lake:

  funding_events       every event of the duplicate is re-keyed with the
                       hash family that minted it, the funder swapped:
                         ingest.py stub          sha1(funder|facility)
                         load_lto_funding /
                         seed_funding_events_sample
                                                 sha1(funder|facility|award|fy)
                         fetch_funding_nsf /
                         _usaspending            blake2b(funder|facility|award|fy)
                         load_agency_budgets     blake2b(funder|facility|agency-budget|fy)
                         fetch_funding_990       blake2b(funder|facility|ein|fy|990)
                       An id no family reproduces stops the run. When the
                       new id already exists the two rows must be the same
                       event (same facility, award_id, fiscal_year and
                       amount_usd); the duplicate's row is then dropped and
                       any relation, source, source_url or confidence it
                       carried that the kept row does not is recorded in
                       the merge log. A collision between
                       different events stops the run.
  funder_area_funding  the duplicate's rows are deleted (derived; recompute
                       with compute_area_metrics.py)
  funders              the survivor's NULL / empty columns (type, country,
                       url, notes) are filled from the duplicate, its own
                       values always win; then the duplicate is deleted

funding_links and v_funder_funding_by_year are views over funding_events
and follow on their own. Afterwards no lake table column named funder_id
may still hold a merged id, and no funder row may carry an id the merge
log redirects, or the run stops.

One lake transaction (one snapshot), checked with lto_db.assert_integrity.
Each merge is appended to data/seed/funder_merge_log.csv (kept_id,
kept_name, merged_id, merged_name, aliases, evidence, notes, merged_at;
with a non-default catalog, <catalog dir>/funder_merge_log.csv unless --log
is given). Writers send a minted id through lto_db.canonical_funder(), which
reads that log, so 'NSF' from ingest.py or a raw record lands on the
survivor under the survivor's name; qa.py fails if a redirected id is back
in funders.

Idempotent: a pair whose duplicate is already gone is skipped.

Then re-run compute_area_metrics.py (funder_area_funding,
facility_area_funding), qa.py, export_parquet.py, export_view_caches.py.

Usage::

    python scripts/merge_funders.py --dry-run   # every change, rolled back
    python scripts/merge_funders.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MERGE_SEED = ROOT / "data" / "seed" / "funder_merge_seed.csv"
MERGE_LOG = lto_db.FUNDER_MERGE_LOG
LOG_COLS = ["kept_id", "kept_name", "merged_id", "merged_name", "aliases",
            "evidence", "notes", "merged_at"]
FILL = ["type", "country", "url", "notes"]
DERIVED = ["funder_area_funding"]


class _DryRun(Exception):
    pass


def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def blake16(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=8).hexdigest()


def rekey_event_id(event_id: str, old: str, new: str, fac: str,
                   award: str | None, fy, amount) -> str | None:
    """``event_id`` re-derived for funder ``new`` with the hash family that
    minted it for funder ``old`` (module docstring); None when no family
    reproduces it."""
    fys = "" if fy is None else str(fy)
    fams = []
    if award is None and amount is None:
        fams.append(lambda f: sha16(f"{f}|{fac}"))                       # ingest stub
    fams += [
        lambda f: sha16(f"{f}|{fac}|{(award or '').strip()}|{fys}"),    # load_lto_funding
        lambda f: blake16(f"{f}|{fac}|{award or ''}|{fys}"),             # nsf / usaspending
        lambda f: blake16(f"{f}|{fac}|agency-budget|{fys}"),             # load_agency_budgets
    ]
    m = re.fullmatch(r"EIN-(.+)-FY(\d+)", award or "")
    if m:
        ein, efy = m.groups()
        fams.append(lambda f: blake16(f"{f}|{fac}|{ein}|{int(efy)}|990"))  # fetch_funding_990
    for fam in fams:
        if fam(old) == event_id:
            return fam(new)
    return None


def read_seed(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        out = []
        for r in csv.DictReader(fh):
            keep, dup = (r.get("survivor_id") or "").strip(), (r.get("duplicate_id") or "").strip()
            if keep and dup and keep != dup:
                out.append({"keep": keep, "dup": dup,
                            "aliases": "|".join(a.strip() for a in (r.get("aliases") or "").split("|")
                                                if a.strip()),
                            "evidence": (r.get("evidence") or "").strip()})
        return out


def funder_id_columns(con) -> list[tuple[str, str]]:
    return lto_db.rows(
        con, "SELECT table_name, column_name FROM duckdb_columns() WHERE database_name = ? "
             "AND schema_name = 'main' AND column_name = 'funder_id' "
             "AND table_name IN (SELECT table_name FROM duckdb_tables() "
             "  WHERE database_name = ? AND schema_name = 'main') ORDER BY ALL",
        [lto_db.LAKE, lto_db.LAKE])


def merge_pair(con, keep: str, dup: str) -> tuple[Counter, dict, list[str]]:
    """Move or drop every row naming funder ``dup``. Call inside a
    transaction. Returns per-table counts, the survivor columns filled, and
    notes for the merge log."""
    n: Counter = Counter()
    notes: list[str] = []
    present = set(lto_db.lake_tables(con))
    ev_cols = ["event_id", "facility_id", "award_id", "fiscal_year", "amount_usd", "relation",
               "source", "source_url", "confidence"]
    for ev, fac, award, fy, amount, relation, *cite in lto_db.rows(
            con, f"SELECT {', '.join(ev_cols)} FROM funding_events WHERE funder_id = ? "
                 f"ORDER BY event_id", [dup]):
        new_id = rekey_event_id(ev, dup, keep, fac, award, fy, amount)
        if new_id is None:
            raise RuntimeError(f"funding_events {ev} ({award}, FY{fy}) of {dup}: no known hash "
                               f"family reproduces its id; re-key it by hand")
        other = lto_db.rows(con, f"SELECT {', '.join(ev_cols)}, funder_id FROM funding_events "
                                 f"WHERE event_id = ?", [new_id])
        if other:
            o = dict(zip(ev_cols + ["funder_id"], other[0]))
            same = (o["funder_id"] == keep and o["facility_id"] == fac and o["award_id"] == award
                    and o["fiscal_year"] == fy and o["amount_usd"] == amount)
            if not same:
                raise RuntimeError(f"funding_events {ev} of {dup} re-keys to {new_id}, which is a "
                                   f"different event ({o}); resolve by hand")
            con.execute("DELETE FROM funding_events WHERE event_id = ?", [ev])
            n["funding_events.dropped"] += 1
            note = f"event {ev} on {fac} dropped as the same event as {new_id}"
            if relation and relation != o["relation"]:
                note += f" (its relation {relation!r} lost; kept {o['relation']!r})"
            # A dropped row's citation is recorded wherever it differs from
            # the kept row's, so nothing it said vanishes without a trace.
            for col, val in zip(["source", "source_url", "confidence"], cite):
                if val not in (None, "") and val != o[col]:
                    note += f" (its {col} {val!r}; kept {o[col]!r})"
            notes.append(note)
        else:
            con.execute("UPDATE funding_events SET event_id = ?, funder_id = ? WHERE event_id = ?",
                        [new_id, keep, ev])
            n["funding_events.moved"] += 1

    for table in DERIVED:
        if table in present:
            n[f"{table}.deleted"] = lto_db.scalar(
                con, f"SELECT count(*) FROM {table} WHERE funder_id = ?", [dup]) or 0
            con.execute(f"DELETE FROM {table} WHERE funder_id = ?", [dup])

    k_row = dict(zip(FILL, lto_db.rows(con, f"SELECT {', '.join(FILL)} FROM funders "
                                            f"WHERE funder_id = ?", [keep])[0]))
    d_row = dict(zip(FILL, lto_db.rows(con, f"SELECT {', '.join(FILL)} FROM funders "
                                            f"WHERE funder_id = ?", [dup])[0]))
    fill = {c: d_row[c] for c in FILL if k_row[c] in (None, "") and d_row[c] not in (None, "")}
    if fill:
        con.execute(f"UPDATE funders SET {', '.join(f'{c} = ?' for c in fill)} "
                    f"WHERE funder_id = ?", [*fill.values(), keep])
    n["funders.filled"] = len(fill)
    con.execute("DELETE FROM funders WHERE funder_id = ?", [dup])
    return n, fill, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="run every change inside the transaction, report, roll back")
    ap.add_argument("--seed", type=Path, default=MERGE_SEED)
    ap.add_argument("--log", type=Path, default=None,
                    help=f"merge log to append to (default {MERGE_LOG.relative_to(ROOT)}; "
                         f"with a non-default catalog, <catalog dir>/{MERGE_LOG.name})")
    args = ap.parse_args()
    if args.log is None:
        args.log = (MERGE_LOG if lto_db.is_default_catalog(args.catalog)
                    else lto_db.catalog_path(args.catalog).parent / MERGE_LOG.name)

    pairs = read_seed(args.seed)
    con = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    have = dict(lto_db.rows(con, "SELECT funder_id, name FROM funders"))
    todo, errors = [], []
    for p in pairs:
        p["keep"] = lto_db.canonical_funder_id(p["keep"])
        if p["dup"] not in have:
            print(f"  [skip] {p['dup']} not in funders (already merged)")
            continue
        if p["keep"] not in have:
            errors.append(f"survivor {p['keep']} of {p['dup']} is not in funders")
            continue
        todo.append(p)
    dups = {p["dup"] for p in todo}
    errors += [f"{p['keep']} is both a survivor and a duplicate" for p in todo if p["keep"] in dups]
    if errors:
        for e in errors:
            print(f"[error] {e}", file=sys.stderr)
        return 1
    if not todo:
        print("[merge] nothing to merge")
        return 0

    # The ids this merge will redirect (merged ids, and both hash families'
    # ids for every merged name, alias and kept name) must not be live
    # funders other than the duplicates being merged.
    redirected: dict[str, str] = {}
    for p in todo:
        for nm in [have[p["dup"]], have[p["keep"]], *p["aliases"].split("|")]:
            for i in lto_db.funder_name_ids(nm):
                if i != p["keep"]:
                    redirected.setdefault(i, p["keep"])
        redirected[p["dup"]] = p["keep"]
    clash = sorted(i for i in redirected if i in have and i not in dups)
    if clash:
        for i in clash:
            print(f"[error] {i} ({have[i]}) would be redirected to {redirected[i]} but is a live "
                  f"funder outside the seed; add it as a pair or drop the alias", file=sys.stderr)
        return 1

    total: Counter = Counter()
    log_rows = []
    try:
        with lto_db.transaction(con, f"merge_funders: {len(todo)} duplicate funders merged "
                                     f"into their survivors ({args.seed.name})"):
            for p in todo:
                n, filled, notes = merge_pair(con, p["keep"], p["dup"])
                total.update(n)
                moved = ", ".join(f"{k} {v}" for k, v in sorted(n.items()) if v) or "no rows"
                print(f"  keep {have[p['keep']]} ({p['keep']})")
                print(f"    <- {have[p['dup']]} ({p['dup']}): {moved}")
                if filled:
                    print(f"       filled on survivor: {filled}")
                for note in notes:
                    print(f"       {note}")
                log_rows.append([p["keep"], have[p["keep"]], p["dup"], have[p["dup"]],
                                 p["aliases"], p["evidence"], "; ".join(notes),
                                 date.today().isoformat()])
            left = []
            for table, col in funder_id_columns(con):
                c = lto_db.scalar(con, f"SELECT count(*) FROM {lto_db.qident(table)} "
                                       f"WHERE {col} IN (SELECT unnest(?::VARCHAR[]))",
                                  [sorted(redirected)])
                if c:
                    left.append(f"{table}.{col} {c}")
            if left:
                raise RuntimeError(f"rows still name a merged funder: {', '.join(left)}")
            present = set(lto_db.lake_tables(con))
            lto_db.assert_integrity(con, ["funders", "funding_events"]
                                    + [t for t in DERIVED if t in present])
            if args.dry_run:
                raise _DryRun
    except _DryRun:
        print(f"[dry-run] would merge {len(todo)} funders; totals: "
              + ", ".join(f"{k} {v}" for k, v in sorted(total.items()) if v))
        return 0

    new = not args.log.exists()
    with args.log.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        if new:
            w.writerow(LOG_COLS)
        w.writerows(log_rows)
    print(f"[merge] merged {len(todo)} funders; totals: "
          + ", ".join(f"{k} {v}" for k, v in sorted(total.items()) if v)
          + f"; log {args.log}")
    print("[next] compute_area_metrics.py; qa.py; export_parquet.py; export_view_caches.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
