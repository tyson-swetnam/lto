#!/usr/bin/env python3
"""Fetch USFWS authoritative protected-area polygons (FWSApproved) from the
official ArcGIS REST endpoint and save as a single GeoJSON FeatureCollection.

Source service:
  https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/FWSApproved_Authoritative/FeatureServer/0
  (Owned by the U.S. Fish & Wildlife Service Headquarters; layer:
  "FWSApproved" — Approved Acquisition Boundaries.)

This is the authoritative outer boundary of every National Wildlife Refuge,
Wildlife Management Area, Waterfowl Management District, Fish Hatchery, etc.
managed by USFWS. One polygon per organization unit (e.g. one per NWR), as
opposed to the parcel-level "FWSInterest" layer.

We pull *all* records in WGS84 (the service serves them in EPSG:4326 already
when geometryType is unset). Coastal filtering is done downstream by
``filter_coastal.py`` so this raw pull stays reusable for non-coastal queries.

Usage:
    python scripts/coastal_research/fetch_fws_authoritative.py \
        --out network_synth_spatial_analysis/coastal_protected/fws_approved.geojson

Idempotent — re-running overwrites the output and re-emits identical content
when upstream is unchanged. Logs progress to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Iterable

SERVICE = (
    "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/"
    "FWSApproved_Authoritative/FeatureServer/0"
)
PAGE = 200  # well below the 2000 maxRecordCount; keeps responses small


def _query(params: dict) -> dict:
    url = f"{SERVICE}/query?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "cod-kmap/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _fetch_offset(offset: int, page: int, where: str = "1=1") -> list[dict]:
    """Page via resultOffset/resultRecordCount instead of objectId batches.

    The service supports advanced pagination, which is more reliable on
    ArcGIS Online than enumerating then re-querying by id.
    """
    params = {
        "where": where,
        "outFields": "*",
        "outSR": 4326,
        "returnGeometry": "true",
        "resultOffset": offset,
        "resultRecordCount": page,
        "orderByFields": "OBJECTID",
        "f": "geojson",
    }
    data = _query(params)
    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error']}")
    return data.get("features") or []


def _count(where: str = "1=1") -> int:
    data = _query({"where": where, "returnCountOnly": "true", "f": "json"})
    return int(data.get("count", 0))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="Output GeoJSON path")
    ap.add_argument("--page", type=int, default=PAGE)
    ap.add_argument(
        "--where",
        default="1=1",
        help="Optional ArcGIS WHERE clause (e.g. \"RSL_TYPE='NWR'\")",
    )
    args = ap.parse_args()

    total = _count(args.where)
    print(f"[fetch_fws] {total} features match where='{args.where}'", file=sys.stderr)

    features: list[dict] = []
    offset = 0
    while offset < total:
        for attempt in range(3):
            try:
                got = _fetch_offset(offset, args.page, args.where)
                features.extend(got)
                print(
                    f"[fetch_fws] offset={offset} +{len(got)} -> {len(features)}/{total}",
                    file=sys.stderr,
                )
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[fetch_fws] attempt {attempt+1} failed: {exc}", file=sys.stderr)
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"failed to fetch offset {offset}")
        offset += args.page

    fc = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source_service": SERVICE,
            "source_owner": "U.S. Fish and Wildlife Service",
            "layer": "FWSApproved (Approved Acquisition Boundaries)",
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "feature_count": len(features),
            "license": "Public domain (US federal government work)",
        },
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(fc, f)
    print(f"[fetch_fws] wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
