#!/usr/bin/env python3
"""Add the `arid` sphere and reassign dryland study sites to it.

The six-sphere model becomes seven: arid, semi-arid, and desert systems
get their own primary sphere instead of riding along under terrestrial.

Assignment policy (user-directed, 2026-08-13):

  * PRIMARY -> arid: sites whose research identity is dryland ecology —
    the desert LTERs (Jornada Basin, Sevilleta), the NEON desert-domain
    sites, Great Basin Experimental Range, Mojave Global Change
    Facility, USGS Canyonlands, Big Bend Biosphere Reserve, and the NPS
    Sonoran Desert I&M network.
  * SECONDARY arid: every other facility carrying the `arid-land`
    ecosystem tag. LTAR / ARS rangeland and SCAN sites keep agriculture
    as primary (that sphere's charter explicitly includes ARS
    rangelands); desert streams (Sycamore Creek, Red Butte) keep
    freshwater. Their dryland setting is recorded, not promoted.

Idempotent: re-running converges to the same state. Prints every change
it makes and a summary; --dry-run previews.

Usage::

    python scripts/add_arid_sphere.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "lto.duckdb"
VOCAB = ROOT / "schema" / "vocab" / "spheres.csv"

# Sites whose identity IS dryland research — primary flips to arid.
# Matched on acronym (unique in the catalogue); the Sonoran network has
# no acronym so it matches on canonical_name.
PRIMARY_ACRONYMS = [
    "JRN",            # Jornada Basin LTER
    "SEV",            # Sevilleta LTER
    "GBR",            # Great Basin Experimental Range
    "MGCF",           # Mojave Global Change Facility (LTREB)
    "JORN",           # Jornada Experimental Range NEON
    "SRER",           # Santa Rita Experimental Range NEON (flux tower)
    "ONAQ",           # Onaqui NEON
    "USGS-CRS-MOAB",  # USGS Canyonlands Research Station
    "BIBE-BR",        # Big Bend Biosphere Reserve
]
PRIMARY_NAMES = [
    "NPS-IM Sonoran Desert Network",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = duckdb.connect(str(DB))
    conn.execute("SET search_path = main;")

    # 1. Vocab row, straight from the canonical CSV so label/description
    #    can never drift from schema/vocab/spheres.csv.
    with VOCAB.open() as fh:
        row = next(r for r in csv.DictReader(fh) if r["slug"] == "arid")
    exists = conn.execute(
        "SELECT COUNT(*) FROM spheres WHERE slug = 'arid'").fetchone()[0]
    if not exists:
        print(f"[vocab] inserting sphere 'arid' — {row['label']}")
        if not args.dry_run:
            conn.execute(
                "INSERT INTO spheres (slug, label, description) VALUES (?, ?, ?)",
                [row["slug"], row["label"], row["description"]])
    else:
        print("[vocab] sphere 'arid' already present")

    # 2. Resolve the primary-flip set.
    ids = conn.execute(
        """SELECT facility_id, canonical_name FROM facilities
           WHERE acronym IN (SELECT UNNEST(?::VARCHAR[]))
              OR canonical_name IN (SELECT UNNEST(?::VARCHAR[]))""",
        [PRIMARY_ACRONYMS, PRIMARY_NAMES]).fetchall()
    if len(ids) != len(PRIMARY_ACRONYMS) + len(PRIMARY_NAMES):
        print(f"[warn] resolved {len(ids)} of "
              f"{len(PRIMARY_ACRONYMS) + len(PRIMARY_NAMES)} intended primaries "
              "— check acronyms", file=sys.stderr)
    flip_ids = [r[0] for r in ids]

    # 3. Flip primaries. Delete any existing arid row first so the UPDATE
    #    can never create a duplicate (facility_id, sphere_slug) pair.
    for fid, name in ids:
        cur = conn.execute(
            "SELECT sphere_slug FROM facility_spheres WHERE facility_id = ? AND role = 'primary'",
            [fid]).fetchone()
        if cur and cur[0] == "arid":
            continue
        print(f"[primary] {name}: {cur[0] if cur else '(none)'} -> arid")
        if args.dry_run:
            continue
        conn.execute(
            "DELETE FROM facility_spheres WHERE facility_id = ? AND sphere_slug = 'arid'",
            [fid])
        if cur:
            # Old primary becomes a secondary of its former sphere: Big
            # Bend is still terrestrial, just not primarily.
            conn.execute(
                """UPDATE facility_spheres SET role = 'secondary'
                   WHERE facility_id = ? AND role = 'primary'""", [fid])
        conn.execute(
            "INSERT INTO facility_spheres (facility_id, sphere_slug, role) VALUES (?, 'arid', 'primary')",
            [fid])

    # 4. Sonoran Desert Network also gains the ecosystem tag it was missing.
    if not args.dry_run:
        conn.execute(
            """INSERT INTO facility_ecosystems (facility_id, ecosystem_slug)
               SELECT facility_id, 'arid-land' FROM facilities
               WHERE canonical_name = 'NPS-IM Sonoran Desert Network'
                 AND facility_id NOT IN (
                   SELECT facility_id FROM facility_ecosystems
                   WHERE ecosystem_slug = 'arid-land')""")

    # 5. Secondary arid for every other arid-land-tagged facility.
    secondaries = conn.execute(
        """SELECT DISTINCT f.facility_id, f.canonical_name
           FROM facility_ecosystems fe
           JOIN facilities f USING (facility_id)
           WHERE fe.ecosystem_slug = 'arid-land'
             AND f.facility_id NOT IN (SELECT UNNEST(?::VARCHAR[]))
             AND f.facility_id NOT IN (
               SELECT facility_id FROM facility_spheres WHERE sphere_slug = 'arid')
           ORDER BY f.canonical_name""",
        [flip_ids]).fetchall()
    for fid, name in secondaries:
        print(f"[secondary] {name}: + arid")
        if not args.dry_run:
            conn.execute(
                "INSERT INTO facility_spheres (facility_id, sphere_slug, role) VALUES (?, 'arid', 'secondary')",
                [fid])

    n_primary = conn.execute(
        "SELECT COUNT(*) FROM facility_spheres WHERE sphere_slug='arid' AND role='primary'"
    ).fetchone()[0]
    n_secondary = conn.execute(
        "SELECT COUNT(*) FROM facility_spheres WHERE sphere_slug='arid' AND role='secondary'"
    ).fetchone()[0]
    print(f"[done] arid sphere: {n_primary} primary, {n_secondary} secondary"
          + (" (dry run — no writes)" if args.dry_run else ""))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
