#!/usr/bin/env python3
"""Merge `facilities` rows that are the same facility — on a reviewed pair.

Input
  data/seed/facility_merge_seed.csv   survivor_id, duplicate_id, evidence,
                                      location_label, drop_personnel: one
                                      reviewed pair per row, the evidence
                                      cited (the site's official page, a
                                      shared ROR, an archive scope naming
                                      it); location_label (optional) names
                                      the duplicate's own point when it is
                                      moved (see locations); drop_personnel
                                      (optional) lists the duplicate's
                                      facility_personnel rows that must not
                                      move, as space-separated
                                      person_id:role pairs (see below)

For each pair whose duplicate is still in the lake, everything that names
the duplicate is moved onto the survivor or dropped, then the duplicate is
deleted:

  facility_personnel   rows named in the seed's drop_personnel are deleted
                       first, not moved (a network-level role the bulk
                       import attached to every node, e.g. a network
                       director, is not a role at the survivor); a pair
                       that names a row the duplicate does not have stops
                       the run. The rest are
                       repointed; where the survivor already has the same
                       (person_id, role) the better-attested row survives:
                       a row with evidence first, then dedupe_people's
                       _FP_RANK (is_current true over unknown over false,
                       then evidence, then the later retrieved_at); a tie
                       keeps the survivor's row. Evidence leads here because
                       the two copies come from different bulk passes: a
                       verified "no longer holds the role" (is_current
                       false) beats an unsourced copy with is_current NULL
  facility_archives    repointed; on the same archive_id the survivor's row
                       stays and its empty role / scope_url / scope_id /
                       sample_doi / notes are filled from the duplicate's
  data_products, api_endpoints, cloud_buckets, projects.lead_facility_id
                       facility_id updated (their keys do not include it)
  project_facilities, registry_facilities
                       repointed; a row the survivor already has is dropped
  facility_spheres, network_membership, area_links, facility_ecosystems,
  facility_life_zones, facility_regions
                       the survivor's set is the curated one: when it has
                       any row in the table the duplicate's rows are dropped,
                       not added (a bulk-imported duplicate carries generic
                       tags — a blanket coastal area set, an 'lter-site'
                       membership no other site row has); only when it has
                       none are the duplicate's rows moved
  locations            a duplicate point within 1 km of one of the
                       survivor's locations or of its hq_lat/hq_lng is
                       dropped; any other is moved, its location_id
                       re-minted as ingest.py mints it,
                       sha1(facility_id|label)[:16]. A moved point labelled
                       with the duplicate's canonical_name (a bulk import's
                       default point) is relabelled with the seed's
                       location_label, or "<survivor acronym> site point"
                       when the seed gives none, so the retired name does
                       not reappear under the survivor
  funding_events       an award-less stub (no award_id, no amount) gets the
                       id ingest.py would mint for the survivor,
                       sha1(funder_id|facility_id)[:16], and is dropped
                       when the survivor already has it (only when its id
                       is that stub id for the duplicate); any other event
                       is re-keyed with the hash family that minted it
                       (load_lto_funding's sha1, the fetch_funding_nsf /
                       _usaspending blake2b, or fetch_funding_990's blake2b
                       over the EIN in award_id 'EIN-<ein>-FY<fy>') and
                       dropped on a collision; an id no known family
                       reproduces stops the run
  provenance           the duplicate's rows are deleted (the merge log is
                       the trace; the survivor keeps its own)
  facilities           the survivor's NULL columns are filled from the
                       duplicate (its own values always win), then the
                       duplicate is deleted
  facility_primary_groups, facility_area_funding
                       the duplicate's rows are deleted (derived; recompute)

Afterwards no column named facility_id or lead_facility_id in any lake
table may still hold a merged id, or the run stops.

One lake transaction (one snapshot), checked with lto_db.assert_integrity on
every touched table before commit. Each merge is appended to
data/seed/facility_merge_log.csv (kept_id, merged_id, evidence, merged_at;
with a non-default catalog, <catalog dir>/facility_merge_log.csv unless
--log is given, so a scratch rehearsal never touches the committed log);
loaders read that log through lto_db.canonical_facility_id, ingest.py drops a
raw record whose id is in it, and qa.py fails if a merged id is back.

Idempotent: a pair whose duplicate is already gone is skipped.

Then re-run backfill_facility_state.py and compute_collaborations ->
compute_person_areas -> compute_primary_groups -> compute_area_metrics ->
build_mvg_layout, qa.py, export_parquet.py, export_view_caches.py.

Usage::

    python scripts/merge_facilities.py --dry-run   # every change, rolled back
    python scripts/merge_facilities.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from dedupe_people import _FP_RANK  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MERGE_SEED = ROOT / "data" / "seed" / "facility_merge_seed.csv"
MERGE_LOG = lto_db.FACILITY_MERGE_LOG
NEAR_KM = 1.0
# facility_personnel copy rank for a facility merge: evidence first, then
# dedupe_people's rank (module docstring).
_MERGE_FP_RANK = ("[CASE WHEN {t}.evidence IS NOT NULL THEN 1 ELSE 0 END, "
                  + _FP_RANK.strip("[]") + "]")

# Facet tables keyed (facility_id, <slug>): the survivor's set wins.
FACET_KEYS = {
    "facility_spheres": "sphere_slug",
    "network_membership": "network_id",
    "area_links": "area_id",
    "facility_ecosystems": "ecosystem_slug",
    "facility_life_zones": "life_zone_slug",
    "facility_regions": "region_id",
}
# Repointed; a row whose other key columns the survivor already has is dropped.
REPOINT_KEYS = {
    "project_facilities": ["project_id", "relation"],
    "registry_facilities": ["canonical_id"],
}
# facility_id is not part of the key: just updated.
UPDATE_ONLY = ["data_products", "api_endpoints", "cloud_buckets"]
ARCHIVE_FILL = ["role", "scope_url", "scope_id", "sample_doi", "notes"]
DERIVED = ["facility_primary_groups", "facility_area_funding"]


class _DryRun(Exception):
    pass


def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def blake16(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=8).hexdigest()


def stub_event_id(funder: str, fid: str) -> str:
    """ingest.py's funder stub: location_id(funder_id, facility_id)."""
    return sha16(f"{funder}|{fid}")


def award_event_id(event_id: str, funder: str, dup: str, keep: str,
                   award: str | None, fy) -> str | None:
    """Re-derive an award event's id for ``keep`` with the hash family that
    minted ``event_id`` for ``dup``; None when no family reproduces it."""
    fy = "" if fy is None else str(fy)
    families = [
        # load_lto_funding.event_id
        lambda fid: sha16(f"{funder}|{fid}|{award or ''}|{fy}"),
        # fetch_funding_nsf / fetch_funding_usaspending event_id_for
        lambda fid: blake16(f"{funder}|{fid}|{award or ''}|{fy}"),
    ]
    m = re.fullmatch(r"EIN-(.+)-FY(\d+)", award or "")
    if m:
        # fetch_funding_990.event_id_for: award_id is f"EIN-{ein}-FY{fy}"
        ein, efy = m.groups()
        families.append(lambda fid: blake16(f"{funder}|{fid}|{ein}|{int(efy)}|990"))
    for fam in families:
        if fam(dup) == event_id:
            return fam(keep)
    return None


def haversine_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    x = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(x))


def read_seed(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        out = []
        for r in csv.DictReader(fh):
            keep, dup = (r.get("survivor_id") or "").strip(), (r.get("duplicate_id") or "").strip()
            if keep and dup and keep != dup:
                drop = []
                for item in (r.get("drop_personnel") or "").split():
                    pid, sep, role = item.partition(":")
                    if not (pid and sep and role):
                        raise SystemExit(f"[error] {path.name}: drop_personnel {item!r} of {dup} "
                                         f"is not person_id:role")
                    drop.append((pid, role))
                out.append({"keep": keep, "dup": dup, "evidence": (r.get("evidence") or "").strip(),
                            "location_label": (r.get("location_label") or "").strip(),
                            "drop_personnel": drop})
        return out


def facility_id_columns(con) -> list[tuple[str, str]]:
    return lto_db.rows(
        con, "SELECT table_name, column_name FROM duckdb_columns() WHERE database_name = ? "
             "AND schema_name = 'main' AND column_name IN ('facility_id', 'lead_facility_id') "
             "AND table_name IN (SELECT table_name FROM duckdb_tables() "
             "  WHERE database_name = ? AND schema_name = 'main') ORDER BY ALL",
        [lto_db.LAKE, lto_db.LAKE])


def merge_pair(con, keep: str, dup: str, location_label: str = "",
               drop_personnel: list[tuple[str, str]] | None = None) -> tuple[Counter, dict]:
    """Move or drop every row naming ``dup`` (module docstring). Call inside
    a transaction. Returns per-table counts and the survivor columns filled
    from the duplicate."""
    n: Counter = Counter()
    present = set(lto_db.lake_tables(con))

    def count(sql: str, params) -> int:
        return lto_db.scalar(con, sql, params) or 0

    # facility_personnel the seed says not to move (network-level roles).
    for pid, role in drop_personnel or []:
        if not count("SELECT count(*) FROM facility_personnel WHERE person_id = ? "
                     "AND facility_id = ? AND role = ?", [pid, dup, role]):
            raise RuntimeError(f"drop_personnel {pid}:{role}: {dup} has no such "
                               f"facility_personnel row")
        con.execute("DELETE FROM facility_personnel WHERE person_id = ? AND facility_id = ? "
                    "AND role = ?", [pid, dup, role])
        n["facility_personnel.not_moved"] += 1

    # facility_personnel: the better-attested copy of one (person, role) wins.
    n["facility_personnel.replaced"] = count(
        f"SELECT count(*) FROM facility_personnel k WHERE k.facility_id = ? AND EXISTS ("
        f"SELECT 1 FROM facility_personnel d WHERE d.facility_id = ? "
        f"AND d.person_id = k.person_id AND d.role = k.role "
        f"AND {_MERGE_FP_RANK.format(t='d')} > {_MERGE_FP_RANK.format(t='k')})", [keep, dup])
    con.execute(
        f"DELETE FROM facility_personnel k WHERE k.facility_id = ? AND EXISTS ("
        f"SELECT 1 FROM facility_personnel d WHERE d.facility_id = ? "
        f"AND d.person_id = k.person_id AND d.role = k.role "
        f"AND {_MERGE_FP_RANK.format(t='d')} > {_MERGE_FP_RANK.format(t='k')})", [keep, dup])
    same = ("SELECT 1 FROM facility_personnel k WHERE k.facility_id = ? "
            "AND k.person_id = d.person_id AND k.role = d.role")
    n["facility_personnel.dropped"] = count(
        f"SELECT count(*) FROM facility_personnel d WHERE d.facility_id = ? AND EXISTS ({same})",
        [dup, keep])
    con.execute(f"DELETE FROM facility_personnel d WHERE d.facility_id = ? AND EXISTS ({same})",
                [dup, keep])
    n["facility_personnel.moved"] = count(
        "SELECT count(*) FROM facility_personnel WHERE facility_id = ?", [dup])
    con.execute("UPDATE facility_personnel SET facility_id = ? WHERE facility_id = ?", [keep, dup])

    # facility_archives: the survivor's row stays, its blanks filled.
    for (archive_id,) in lto_db.rows(
            con, "SELECT d.archive_id FROM facility_archives d JOIN facility_archives k "
                 "ON k.archive_id = d.archive_id AND k.facility_id = ? "
                 "WHERE d.facility_id = ? ORDER BY 1", [keep, dup]):
        sets = ", ".join(f"{c} = COALESCE(NULLIF(facility_archives.{c}, ''), d.{c})"
                         for c in ARCHIVE_FILL)
        con.execute(f"UPDATE facility_archives SET {sets} FROM "
                    f"(SELECT * FROM facility_archives WHERE facility_id = ? AND archive_id = ?) d "
                    f"WHERE facility_archives.facility_id = ? AND facility_archives.archive_id = ?",
                    [dup, archive_id, keep, archive_id])
        con.execute("DELETE FROM facility_archives WHERE facility_id = ? AND archive_id = ?",
                    [dup, archive_id])
        n["facility_archives.coalesced"] += 1
    n["facility_archives.moved"] = count(
        "SELECT count(*) FROM facility_archives WHERE facility_id = ?", [dup])
    con.execute("UPDATE facility_archives SET facility_id = ? WHERE facility_id = ?", [keep, dup])

    for table in UPDATE_ONLY:
        if table in present:
            n[f"{table}.moved"] = count(f"SELECT count(*) FROM {table} WHERE facility_id = ?", [dup])
            con.execute(f"UPDATE {table} SET facility_id = ? WHERE facility_id = ?", [keep, dup])
    n["projects.lead_facility_id"] = count(
        "SELECT count(*) FROM projects WHERE lead_facility_id = ?", [dup])
    con.execute("UPDATE projects SET lead_facility_id = ? WHERE lead_facility_id = ?", [keep, dup])

    for table, rest in REPOINT_KEYS.items():
        if table not in present:
            continue
        on = " AND ".join(f"k.{c} = d.{c}" for c in rest)
        cond = f"d.facility_id = ? AND EXISTS (SELECT 1 FROM {table} k WHERE k.facility_id = ? AND {on})"
        n[f"{table}.dropped"] = count(f"SELECT count(*) FROM {table} d WHERE {cond}", [dup, keep])
        con.execute(f"DELETE FROM {table} d WHERE {cond}", [dup, keep])
        n[f"{table}.moved"] = count(f"SELECT count(*) FROM {table} WHERE facility_id = ?", [dup])
        con.execute(f"UPDATE {table} SET facility_id = ? WHERE facility_id = ?", [keep, dup])

    # Facets: the survivor's curated set wins over the duplicate's.
    for table, slug in FACET_KEYS.items():
        if table not in present:
            continue
        have = count(f"SELECT count(*) FROM {table} WHERE facility_id = ?", [keep])
        if have:
            n[f"{table}.dropped"] = count(f"SELECT count(*) FROM {table} WHERE facility_id = ?", [dup])
            con.execute(f"DELETE FROM {table} WHERE facility_id = ?", [dup])
        else:
            n[f"{table}.moved"] = count(f"SELECT count(*) FROM {table} WHERE facility_id = ?", [dup])
            con.execute(f"UPDATE {table} SET facility_id = ? WHERE facility_id = ?", [keep, dup])

    # locations: a point the survivor already has is dropped, any other moved.
    kept_pts = [(lat, lng) for lat, lng in lto_db.rows(
        con, "SELECT lat, lng FROM locations WHERE facility_id = ? "
             "AND lat IS NOT NULL AND lng IS NOT NULL "
             "UNION ALL SELECT hq_lat, hq_lng FROM facilities WHERE facility_id = ? "
             "AND hq_lat IS NOT NULL AND hq_lng IS NOT NULL", [keep, keep])]
    keep_acr, keep_name = lto_db.rows(
        con, "SELECT acronym, canonical_name FROM facilities WHERE facility_id = ?", [keep])[0]
    dup_name = lto_db.scalar(con, "SELECT canonical_name FROM facilities WHERE facility_id = ?",
                             [dup])
    for loc_id, label, lat, lng in lto_db.rows(
            con, "SELECT location_id, label, lat, lng FROM locations WHERE facility_id = ? "
                 "ORDER BY location_id", [dup]):
        near = (lat is not None and lng is not None
                and any(haversine_km((lat, lng), p) <= NEAR_KM for p in kept_pts))
        if near or lat is None or lng is None:
            con.execute("DELETE FROM locations WHERE location_id = ?", [loc_id])
            n["locations.dropped"] += 1
            continue
        if not label or label.strip().casefold() == (dup_name or "").strip().casefold():
            label = location_label or f"{keep_acr or keep_name} site point"
            n["locations.relabelled"] += 1
        new_id = sha16(f"{keep}|{label}")
        if lto_db.scalar(con, "SELECT count(*) FROM locations WHERE location_id = ?", [new_id]):
            raise RuntimeError(f"location {loc_id} ({label!r}) of {dup} would re-mint as "
                               f"{new_id}, which {keep} already has at another point")
        con.execute("UPDATE locations SET location_id = ?, facility_id = ?, label = ? "
                    "WHERE location_id = ?", [new_id, keep, label, loc_id])
        n["locations.moved"] += 1

    # funding_events: re-key with the id the survivor's own writer would mint.
    for ev, funder, award, fy, amount in lto_db.rows(
            con, "SELECT event_id, funder_id, award_id, fiscal_year, amount_usd "
                 "FROM funding_events WHERE facility_id = ? ORDER BY event_id", [dup]):
        if award is None and amount is None and ev == stub_event_id(funder, dup):
            new_id = stub_event_id(funder, keep)
        else:
            new_id = award_event_id(ev, funder, dup, keep, award, fy)
            if new_id is None:
                raise RuntimeError(f"funding_events {ev} ({award}) on {dup}: no known hash "
                                   f"family reproduces its id; re-key it by hand")
        if lto_db.scalar(con, "SELECT count(*) FROM funding_events WHERE event_id = ?", [new_id]):
            con.execute("DELETE FROM funding_events WHERE event_id = ?", [ev])
            n["funding_events.dropped"] += 1
        else:
            con.execute("UPDATE funding_events SET event_id = ?, facility_id = ? WHERE event_id = ?",
                        [new_id, keep, ev])
            n["funding_events.moved"] += 1

    n["provenance.deleted"] = count(
        "SELECT count(*) FROM provenance WHERE record_type = 'facility' AND record_id = ?", [dup])
    con.execute("DELETE FROM provenance WHERE record_type = 'facility' AND record_id = ?", [dup])

    for table in DERIVED:
        if table in present:
            n[f"{table}.deleted"] = count(f"SELECT count(*) FROM {table} WHERE facility_id = ?", [dup])
            con.execute(f"DELETE FROM {table} WHERE facility_id = ?", [dup])

    # facilities: fill the survivor's blanks, then drop the duplicate.
    cols = [c for c, _t in lto_db.rows(
        con, "SELECT column_name, data_type FROM duckdb_columns() WHERE database_name = ? "
             "AND schema_name = 'main' AND table_name = 'facilities' ORDER BY column_index",
        [lto_db.LAKE]) if c not in ("facility_id", "created_at")]
    k_row = dict(zip(cols, lto_db.rows(con, f"SELECT {', '.join(cols)} FROM facilities "
                                            f"WHERE facility_id = ?", [keep])[0]))
    d_row = dict(zip(cols, lto_db.rows(con, f"SELECT {', '.join(cols)} FROM facilities "
                                            f"WHERE facility_id = ?", [dup])[0]))
    fill = {c: d_row[c] for c in cols if k_row[c] in (None, "") and d_row[c] not in (None, "")}
    if fill:
        con.execute(f"UPDATE facilities SET {', '.join(f'{c} = ?' for c in fill)} "
                    f"WHERE facility_id = ?", [*fill.values(), keep])
    n["facilities.filled"] = len(fill)
    con.execute("DELETE FROM facilities WHERE facility_id = ?", [dup])
    return n, fill


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
    have = {r[0]: r[1] for r in lto_db.rows(con, "SELECT facility_id, canonical_name FROM facilities")}
    todo, errors = [], []
    for p in pairs:
        # A survivor merged away itself since the seed was written lives on
        # under the facility it went into.
        p["keep"] = lto_db.canonical_facility_id(p["keep"])
        if p["dup"] not in have:
            print(f"  [skip] {p['dup']} not in facilities (already merged)")
            continue
        if p["keep"] not in have:
            errors.append(f"survivor {p['keep']} of {p['dup']} is not in facilities")
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

    total: Counter = Counter()
    try:
        with lto_db.transaction(con, f"merge_facilities: {len(todo)} duplicate facilities merged "
                                     f"into their survivors ({args.seed.name})"):
            for p in todo:
                n, filled = merge_pair(con, p["keep"], p["dup"], p["location_label"],
                                       p["drop_personnel"])
                total.update(n)
                moved = ", ".join(f"{k} {v}" for k, v in sorted(n.items()) if v)
                print(f"  keep {have[p['keep']]} ({p['keep']})")
                print(f"    <- {have[p['dup']]} ({p['dup']}): {moved}")
                if filled:
                    print(f"       filled on survivor: {filled}")
            left = []
            for table, col in facility_id_columns(con):
                c = lto_db.scalar(con, f"SELECT count(*) FROM {lto_db.qident(table)} "
                                       f"WHERE {col} IN (SELECT unnest(?::VARCHAR[]))",
                                  [sorted(dups)])
                if c:
                    left.append(f"{table}.{col} {c}")
            if left:
                raise RuntimeError(f"rows still name a merged facility: {', '.join(left)}")
            touched = ["facilities", "facility_personnel", "facility_archives", "projects",
                       "locations", "funding_events", "provenance",
                       *UPDATE_ONLY, *REPOINT_KEYS, *FACET_KEYS]
            present = set(lto_db.lake_tables(con))
            lto_db.assert_integrity(con, [t for t in touched if t in present]
                                    + [t for t in DERIVED if t in present])
            if args.dry_run:
                raise _DryRun
    except _DryRun:
        print(f"[dry-run] would merge {len(todo)} facilities; totals: "
              + ", ".join(f"{k} {v}" for k, v in sorted(total.items()) if v))
        return 0

    new = not args.log.exists()
    with args.log.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        if new:
            w.writerow(["kept_id", "merged_id", "evidence", "merged_at"])
        for p in todo:
            w.writerow([p["keep"], p["dup"], p["evidence"], date.today().isoformat()])
    print(f"[merge] merged {len(todo)} facilities; totals: "
          + ", ".join(f"{k} {v}" for k, v in sorted(total.items()) if v)
          + f"; log {args.log}")
    print("[note] rows a merge must not move are removed beforehand, from "
          "data/seed/facility_fixes_premerge.csv (apply_facility_fixes.py --fixes)")
    print("[next] backfill_facility_state.py; compute_collaborations -> compute_person_areas -> "
          "compute_primary_groups -> compute_area_metrics -> build_mvg_layout; qa.py; "
          "export_parquet.py; export_view_caches.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
