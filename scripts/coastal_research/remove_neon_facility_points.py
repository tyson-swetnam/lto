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

Then re-exports the affected parquets and the
``public/facilities.geojson`` snapshot.

Idempotent — re-running on a clean DB drops 0 rows.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get("COD_KMAP_DB", str(ROOT / "db" / "cod_kmap.duckdb")))
OUT_DB = ROOT / "db" / "parquet"
OUT_WEB = ROOT / "public" / "parquet"
GEOJSON_OUT = ROOT / "public" / "facilities.geojson"
R11_FAC_FILE = (ROOT / "data" / "raw" / "R11_coastal_ecosystems"
                / "facilities_neon_sites.json")

PARQUET_TABLES = (
    "facilities", "locations", "network_membership", "area_links",
    "provenance",
)


def main() -> int:
    if not DB_PATH.exists():
        print(f"[err] DB not found: {DB_PATH}", file=sys.stderr)
        return 2
    print(f"[neon-rm] DB: {DB_PATH}", file=sys.stderr)

    with duckdb.connect(str(DB_PATH)) as conn:
        # Find the facility_ids to delete
        rows = conn.execute(
            "SELECT facility_id FROM main.facilities "
            "WHERE parent_org = 'National Ecological Observatory Network'"
        ).fetchall()
        ids = [r[0] for r in rows]
        print(f"[neon-rm] {len(ids)} NEON facility rows to remove",
              file=sys.stderr)
        if not ids:
            print("[neon-rm] nothing to do", file=sys.stderr)
            return 0

        # DELETE child tables FIRST (DuckDB FKs); then facilities.
        ph = ",".join(["?"] * len(ids))
        for child in ("locations", "network_membership", "area_links",
                      "facility_regions", "facility_personnel"):
            try:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM main.{child} "
                    f"WHERE facility_id IN ({ph})", ids,
                ).fetchone()[0]
                conn.execute(
                    f"DELETE FROM main.{child} "
                    f"WHERE facility_id IN ({ph})", ids,
                )
                print(f"[neon-rm]   {child}: -{n}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                # Some tables may not exist depending on schema version
                print(f"[neon-rm]   {child}: skipped ({exc})", file=sys.stderr)

        # provenance has no FK to facilities so we can delete by record_id
        try:
            n = conn.execute(
                f"SELECT COUNT(*) FROM main.provenance "
                f"WHERE record_id IN ({ph}) AND record_type='facility'",
                ids,
            ).fetchone()[0]
            conn.execute(
                f"DELETE FROM main.provenance "
                f"WHERE record_id IN ({ph}) AND record_type='facility'", ids,
            )
            print(f"[neon-rm]   provenance: -{n}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[neon-rm]   provenance: skipped ({exc})", file=sys.stderr)

        # Finally drop the facility rows
        conn.execute(
            f"DELETE FROM main.facilities WHERE facility_id IN ({ph})", ids,
        )
        print(f"[neon-rm]   facilities: -{len(ids)}", file=sys.stderr)

        # Re-export the affected parquets to both db/ and public/
        OUT_DB.mkdir(parents=True, exist_ok=True)
        OUT_WEB.mkdir(parents=True, exist_ok=True)
        for t in PARQUET_TABLES:
            out = OUT_DB / f"{t}.parquet"
            try:
                conn.execute(f"COPY (SELECT * FROM main.{t}) TO '{out}' "
                             "(FORMAT PARQUET)")
                shutil.copyfile(out, OUT_WEB / f"{t}.parquet")
            except Exception as exc:  # noqa: BLE001
                print(f"[neon-rm]   skipped re-export of {t}: {exc}",
                      file=sys.stderr)
        print(f"[neon-rm] refreshed parquets: {', '.join(PARQUET_TABLES)}",
              file=sys.stderr)

        # Rebuild the published facilities.geojson
        rows = conn.execute(
            """SELECT id, name, acronym, type, country, lat, lng, url, parent_org
               FROM v_facility_map"""
        ).fetchall()
        feats = [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": fid_, "name": name, "acronym": acr, "type": ftype,
                "country": country, "url": url, "parent_org": parent,
            },
        } for fid_, name, acr, ftype, country, lat, lng, url, parent in rows]
        GEOJSON_OUT.write_text(
            json.dumps({"type": "FeatureCollection", "features": feats}, indent=0)
        )
        print(f"[neon-rm] rebuilt {GEOJSON_OUT.relative_to(ROOT)}: "
              f"{len(feats)} features", file=sys.stderr)

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
