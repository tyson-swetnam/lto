#!/usr/bin/env python3
"""Drop non-research-facility records from the facilities table.

The cod-kmap heritage data classified several administrative /
regulatory / philanthropic entities as facilities. These don't host
long-term observational data and don't fit the WORLD_MODEL spec for
an LTO facility:

  * EPA Regions (10)              — administrative regions, belong in `regions`
  * State coastal-management offices — regulatory bodies, not observatories
  * State fish & wildlife commissions — regulators, not data producers
  * Private foundations           — funders, belong in `funders`
  * Advocacy NGOs                  — not observatories
  * Network umbrella records       — duplicates of `networks` table rows

Run AFTER `scripts/ingest.py` and BEFORE the people / archives /
publications loaders. Idempotent — re-running drops nothing if the
records have already been removed.

Usage::
    python scripts/cleanup_non_facilities.py
    python scripts/cleanup_non_facilities.py --db db/cod_kmap.duckdb --dry-run
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"

# Patterns / acronyms to drop. Each entry is a SQL WHERE clause fragment.
# Add new patterns at the bottom as future loops surface more non-facility
# records via PROGRESS.md's worst-covered list.
DROP_PATTERNS = [
    # Administrative regions (belong in `regions`, not `facilities`).
    ("EPA Regions",
     "canonical_name LIKE 'U.S. EPA Region%'"),
    # State coastal-management regulatory offices.
    ("State coastal-management offices",
     "canonical_name IN ("
     "  'North Carolina Division of Coastal Management',"
     "  'Texas General Land Office — Coastal Management Program',"
     "  'Massachusetts Office of Coastal Zone Management',"
     "  'Louisiana Coastal Protection and Restoration Authority',"
     "  'Maryland Department of Natural Resources — Coastal and Ocean Program',"
     "  'Florida Department of Environmental Protection — Coastal and Aquatic Managed Areas',"
     "  'California Ocean Protection Council'"
     ")"),
    # State fish & wildlife regulators (not research-data producers).
    ("State fish & wildlife regulators",
     "canonical_name IN ("
     "  'Florida Fish and Wildlife Conservation Commission'"
     ")"),
    # Private grantmaking foundations (move to `funders` if not there).
    ("Private foundations",
     "canonical_name IN ("
     "  'David and Lucile Packard Foundation',"
     "  'Gordon and Betty Moore Foundation',"
     "  'Surfrider Foundation'"
     ")"),
    # Advocacy NGOs and aquaria.
    ("Advocacy NGOs / aquaria",
     "canonical_name IN ("
     "  'The Nature Conservancy — Oceans Program',"
     "  'New England Aquarium',"
     "  'Schmidt Ocean Institute',"
     "  'Environmental Defense Fund — Oceans Program'"
     ")"),
    # Network umbrella records that duplicate the `networks` table.
    ("Network umbrella records",
     "canonical_name IN ("
     "  'Long-Term Ecological Research Network'"
     ")"),
]

# Tables that hold a `facility_id` foreign key and need cascade-delete
# before we can drop the facility row. Order matters only for clarity.
DEPENDENT_TABLES = [
    "facility_archives", "facility_personnel", "facility_spheres",
    "facility_ecosystems", "facility_life_zones", "facility_regions",
    "facility_primary_groups", "area_links", "network_membership",
    "funding_events", "data_products", "api_endpoints", "cloud_buckets",
    "locations", "provenance",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with duckdb.connect(str(args.db)) as conn:
        # Resolve every facility_id matched by any pattern.
        ids: list[tuple[str, str, str]] = []
        for label, where in DROP_PATTERNS:
            rows = conn.execute(
                f"SELECT facility_id, canonical_name, ? AS label FROM facilities WHERE {where}",
                [label],
            ).fetchall()
            ids.extend(rows)

        if not ids:
            print("[cleanup_non_facilities] nothing to drop — already clean")
            return 0

        from collections import Counter
        by_label = Counter(r[2] for r in ids)
        print(f"[cleanup_non_facilities] dropping {len(ids)} non-facility rows:")
        for label, n in by_label.most_common():
            print(f"  {n:3d}  {label}")

        if args.dry_run:
            print("[cleanup_non_facilities] dry-run — no changes")
            return 0

        fid_set = tuple(r[0] for r in ids)
        # DuckDB supports parameterized lists via the `WHERE x IN (...)` form
        # but only with literal SQL — so build the placeholders ourselves.
        placeholders = ",".join(["?"] * len(fid_set))

        # Drop dependents first.
        for tbl in DEPENDENT_TABLES:
            try:
                n = conn.execute(
                    f"DELETE FROM {tbl} WHERE facility_id IN ({placeholders})",
                    list(fid_set),
                ).fetchone()
                # DuckDB DELETE returns row counts via `Changes`; not always
                # exposed via fetchone(). Skip strict counting; the eval
                # script will re-tally.
            except duckdb.Error as e:
                # Table may not exist on a fresh DB, or facility_id column
                # may differ — skip cleanly.
                if "does not exist" not in str(e).lower():
                    print(f"  [warn] {tbl}: {e}")

        # Finally, drop the facility rows themselves.
        conn.execute(
            f"DELETE FROM facilities WHERE facility_id IN ({placeholders})",
            list(fid_set),
        )
        n_after = conn.execute("SELECT count(*) FROM facilities").fetchone()[0]
        print(f"[cleanup_non_facilities] facilities table now: {n_after} rows")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
