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
    python scripts/cleanup_non_facilities.py --catalog db/lto_catalog.sqlite --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

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
# alongside the facility row (the lake cascades nothing; any child table
# missed here fails assert_integrity and rolls the run back). Order
# matters only for clarity.
DEPENDENT_TABLES = [
    "facility_archives", "facility_personnel", "facility_spheres",
    "facility_ecosystems", "facility_life_zones", "facility_regions",
    "facility_primary_groups", "area_links", "network_membership",
    "funding_events", "data_products", "api_endpoints", "cloud_buckets",
    "locations", "provenance",
    # Soft reference (not declared in schema.sql); assert_integrity checks
    # it through lto_db.SOFT_REFERENCES.
    "registry_facilities",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with lto_db.connect(read_only=args.dry_run, catalog=args.catalog,
                        data=args.lake_data) as conn:
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

        # A failed statement aborts the whole transaction, so probe for
        # the table and its facility_id column instead of try/except.
        has_fid = {r[0] for r in lto_db.rows(
            conn, "SELECT table_name FROM duckdb_columns() "
                  "WHERE database_name = ? AND schema_name = 'main' "
                  "AND column_name = 'facility_id'", [lto_db.LAKE])}

        with lto_db.transaction(
                conn, f"cleanup_non_facilities: drop {len(fid_set)} "
                      f"non-facility rows and their dependents"):
            # Drop dependents first.
            for tbl in DEPENDENT_TABLES:
                if tbl not in has_fid:
                    # Table may not exist on a fresh lake — skip cleanly.
                    continue
                conn.execute(
                    f"DELETE FROM {tbl} WHERE facility_id IN ({placeholders})",
                    list(fid_set),
                ).fetchall()

            # Finally, drop the facility rows themselves.
            conn.execute(
                f"DELETE FROM facilities WHERE facility_id IN ({placeholders})",
                list(fid_set),
            )
            # Covers every foreign key that points at facilities.
            lto_db.assert_integrity(conn, ["facilities"])
        n_after = conn.execute("SELECT count(*) FROM facilities").fetchone()[0]
        print(f"[cleanup_non_facilities] facilities table now: {n_after} rows")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
