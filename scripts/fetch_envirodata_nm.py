#!/usr/bin/env python3
"""Catalogue EnviroData-NM's map layers as data products that point back to it.

EnviroData-NM (https://envirodata-nm.unm.edu) is New Mexico's
environmental data portal, run by Natural Heritage New Mexico at the
Museum of Southwestern Biology under the 2021 Environmental Database
Act. Each of its layers is a copy harvested from a state or federal
ArcGIS service and re-served as OGC WMS / WFS.

This script records **metadata and links only**. It never downloads a
layer's features: the portal's terms say its data are not to be
redistributed, and the point of the catalogue is to send people (and
machines) to the portal's own endpoints. What it reads, per layer:

  /explore/api/layers            title, description, category path,
                                 downloadable flag, upstream service
  /ogc/layers                    geometry type
  /ogc/wms/<name> GetCapabilities   bounding box
  /ogc/attributes/<name>?limit=0    column names + feature count, no rows

and what it writes, in the shapes scripts/load_lto_archives.py reads:

  data/raw/J-ENVIRODATA/archives.json        the one archive row
  data/raw/J-ENVIRODATA/data_products.json   one row per visible layer
  data/raw/J-ENVIRODATA/api_endpoints.json   the portal's endpoint templates
  data/raw/J-ENVIRODATA/facility_archives.json   its links to catalogue facilities
                                             (load scripts/load_arid.py first)

/explore/api/layers and /ogc/layers are not documented by the portal;
they were found by inspection and may change. If the catalogue endpoint
goes away this script fails loudly rather than writing an empty file.

Run from the repo root::

    python scripts/fetch_envirodata_nm.py             # ~5 min, 1 request/s
    python scripts/fetch_envirodata_nm.py --offline   # rebuild from the cache
    python scripts/fetch_envirodata_nm.py --refresh   # ignore the cache

Per-layer responses are cached under data/raw/J-ENVIRODATA/_state/
(gitignored), so an interrupted run resumes where it stopped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "raw" / "J-ENVIRODATA"
CACHE = OUT_DIR / "_state"

BASE = "https://envirodata-nm.unm.edu"
USER_AGENT = "lto-catalogue/0.2 (+https://github.com/tyson-swetnam/lto)"
ARCHIVE_ID = "envirodata-nm"
LICENSE = "envirodata-nm-terms"
DELAY_S = 1.0
DESCRIPTION_MAX = 1500

# Columns the portal adds to every layer; not part of the source schema.
INTERNAL_COLUMNS = {"id", "mvt_id", "geometry", "objectid", "globalid", "edb_id"}

# Upstream ArcGIS hosts → who runs the server. This is the *host*, which
# is not always the originating agency (the NHNM server republishes EPA,
# USGS and other layers), so it is recorded as "served from", not "by".
HOSTS = {
    "nhnm-gisweb.unm.edu": "Natural Heritage New Mexico",
    "mercator.env.nm.gov": "New Mexico Environment Department",
    "watersgeo.epa.gov": "U.S. EPA",
    "gis.emnrd.nm.gov": "NM Energy, Minerals and Natural Resources Department",
    "mapservice.nmstatelands.org": "New Mexico State Land Office",
    "apps.fs.usda.gov": "USDA Forest Service",
    "nmert.org": "NM Environmental Review Tool",
    "energy.usgs.gov": "U.S. Geological Survey",
    "gis.blm.gov": "Bureau of Land Management",
}


class LayerError(Exception):
    """An endpoint answered with an HTTP error status."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


class Fetcher:
    def __init__(self, offline: bool, refresh: bool):
        self.offline, self.refresh = offline, refresh
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        CACHE.mkdir(parents=True, exist_ok=True)

    def text(self, cache_name: str, url: str, params: dict | None = None) -> str:
        f = CACHE / cache_name
        if f.exists() and not self.refresh:
            return f.read_text()
        # A failed request is cached too (as <name>.err holding the status),
        # so --offline reproduces the same result instead of stopping.
        err = f.with_name(f.name + ".err")
        if err.exists() and not self.refresh:
            raise LayerError(int(err.read_text()))
        if self.offline:
            raise SystemExit(f"[error] --offline but {f.relative_to(ROOT)} is not cached")
        r = self.session.get(url, params=params, timeout=60)
        time.sleep(DELAY_S)
        if not r.ok:
            err.parent.mkdir(parents=True, exist_ok=True)
            err.write_text(str(r.status_code))
            raise LayerError(r.status_code)
        err.unlink(missing_ok=True)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text)
        return r.text


def plain(html: str) -> str:
    """Catalogue descriptions are HTML fragments; keep the words."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    if len(text) > DESCRIPTION_MAX:
        text = text[:DESCRIPTION_MAX].rsplit(" ", 1)[0] + " …"
    return text


def layer_bbox(capabilities_xml: str) -> tuple[float, float, float, float] | None:
    """(west, south, east, north) of the layer, not of the service root.

    A WMS 1.3.0 document carries one EX_GeographicBoundingBox on the root
    layer (often the whole globe) and one on the named layer beneath it;
    the last one in the document is the layer's own.
    """
    boxes = re.findall(
        r"<EX_GeographicBoundingBox>\s*"
        r"<westBoundLongitude>([-\d.eE]+)</westBoundLongitude>\s*"
        r"<eastBoundLongitude>([-\d.eE]+)</eastBoundLongitude>\s*"
        r"<southBoundLatitude>([-\d.eE]+)</southBoundLatitude>\s*"
        r"<northBoundLatitude>([-\d.eE]+)</northBoundLatitude>",
        capabilities_xml,
    )
    if not boxes:
        return None
    w, e, s, n = (float(x) for x in boxes[-1])
    if (w, s, e, n) == (-180.0, -90.0, 180.0, 90.0):
        return None              # only the root's placeholder extent
    return (w, s, e, n)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use only cached responses")
    ap.add_argument("--refresh", action="store_true", help="re-fetch everything")
    args = ap.parse_args()
    fx = Fetcher(args.offline, args.refresh)
    today = date.today().isoformat()

    tree = json.loads(fx.text("layers.json", f"{BASE}/explore/api/layers"))
    if not isinstance(tree, list) or not tree:
        raise SystemExit("[error] /explore/api/layers did not return a group list")
    geom = {x["name"]: (x.get("geometry") or {}).get("geom_type")
            for x in json.loads(fx.text("ogc_layers.json", f"{BASE}/ogc/layers"))["layers"]}

    # Parent groups repeat their children, so index by id.
    groups: dict[int, dict] = {}
    layers: dict[int, dict] = {}

    def walk(g: dict) -> None:
        groups[g["id"]] = g
        for layer in g.get("layers", []):
            layers[layer["id"]] = layer
        for child in g.get("children", []):
            walk(child)

    for g in tree:
        walk(g)

    def group_path(gid: int | None) -> list[dict]:
        out = []
        while gid is not None and gid in groups:
            out.append(groups[gid])
            gid = groups[gid]["parent_id"]
        return out[::-1]

    visible = []
    for layer in layers.values():
        path = group_path(layer["group_id"])
        if layer.get("visible") and layer.get("status") == "active" \
                and path and all(g.get("visible") for g in path):
            visible.append((path, layer))
    visible.sort(key=lambda t: ([g["order"] for g in t[0]], t[1]["order"], t[1]["id"]))
    if not visible:
        raise SystemExit("[error] no visible layers in the catalogue")

    products = []
    failed: list[str] = []
    for i, (path, layer) in enumerate(visible, 1):
        name = layer["name"]
        wms = f"{BASE}/ogc/wms/{name}"
        # A layer whose service is broken on the portal still gets a
        # record — the fault is noted on it rather than hiding the layer.
        wms_error = None
        try:
            cap = fx.text(f"wms/{name}.xml", wms,
                          {"service": "WMS", "request": "GetCapabilities"})
            bbox = layer_bbox(cap)
        except LayerError as e:
            bbox, wms_error = None, e.status
        try:
            attrs = json.loads(fx.text(f"attributes/{name}.json",
                                       f"{BASE}/ogc/attributes/{name}", {"limit": 0}))
        except (LayerError, json.JSONDecodeError):
            attrs = {}
        aliases = attrs.get("column_aliases") or {}
        columns = [aliases.get(c, c) for c in attrs.get("columns") or []
                   if c.lower() not in INTERNAL_COLUMNS]

        harvest = layer.get("harvest_service") or {}
        upstream = harvest.get("service_url")
        host = urlparse(upstream).netloc if upstream else None
        downloadable = bool(layer.get("downloadable"))

        notes = [f"Geometry: {geom.get(name) or 'unknown'}."]
        if attrs.get("total_count") is not None:
            notes.append(f"{attrs['total_count']:,} features.")
        notes.append("Downloadable from the portal as GeoJSON, GeoPackage, KML or shapefile."
                     if downloadable else
                     "Download is disabled on the portal for this layer; view it through WMS.")
        if upstream:
            who = HOSTS.get(host) or ("ArcGIS Online" if host.endswith("arcgis.com") else host)
            notes.append(f"Harvested by the portal from {upstream} (served from {who}).")
        if harvest.get("last_harvest_date"):
            notes.append(f"Portal's last harvest: {harvest['last_harvest_date'][:10]}.")
        if wms_error:
            notes.append(f"WMS GetCapabilities returned HTTP {wms_error} on {today}.")
            failed.append(name)

        products.append({
            "archive_id": ARCHIVE_ID,
            "title": layer["display_name"].strip(),
            "identifier": name,
            "url": (f"{BASE}/data/download/layer/{layer['id']}?format=geojson" if downloadable
                    else f"{wms}?service=WMS&request=GetCapabilities"),
            "api_url": wms,
            "format_slug": "geojson" if downloadable else "ogc-wms",
            "license_slug": LICENSE,
            "bbox_min_lon": bbox[0] if bbox else None,
            "bbox_min_lat": bbox[1] if bbox else None,
            "bbox_max_lon": bbox[2] if bbox else None,
            "bbox_max_lat": bbox[3] if bbox else None,
            "variables_text": ", ".join(columns) or None,
            "category": " / ".join(g["name"].strip() for g in path),
            "description": plain(layer.get("description")) or None,
            "retrieved_at": today,
            "confidence": "high",
            "notes": " ".join(notes),
        })
        if i % 20 == 0 or i == len(visible):
            print(f"  [{i}/{len(visible)}] {name}")

    example = visible[0][1]
    archive = [{
        "archive_id": ARCHIVE_ID,
        "name": "EnviroData-NM — New Mexico Environmental Data Portal",
        "organization": "Natural Heritage New Mexico, Museum of Southwestern Biology, "
                        "University of New Mexico",
        "archive_type": "data-portal",
        "base_url": f"{BASE}/explore/",
        "api_url": f"{BASE}/ogc/",
        "api_doc_url": f"{BASE}/ogc/",
        "api_type": "ogc-wms-wfs",
        "license_slug": LICENSE,
        "doi_prefix": None,
        "notes": (
            "Housed and maintained by Natural Heritage New Mexico under the 2021 "
            "Environmental Database Act (HB51); contributing agencies include NM Game & "
            "Fish, NM Environment Department, State Land Office, NM Department of Health "
            "and EMNRD. This catalogue holds metadata and links only: the portal's terms "
            f"({BASE}/terms) do not permit redistributing the data, so every record points "
            "at the portal's own download or OGC endpoint."
        ),
    }]

    # Which catalogue facilities this archive belongs with. The ARID link is
    # the lto project owner's own statement (they are part of ARID), not
    # something either website documents, and is labelled as such.
    facility_archives = [
        {"facility_canonical_name": "Museum of Southwestern Biology",
         "archive_id": ARCHIVE_ID, "role": "primary", "scope_url": f"{BASE}/cms/about/",
         "notes": "Natural Heritage New Mexico, which runs the portal, is a division of "
                  "the Museum of Southwestern Biology (portal About page)."},
        {"facility_canonical_name":
             "ARID Institute — Accelerating Resilience Innovations in Drylands",
         "archive_id": ARCHIVE_ID, "role": "supporting", "scope_url": f"{BASE}/explore/",
         "notes": "This catalogue layer is an ARID-supported effort in support of "
                  "EnviroData-NM (statement of the lto project owner, an ARID member, "
                  "2026-10-09). Neither website documents the relationship."},
    ]

    ex_name, ex_id = example["name"], example["id"]
    endpoints = [
        {"path_or_url": f"{BASE}/explore/api/layers", "purpose": "metadata",
         "response_format": "json",
         "example_call": f"curl -s {BASE}/explore/api/layers",
         "notes": "Full catalogue: groups, layers, descriptions, upstream services. "
                  "Undocumented; found by inspection."},
        {"path_or_url": f"{BASE}/ogc/layers", "purpose": "metadata",
         "response_format": "json",
         "example_call": f"curl -s {BASE}/ogc/layers",
         "notes": "Layer names with geometry type and WMS / WFS URLs. Undocumented."},
        {"path_or_url": f"{BASE}/ogc/wms/{{layer}}", "purpose": "browse",
         "response_format": "image/png",
         "example_call": f"curl -s '{BASE}/ogc/wms/{ex_name}?service=WMS&request=GetCapabilities'",
         "notes": "OGC WMS 1.3.0, one service per layer. {layer} is the product identifier."},
        {"path_or_url": f"{BASE}/ogc/wfs/{{layer}}", "purpose": "metadata",
         "response_format": "xml",
         "example_call": f"curl -s '{BASE}/ogc/wfs/{ex_name}?service=WFS&version=1.1.0"
                         "&request=GetCapabilities'",
         "notes": "OGC WFS 1.1.0, one service per layer. GML output; "
                  "outputFormat=application/json is rejected."},
        {"path_or_url": f"{BASE}/ogc/attributes/{{layer}}", "purpose": "search",
         "response_format": "json",
         "example_call": f"curl -s '{BASE}/ogc/attributes/{ex_name}?limit=5&offset=0'",
         "notes": "Paged attribute rows (limit, offset) with total_count and column "
                  "aliases; no geometry. limit=0 returns the schema only."},
        {"path_or_url": f"{BASE}/data/download/layer/{{id}}", "purpose": "download",
         "response_format": "geojson",
         "example_call": f"curl -sO '{BASE}/data/download/layer/{ex_id}?format=geojson'",
         "notes": "Whole-layer download; format = geojson | gpkg | kml | shp. {id} is the "
                  "portal's numeric layer id (in each product's url). Returns 403 for "
                  "layers whose download the portal has disabled."},
    ]
    for e in endpoints:
        e.update({"archive_id": ARCHIVE_ID, "method": "GET", "schema_url": None})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for fname, rows in (("archives.json", archive), ("data_products.json", products),
                        ("api_endpoints.json", endpoints),
                        ("facility_archives.json", facility_archives)):
        (OUT_DIR / fname).write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")

    n_dl = sum(1 for p in products if p["format_slug"] == "geojson")
    n_bbox = sum(1 for p in products if p["bbox_min_lon"] is not None)
    print(f"[ok] {len(products)} layers ({n_dl} downloadable, {len(products) - n_dl} WMS-only), "
          f"{n_bbox} with a bounding box, {len(endpoints)} endpoint templates")
    if failed:
        print(f"[warn] WMS capabilities failed for {len(failed)} layer(s): {failed}")
    print(f"[ok] wrote {OUT_DIR.relative_to(ROOT)}/{{archives,data_products,api_endpoints,facility_archives}}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
