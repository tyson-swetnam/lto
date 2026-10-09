#!/usr/bin/env python3
"""Catalogue the Arizona Water Observatory's API collections as pointer records.

The Arizona Water Observatory (AWO, https://arizonawaterobservatory.asu.edu)
"centralizes water data from ground stations, remote sensing, and
models". Its API (https://arizonawaterobservatory-api.rtd.asu.edu) is a
pygeoapi deployment that fronts state, federal and ASU-derived water
datasets as OGC API collections: Features, Environmental Data Retrieval
(EDR) and Maps.

Like scripts/fetch_envirodata_nm.py, this records **metadata and links
only**. Everything comes from one document, the API's own collection
list; no features, time series or tiles are requested. Per collection:

  title, description, keywords         as the API states them
  spatial / temporal extent            from `extent`
  parameter names                      from `parameter_names` (EDR)
  which query types it answers         items / locations / cube / area / map
  the upstream source and its docs     the `canonical` and `documentation` links

Outputs, in the shapes scripts/load_lto_archives.py reads:

  data/raw/J-AZWATER/archives.json        the one archive row
  data/raw/J-AZWATER/data_products.json   one row per collection
  data/raw/J-AZWATER/api_endpoints.json   the API's endpoint templates

Run from the repo root::

    python scripts/fetch_az_water_observatory.py            # two requests
    python scripts/fetch_az_water_observatory.py --offline  # rebuild from the cache

Responses are cached under data/raw/J-AZWATER/_state/ (gitignored).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "raw" / "J-AZWATER"
CACHE = OUT_DIR / "_state"

API = "https://arizonawaterobservatory-api.rtd.asu.edu"
SITE = "https://arizonawaterobservatory.asu.edu/"
REPO = "https://github.com/cgs-earth/ArizonaWaterObservatory"
USER_AGENT = "lto-catalogue/0.2 (+https://github.com/tyson-swetnam/lto)"
ARCHIVE_ID = "arizona-water-observatory"
VARIABLES_MAX = 40


def fetch(name: str, url: str, offline: bool) -> dict:
    f = CACHE / name
    if not offline:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
        r.raise_for_status()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text)
        time.sleep(1.0)
    elif not f.exists():
        raise SystemExit(f"[error] --offline but {f.relative_to(ROOT)} is not cached")
    return json.loads(f.read_text())


def squash(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def links(coll: dict, rel: str) -> list[str]:
    """Distinct hrefs of one link relation, in document order."""
    seen: list[str] = []
    for link in coll.get("links", []):
        if link.get("rel") == rel and link.get("href") and link["href"] not in seen:
            seen.append(link["href"])
    return seen


def day(stamp: str | None) -> str | None:
    return stamp[:10] if stamp else None


def kind_of(coll: dict) -> tuple[str, str | None, list[str]]:
    """(category, format slug, query types) from what the collection offers."""
    queries = sorted((coll.get("data_queries") or {}).keys())
    is_feature = coll.get("itemType") == "feature"
    is_map = any(l.get("rel", "").endswith("/map") for l in coll.get("links", []))
    edr = [q for q in queries if q != "items"]
    if is_feature and edr:
        return "Feature collection with time series (EDR)", "geojson", ["items", *edr]
    if is_feature:
        return "Feature collection", "geojson", ["items"]
    if queries:
        return "Time series and grids (EDR)", "json", queries
    if is_map:
        return "Map layer", None, ["map"]
    return "Other", None, []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use only cached responses")
    args = ap.parse_args()
    today = date.today().isoformat()

    root = fetch("root.json", f"{API}/?f=json", args.offline)
    colls = fetch("collections.json", f"{API}/collections?f=json", args.offline).get("collections")
    if not colls:
        raise SystemExit("[error] /collections returned no collections")

    products = []
    for c in colls:
        cid = c["id"]
        category, fmt, queries = kind_of(c)
        extent = c.get("extent") or {}
        bbox = ((extent.get("spatial") or {}).get("bbox") or [None])[0]
        interval = ((extent.get("temporal") or {}).get("interval") or [[None, None]])[0]
        params = [squash(p.get("name") or key)
                  for key, p in (c.get("parameter_names") or {}).items()]
        variables = ", ".join(params[:VARIABLES_MAX])
        if len(params) > VARIABLES_MAX:
            variables += f", … ({len(params)} parameters in all)"

        description = squash(c.get("description"))
        # The API writes descriptions as a continuation of the title
        # ("contains …", "provides …"); give them a capital to stand alone.
        description = description[:1].upper() + description[1:]

        notes = []
        if queries:
            notes.append(f"Query types: {', '.join(queries)}.")
        if params:
            notes.append(f"{len(params)} parameter(s).")
        if links(c, "canonical"):
            notes.append(f"Upstream source: {' ; '.join(links(c, 'canonical'))}.")
        if links(c, "documentation"):
            notes.append(f"Documentation: {' ; '.join(links(c, 'documentation'))}.")
        if links(c, "methodology"):
            notes.append(f"Methodology: {' ; '.join(links(c, 'methodology'))}.")
        if c.get("keywords"):
            notes.append(f"Keywords: {', '.join(c['keywords'])}.")

        products.append({
            "archive_id": ARCHIVE_ID,
            "title": squash(c.get("title")) or cid,
            "identifier": cid,
            "url": f"{API}/collections/{cid}?f=html",
            "api_url": f"{API}/collections/{cid}",
            "format_slug": fmt,
            "license_slug": "unknown",
            "temporal_start": day(interval[0]),
            "temporal_end": day(interval[1]),
            "bbox_min_lon": bbox[0] if bbox else None,
            "bbox_min_lat": bbox[1] if bbox else None,
            "bbox_max_lon": bbox[2] if bbox else None,
            "bbox_max_lat": bbox[3] if bbox else None,
            "variables_text": variables or None,
            "category": category,
            "description": description or None,
            "retrieved_at": today,
            "confidence": "high",
            "notes": " ".join(notes) or None,
        })

    archive = [{
        "archive_id": ARCHIVE_ID,
        "name": "Arizona Water Observatory (AWO)",
        "organization": "Arizona State University, with the Internet of Water "
                        "(Center for Geospatial Solutions, Lincoln Institute of Land Policy)",
        "archive_type": "aggregator",
        "base_url": SITE,
        "api_url": API,
        "api_doc_url": f"{API}/openapi?f=html",
        "api_type": "ogc-api",
        "license_slug": "unknown",
        "doi_prefix": None,
        "notes": (
            f"{squash(root.get('description'))} A pygeoapi deployment serving OGC API "
            "Features, Environmental Data Retrieval (EDR), Maps and Processes; most "
            "collections front another agency's service (NOAA, USGS, USDA, USBR, USACE, "
            "NASA, Arizona Department of Water Resources), named in each record's notes. "
            f"Source code: {REPO}. The API document declares the MIT License, which "
            "covers the software; each upstream dataset keeps its own terms, so the "
            "records here carry license 'unknown'. This catalogue holds metadata and "
            "links only."
        ),
    }]

    def first_with(query: str) -> str:
        for c in colls:
            if query in (c.get("data_queries") or {}) or (
                    query == "items" and c.get("itemType") == "feature"):
                return c["id"]
        return colls[0]["id"]

    feat, edr = first_with("items"), first_with("locations")
    endpoints = [
        {"path_or_url": f"{API}/openapi", "purpose": "metadata", "response_format": "json",
         "example_call": f"curl -s '{API}/openapi?f=json'",
         "notes": "OpenAPI 3.0 description of every path. ?f=html for the Swagger UI."},
        {"path_or_url": f"{API}/collections", "purpose": "metadata", "response_format": "json",
         "example_call": f"curl -s '{API}/collections?f=json'",
         "notes": "Every collection with its extent, parameters and source links. "
                  "This is the document the catalogue is built from."},
        {"path_or_url": f"{API}/collections/{{collectionId}}/queryables", "purpose": "metadata",
         "response_format": "json",
         "example_call": f"curl -s '{API}/collections/{feat}/queryables?f=json'",
         "notes": "Filterable properties of a feature collection (JSON Schema)."},
        {"path_or_url": f"{API}/collections/{{collectionId}}/items", "purpose": "download",
         "response_format": "geojson",
         "example_call": f"curl -s '{API}/collections/{feat}/items?f=json&limit=10'",
         "notes": "OGC API Features. Supports limit, offset, bbox, datetime and property "
                  "filters; responses can be large where geometries are detailed."},
        {"path_or_url": f"{API}/collections/{{collectionId}}/locations", "purpose": "search",
         "response_format": "geojson",
         "example_call": f"curl -s '{API}/collections/{edr}/locations?f=json'",
         "notes": "OGC API EDR: the stations or sites a collection has data for. Append "
                  "/{locId} with datetime and parameter-name for one location's series; "
                  "f=csv is offered too."},
        {"path_or_url": f"{API}/collections/{{collectionId}}/cube", "purpose": "download",
         "response_format": "json",
         "example_call": f"curl -s '{API}/collections/{edr}/cube?f=json"
                         "&bbox=-112.5,33.2,-111.5,33.8&datetime=2023-01-01/2023-01-31'",
         "notes": "OGC API EDR cube query: everything inside a bbox and time window, as "
                  "CoverageJSON. /area takes a WKT polygon instead of a bbox."},
        {"path_or_url": f"{API}/processes", "purpose": "metadata", "response_format": "json",
         "example_call": f"curl -s '{API}/processes?f=json'",
         "notes": "OGC API Processes offered by the server."},
    ]
    for e in endpoints:
        e.update({"archive_id": ARCHIVE_ID, "method": "GET",
                  "schema_url": f"{API}/openapi?f=json"})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for fname, rows in (("archives.json", archive), ("data_products.json", products),
                        ("api_endpoints.json", endpoints)):
        (OUT_DIR / fname).write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")

    by_cat: dict[str, int] = {}
    for p in products:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    print(f"[ok] {len(products)} collections: "
          + ", ".join(f"{n} {k}" for k, n in sorted(by_cat.items(), key=lambda t: -t[1])))
    print(f"[ok] wrote {OUT_DIR.relative_to(ROOT)}/{{archives,data_products,api_endpoints}}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
