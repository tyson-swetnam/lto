"""Data-quality assertions run after ingest.

Exits non-zero on any failure so CI workflows can gate deploys.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "cod_kmap.duckdb"

BBOX_BY_COUNTRY = {
    # (min_lat, max_lat, min_lng, max_lng) — generous continental boxes
    "US": (17.0, 72.0, -180.0, -64.0),
    "CA": (41.0, 84.0, -142.0, -52.0),
    "MX": (14.0, 33.0, -118.0, -86.0),
    "CU": (19.5, 23.5, -85.5, -74.0),
    "JM": (17.5, 18.7, -78.5, -76.0),
    "BS": (20.5, 27.5, -79.5, -72.5),
    "DO": (17.5, 20.0, -72.0, -68.0),
    "HT": (17.5, 20.0, -74.5, -71.5),
    "PR": (17.8, 18.6, -67.3, -65.2),
    "VI": (17.6, 18.5, -65.1, -64.5),
    "CO": (-4.3, 13.0, -81.8, -66.8),
    "BR": (-34.0, 5.3, -74.0, -28.6),
    "AR": (-55.2, -21.8, -73.6, -53.6),
    "CL": (-56.0, -17.5, -75.7, -66.4),
    "PE": (-18.4, -0.1, -81.4, -68.6),
    "EC": (-5.1, 1.7, -92.1, -75.2),
    "UY": (-35.0, -30.0, -58.5, -53.0),
    "VE": (0.6, 12.3, -73.4, -59.8),
    "PA": (7.2, 9.7, -83.0, -77.2),
    "CR": (8.0, 11.3, -86.0, -82.5),
    "GT": (13.7, 17.9, -92.3, -88.2),
    "BZ": (15.9, 18.5, -89.3, -87.3),
    "HN": (12.9, 16.6, -89.4, -83.1),
    "NI": (10.7, 15.1, -87.7, -82.6),
    "SV": (12.9, 14.5, -90.2, -87.6),
    "BB": (13.0, 13.4, -60.0, -59.3),
    "TT": (10.0, 11.5, -62.0, -60.4),
    "KY": (19.2, 19.9, -81.5, -79.7),
    "TC": (20.9, 22.0, -72.5, -71.0),
}


def assert_true(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)


def main() -> int:
    failures: list[str] = []
    with duckdb.connect(str(DB_PATH)) as conn:
        conn.execute("SET search_path = main;")

        null_type = conn.execute(
            "SELECT COUNT(*) FROM facilities WHERE facility_type IS NULL OR country IS NULL"
        ).fetchone()[0]
        assert_true(null_type == 0, f"{null_type} facilities with null facility_type or country", failures)

        bad_enum = conn.execute(
            "SELECT COUNT(*) FROM facilities f LEFT JOIN facility_types t ON f.facility_type = t.slug WHERE t.slug IS NULL"
        ).fetchone()[0]
        assert_true(bad_enum == 0, f"{bad_enum} facilities reference unknown facility_type", failures)

        no_prov = conn.execute(
            """SELECT COUNT(*) FROM facilities f
               LEFT JOIN provenance p ON p.record_type='facility' AND p.record_id = f.facility_id
               WHERE p.record_id IS NULL"""
        ).fetchone()[0]
        assert_true(no_prov == 0, f"{no_prov} facilities without provenance rows", failures)

        # bbox checks
        for country, (min_lat, max_lat, min_lng, max_lng) in BBOX_BY_COUNTRY.items():
            count = conn.execute(
                """SELECT COUNT(*) FROM facilities
                   WHERE country = ? AND hq_lat IS NOT NULL AND hq_lng IS NOT NULL
                   AND (hq_lat < ? OR hq_lat > ? OR hq_lng < ? OR hq_lng > ?)""",
                [country, min_lat, max_lat, min_lng, max_lng],
            ).fetchone()[0]
            assert_true(count == 0, f"{count} {country} facilities outside the country bbox", failures)

    if failures:
        print("QA FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("QA passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
