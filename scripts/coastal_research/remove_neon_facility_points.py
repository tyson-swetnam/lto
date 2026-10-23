#!/usr/bin/env python3
"""Remove the 81 NEON-as-facility-points records from the cod-kmap
catalogue. The NEON sites now live exclusively as the
``public/overlays/neon-sites.geojson`` polygon overlay; keeping them
in the facilities table would render them twice on the Map view (once
as observatory dots, once as polygons).

Drops:
  * facilities rows where parent_org='National Ecological Observatory Network'
  * matching locations rows
  * matching network_membership rows
  * matching area_links rows
  * matching provenance rows where agent='R11' and record_type='facility'

All deletes land in the lake as one snapshot (commit message
``remove_neon_facility_points: …``), after an integrity check; nothing
lands if a remaining table still points at a NEON row. This script no
longer writes parquet or ``public/facilities.geojson`` — publish with
qa.py → export_parquet.py → export_view_caches.py afterwards. Point it
at a scratch lake with ``$LTO_LAKE_CATALOG`` or ``--catalog``.

Idempotent — re-running on a clean lake drops 0 rows and writes no
snapshot.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lto_db  # noqa: E402

R11_FAC_FILE = (ROOT / "data" / "raw" / "R11_coastal_ecosystems"
                / "facilities_neon_sites.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lto_db.add_argparse_catalog(ap)
    args = ap.parse_args()
    try:
        conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[err] {e}", file=sys.stderr)
        return 2
    print(f"[neon-rm] lake: {lto_db.catalog_path(args.catalog)}", file=sys.stderr)

    with conn:
        # Find the facility_ids to delete
        rows = conn.execute(
            "SELECT facility_id FROM facilities "
            "WHERE parent_org = 'National Ecological Observatory Network'"
        ).fetchall()
        ids = [r[0] for r in rows]
        print(f"[neon-rm] {len(ids)} NEON facility rows to remove",
              file=sys.stderr)
        if not ids:
            print("[neon-rm] nothing to do", file=sys.stderr)
            return 0

        ph = ",".join(["?"] * len(ids))
        with lto_db.transaction(conn, f"remove_neon_facility_points: drop "
                                      f"{len(ids)} NEON facility points"):
            for child in ("locations", "network_membership", "area_links",
                          "facility_regions", "facility_personnel",
                          "registry_facilities"):
                # A failed statement aborts the transaction, so probe for
                # the table instead of try/except.
                if not lto_db.table_exists(conn, child):
                    print(f"[neon-rm]   {child}: skipped (no such table)",
                          file=sys.stderr)
                    continue
                n = lto_db.scalar(
                    conn, f"SELECT COUNT(*) FROM {child} "
                          f"WHERE facility_id IN ({ph})", ids)
                conn.execute(
                    f"DELETE FROM {child} WHERE facility_id IN ({ph})", ids)
                print(f"[neon-rm]   {child}: -{n}", file=sys.stderr)

            # provenance has no FK to facilities so we delete by record_id
            n = lto_db.scalar(
                conn, f"SELECT COUNT(*) FROM provenance "
                      f"WHERE record_id IN ({ph}) AND record_type='facility'", ids)
            conn.execute(
                f"DELETE FROM provenance "
                f"WHERE record_id IN ({ph}) AND record_type='facility'", ids)
            print(f"[neon-rm]   provenance: -{n}", file=sys.stderr)

            # Finally drop the facility rows
            conn.execute(
                f"DELETE FROM facilities WHERE facility_id IN ({ph})", ids)
            print(f"[neon-rm]   facilities: -{len(ids)}", file=sys.stderr)

            # Nothing cascades in a lake: any other table that still
            # points at a dropped facility (declared FKs and the soft
            # references in lto_db.SOFT_REFERENCES) fails this and rolls back.
            lto_db.assert_integrity(conn, ["facilities", "provenance"])
        print("[neon-rm] next: qa.py → export_parquet.py → export_view_caches.py",
              file=sys.stderr)

    # Drop the now-orphan R11 seed file so future ingest_r11.py runs
    # don't re-add the points.
    if R11_FAC_FILE.exists():
        try:
            R11_FAC_FILE.unlink()
            print(f"[neon-rm] removed seed file: "
                  f"{R11_FAC_FILE.relative_to(ROOT)}", file=sys.stderr)
        except OSError as exc:
            print(f"[neon-rm] could not remove seed file ({exc}); "
                  f"please delete by hand", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
