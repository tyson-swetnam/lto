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

The facility rows and updates are one DuckLake snapshot (scripts/lto_db.py).
The lake checks no foreign keys, so a link row or an update that DuckDB
used to reject (an unknown sphere slug, an established year that is not
a number) is checked first and skipped, as before.

Usage::

    python scripts/load_lto_enrichment.py
    python scripts/load_lto_enrichment.py --catalog db/lto_catalog.sqlite --verbose
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_lto_archives import RowRejected, cast_error, write_row  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
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
            # A bad facility row (unknown facility_type, no name) still
            # stops the run, now at assert_integrity in main().
            write_row(conn, "facilities", {
                "facility_id": fid, "canonical_name": name, "acronym": acronym,
                "parent_org": r.get("parent_org"), "facility_type": r.get("facility_type"),
                "country": r.get("country") or "US", "region": r.get("region"),
                "hq_address": hq.get("address"), "hq_lat": hq.get("lat"),
                "hq_lng": hq.get("lng"), "url": r.get("url"), "contact": r.get("contact"),
                "established": r.get("established"),
                "record_length_years": r.get("record_length_years"),
                "long_term_threshold_met": r.get("long_term_threshold_met"),
                "data_portal_url": r.get("data_portal_url"),
            }, key=["facility_id"], checked=True)

            def link(table: str, row: dict) -> None:
                # Unknown slugs are dropped silently, as DuckDB's FK
                # rejection used to be.
                try:
                    write_row(conn, table, row, key=list(row)[:2], insert_only=True)
                except RowRejected:
                    pass

            # facility_spheres
            primary = r.get("primary_sphere")
            if primary:
                link("facility_spheres",
                     {"facility_id": fid, "sphere_slug": primary, "role": "primary"})
            for sec in r.get("secondary_spheres") or []:
                link("facility_spheres",
                     {"facility_id": fid, "sphere_slug": sec, "role": "secondary"})
            for eco in r.get("ecosystem_types") or []:
                link("facility_ecosystems", {"facility_id": fid, "ecosystem_slug": eco})
            for net in r.get("networks") or []:
                link("network_membership",
                     {"facility_id": fid,
                      "network_id": net.lower() if isinstance(net, str) else net,
                      "role": None})
            for area in r.get("research_areas") or []:
                link("area_links", {"facility_id": fid, "area_id": area})
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
            err = cast_error("facilities", field, new_val)
            if err is None:
                conn.execute(
                    f"UPDATE facilities SET {field} = ? WHERE facility_id = ?",
                    [new_val, fid],
                )
                applied += 1
                if verbose:
                    print(f"  [update] {name} ({acronym}) {field} → {new_val!r}")
            else:
                skipped += 1
                if verbose:
                    print(f"  [skip] {name} update failed: {err}")
    print(f"[enrich] facility_updates — applied {applied}, skipped {skipped}")
    return applied


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path, help="deprecated alias of --catalog")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    agents = sorted(d.name for d in RAW_DIR.glob(ENRICH_GLOB))
    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    with lto_db.transaction(conn, f"load_lto_enrichment: facilities + facility updates from "
                                  f"{', '.join(agents) or 'no Q-ENRICH-* dirs'}"):
        load_additional_facilities(conn, args.verbose)
        load_facility_updates(conn, args.verbose)
        lto_db.assert_integrity(conn, ["facilities", "facility_spheres", "facility_ecosystems",
                                       "network_membership", "area_links"])
    conn.close()

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
