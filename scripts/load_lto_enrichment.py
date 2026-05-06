#!/usr/bin/env python3
"""Load Q-ENRICH-* agent outputs into the LTO database.

Each Q-ENRICH-* agent writes up to 4 files:

  additional_facilities.json   — new facility rows (matching agents/README.md)
  facility_updates.json        — patches to existing rows: list of
                                  {canonical_name|acronym, field_name,
                                   old_value_seen, new_value, confidence,
                                   notes}
  additional_people.json       — same shape as R-PEOPLE-*/people.json
                                  (people[] + affiliations[])
  additional_publications.json — same shape as H-PUB-*/publications.json
                                  (publications[] + authorship[])
  additional_data_products.json — array of data_products rows
                                  (matching J-DATA.md spec)

This loader composes the existing per-domain loaders so agent output
gets folded into the right tables without duplicating dedupe logic.

Usage::

    python scripts/load_lto_enrichment.py
    python scripts/load_lto_enrichment.py --db db/cod_kmap.duckdb --verbose
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
RAW_DIR = ROOT / "data" / "raw"
ENRICH_GLOB = "Q-ENRICH-*"


def stage_for_existing_loaders(verbose: bool) -> dict:
    """Copy enrichment payload files into namespace-conformant raw dirs
    so the existing loaders pick them up via their globs.

    additional_publications.json   →  N-PUB-Q-<agent>/publications.json
    additional_data_products.json  →  M-Q-<agent>/data_products.json
    (loaders already glob N-PUB-* and M-* per their respective scripts).

    Returns a dict of staged-paths for cleanup-after-run.
    """
    staged = {}
    for agent_dir in sorted(RAW_DIR.glob(ENRICH_GLOB)):
        agent = agent_dir.name
        # Publications
        src = agent_dir / "additional_publications.json"
        if src.exists():
            dst_dir = RAW_DIR / f"N-PUB-{agent}"
            dst_dir.mkdir(exist_ok=True)
            dst = dst_dir / "publications.json"
            shutil.copyfile(src, dst)
            staged[str(dst)] = src.name
            if verbose:
                print(f"  staged {src} → {dst}")
        # Data products
        src = agent_dir / "additional_data_products.json"
        if src.exists():
            dst_dir = RAW_DIR / f"M-{agent}"
            dst_dir.mkdir(exist_ok=True)
            dst = dst_dir / "data_products.json"
            shutil.copyfile(src, dst)
            staged[str(dst)] = src.name
            if verbose:
                print(f"  staged {src} → {dst}")
    return staged


def load_additional_facilities(conn, verbose: bool) -> int:
    """Insert new facility rows from additional_facilities.json files."""
    import hashlib
    inserted = 0
    skipped = 0
    for agent_dir in sorted(RAW_DIR.glob(ENRICH_GLOB)):
        path = agent_dir / "additional_facilities.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"  [warn] {path}: {e}")
            continue
        if not isinstance(payload, list):
            print(f"  [warn] {path}: not a list")
            continue
        for r in payload:
            name = (r.get("canonical_name") or "").strip()
            acronym = (r.get("acronym") or "").strip()
            if not name:
                skipped += 1
                continue
            # Skip if a facility with this acronym OR exact name already exists.
            existing = conn.execute(
                "SELECT facility_id FROM facilities WHERE "
                "(acronym IS NOT NULL AND upper(acronym) = upper(?)) OR "
                "lower(canonical_name) = lower(?) LIMIT 1",
                [acronym, name],
            ).fetchone()
            if existing:
                if verbose:
                    print(f"  [skip] {name} ({acronym}) already in DB as {existing[0]}")
                skipped += 1
                continue
            fid = hashlib.sha1(
                (name.lower() + "|" + acronym.lower()).encode("utf-8")
            ).hexdigest()[:16]
            hq = r.get("hq") or {}
            conn.execute(
                """INSERT OR REPLACE INTO facilities (
                    facility_id, canonical_name, acronym, parent_org,
                    facility_type, country, region, hq_address, hq_lat, hq_lng,
                    url, contact, established,
                    record_length_years, long_term_threshold_met, data_portal_url,
                    created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                [
                    fid, name, acronym, r.get("parent_org"),
                    r.get("facility_type"), r.get("country") or "US", r.get("region"),
                    hq.get("address"), hq.get("lat"), hq.get("lng"),
                    r.get("url"), r.get("contact"), r.get("established"),
                    r.get("record_length_years"),
                    r.get("long_term_threshold_met"),
                    r.get("data_portal_url"),
                ],
            )
            # facility_spheres
            primary = r.get("primary_sphere")
            if primary:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO facility_spheres VALUES (?, ?, 'primary')",
                        [fid, primary],
                    )
                except duckdb.Error:
                    pass
            for sec in r.get("secondary_spheres") or []:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO facility_spheres VALUES (?, ?, 'secondary')",
                        [fid, sec],
                    )
                except duckdb.Error:
                    pass
            for eco in r.get("ecosystem_types") or []:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO facility_ecosystems VALUES (?, ?)",
                        [fid, eco],
                    )
                except duckdb.Error:
                    pass
            for net in r.get("networks") or []:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO network_membership VALUES (?, ?, NULL)",
                        [fid, net.lower() if isinstance(net, str) else net],
                    )
                except duckdb.Error:
                    pass
            for area in r.get("research_areas") or []:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO area_links VALUES (?, ?)",
                        [fid, area],
                    )
                except duckdb.Error:
                    pass
            inserted += 1
            if verbose:
                print(f"  [insert] {name} ({acronym}) [{primary}, est {r.get('established')}]")
    print(f"[enrich] additional_facilities — inserted {inserted}, skipped {skipped}")
    return inserted


def load_facility_updates(conn, verbose: bool) -> int:
    """Apply field-level updates to existing facilities."""
    UPDATABLE = {
        "established", "record_length_years", "long_term_threshold_met",
        "url", "data_portal_url", "parent_org", "region", "hq_address",
        "hq_lat", "hq_lng", "contact",
    }
    applied = 0
    skipped = 0
    for agent_dir in sorted(RAW_DIR.glob(ENRICH_GLOB)):
        path = agent_dir / "facility_updates.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"  [warn] {path}: {e}")
            continue
        if not isinstance(payload, list):
            print(f"  [warn] {path}: not a list")
            continue
        for u in payload:
            field = u.get("field_name") or u.get("field")
            new_val = u.get("new_value")
            if field not in UPDATABLE:
                skipped += 1
                continue
            name = (u.get("canonical_name") or "").strip()
            acronym = (u.get("acronym") or "").strip()
            row = conn.execute(
                "SELECT facility_id FROM facilities WHERE "
                "(acronym IS NOT NULL AND upper(acronym) = upper(?)) OR "
                "lower(canonical_name) = lower(?) LIMIT 1",
                [acronym, name],
            ).fetchone()
            if not row:
                skipped += 1
                if verbose:
                    print(f"  [skip] no facility for '{name}' ({acronym})")
                continue
            fid = row[0]
            try:
                conn.execute(
                    f"UPDATE facilities SET {field} = ? WHERE facility_id = ?",
                    [new_val, fid],
                )
                applied += 1
                if verbose:
                    print(f"  [update] {name} ({acronym}) {field} → {new_val!r}")
            except duckdb.Error as e:
                skipped += 1
                if verbose:
                    print(f"  [skip] {name} update failed: {e}")
    print(f"[enrich] facility_updates — applied {applied}, skipped {skipped}")
    return applied


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    with duckdb.connect(str(args.db)) as conn:
        load_additional_facilities(conn, args.verbose)
        load_facility_updates(conn, args.verbose)

    # Stage publications + data_products into the namespaces the
    # existing loaders glob, then invoke them. additional_people.json
    # files use the standard people.json shape and the load_lto_people
    # glob already picks them up via Q-ENRICH-* if we copy alongside.
    # For now: just stage pubs + products; the parent script runs the
    # other loaders next.
    print("[enrich] staging additional_publications.json + additional_data_products.json")
    stage_for_existing_loaders(args.verbose)
    print("[enrich] run scripts/load_lto_publications.py + scripts/load_lto_archives.py "
          "+ scripts/load_lto_people.py to ingest the staged payload")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
