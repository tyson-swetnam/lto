#!/usr/bin/env python3
"""Build a US-Ramsar-sites GeoJSON from Wikipedia's curated table.

Source:
  https://en.wikipedia.org/wiki/List_of_Ramsar_sites_in_the_United_States

That page is sourced from the Ramsar Convention Sites Information Service
(rsis.ramsar.org), which is gated behind Cloudflare and not directly
machine-readable. Wikipedia maintains a clean wikitable mirror with name,
state, lat/lng (in DMS), area, and designation date — perfectly suitable
for our coastal-observatory map's research-area-context layer.

Output:
  network_synth_spatial_analysis/coastal_protected/ramsar_us.geojson
  (Point features — Ramsar centroids, since the published list doesn't
  include polygon boundaries.)

Subsequent ``filter_coastal.py`` runs would skip points (they expect
polygons), so this script writes facility records directly into
``data/raw/R11_coastal_ecosystems/facilities_ramsar.json`` in the same
shape that ``ingest_r11.py`` consumes.

Idempotent — overwrites both outputs on each run.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GEO_OUT = (ROOT / "network_synth_spatial_analysis" / "coastal_protected"
           / "ramsar_us.geojson")
FACS_OUT = ROOT / "data" / "raw" / "R11_coastal_ecosystems" / "facilities_ramsar.json"

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_Ramsar_sites_in_the_United_States"


# 23 ocean coastal states + AK + HI + 5 territories. Used to mark a
# Ramsar site as "coastal-relevant" for the cod-kmap map.
COASTAL_STATES = {
    "Alabama", "Alaska", "California", "Connecticut", "Delaware", "Florida",
    "Georgia", "Hawaii", "Louisiana", "Maine", "Maryland", "Massachusetts",
    "Mississippi", "New Hampshire", "New Jersey", "New York",
    "North Carolina", "Oregon", "Rhode Island", "South Carolina", "Texas",
    "Virginia", "Washington",
    "Puerto Rico", "U.S. Virgin Islands", "Guam",
    "Northern Mariana Islands", "American Samoa",
}

# State abbrev for the facility region field (matches ingest_r11.py)
STATE_TO_NAME = {  # already canonical names; kept for symmetry
    s: s for s in COASTAL_STATES
}


def fetch_html() -> str:
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": "cod-kmap/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_dms(loc: str) -> tuple[float, float] | None:
    """Pull lat/lng from a Wikipedia DMS string like
    '36°25′N 116°20′W' or '36.417°N 116.333°W'. Returns (lat, lng) in
    decimal degrees, or None if not parseable."""
    m = re.search(
        r"(\d+(?:\.\d+)?)°(?:(\d+)(?:[′'](\d+(?:\.\d+)?)\")?)?[′']?\s*([NS])"
        r"\s*(\d+(?:\.\d+)?)°(?:(\d+)(?:[′'](\d+(?:\.\d+)?)\")?)?[′']?\s*([EW])",
        loc,
    )
    if not m:
        return None
    lat_d, lat_m_, lat_s, lat_h, lon_d, lon_m_, lon_s, lon_h = m.groups()
    lat = float(lat_d)
    if lat_m_:
        lat += float(lat_m_) / 60.0
        if lat_s:
            lat += float(lat_s) / 3600.0
    if lat_h == "S":
        lat = -lat
    lon = float(lon_d)
    if lon_m_:
        lon += float(lon_m_) / 60.0
        if lon_s:
            lon += float(lon_s) / 3600.0
    if lon_h == "W":
        lon = -lon
    return lat, lon


def parse_state(loc_cell: str) -> str | None:
    """First word(s) before the DMS coordinate = state name."""
    # Take everything before the first digit-degree pattern
    m = re.split(r"\d+°", loc_cell, maxsplit=1)
    if not m or not m[0].strip():
        return None
    return m[0].strip()


def parse_area(area_cell: str) -> float | None:
    """Wikipedia uses 'X.YZ mi2' or sometimes 'X.YZ km2'. Convert to
    acres. Strip HTML entities."""
    txt = re.sub(r"<[^>]+>", "", area_cell)
    txt = txt.replace("&#160;", " ").replace("&nbsp;", " ").strip()
    m = re.match(r"^([\d,]+(?:\.\d+)?)\s*(mi2|sq mi|km2|sq km|ha|acres?)", txt, re.I)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    if unit in ("mi2", "sq mi"):
        return val * 640.0
    if unit in ("km2", "sq km"):
        return val * 247.105
    if unit == "ha":
        return val * 2.47105
    if unit.startswith("acre"):
        return val
    return None


def parse_table(html: str) -> list[dict]:
    table_m = re.search(
        r"<table[^>]*class=[\"\'][^\"\']*wikitable[^\"\']*[\"\'][^>]*>(.*?)</table>",
        html, re.S,
    )
    if not table_m:
        raise RuntimeError("could not find Ramsar wikitable on page")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_m.group(1), re.S)
    sites: list[dict] = []
    for row in rows[1:]:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
        if len(cells) < 4:
            continue
        name = re.sub(r"<[^>]+>", "", cells[0]).strip()
        loc_cell = cells[1]
        loc_text = re.sub(r"<[^>]+>", " ", loc_cell)
        loc_text = re.sub(r"\.mw-parser-output[^{]*{[^}]*}", "", loc_text)
        loc_text = re.sub(r"&#x[0-9a-fA-F]+;|&[a-zA-Z]+;", " ", loc_text)
        state = parse_state(loc_text)
        coords = parse_dms(loc_text)
        area_acres = parse_area(cells[2])
        designated = re.sub(r"<[^>]+>", "", cells[3]).strip()
        desc = (re.sub(r"<[^>]+>", "", cells[4]).strip()
                if len(cells) >= 5 else "")
        if not name or not coords:
            continue
        lat, lon = coords
        sites.append({
            "name": name,
            "state": state,
            "lat": lat, "lng": lon,
            "area_acres": round(area_acres, 1) if area_acres else None,
            "designated": designated,
            "description": desc[:400] if desc else None,
        })
    return sites


def fid(name: str, acronym: str | None = None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def write_geojson(sites: list[dict]) -> int:
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lng"], s["lat"]]},
            "properties": {
                "name": s["name"],
                "state": s["state"],
                "kind": "ramsar-site",
                "manager": "Ramsar Convention (designated by U.S. State Department)",
                "area_acres": s["area_acres"],
                "designated": s["designated"],
                "description": s["description"],
                "source": WIKI_URL,
            },
        } for s in sites],
        "metadata": {
            "source_url": WIKI_URL,
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "feature_count": len(sites),
            "license": "Wikipedia content, CC BY-SA 4.0",
        },
    }
    GEO_OUT.parent.mkdir(parents=True, exist_ok=True)
    GEO_OUT.write_text(json.dumps(fc, indent=2))
    return len(sites)


def write_facilities(sites: list[dict]) -> int:
    """One R11 facility record per Ramsar site, in the format
    scripts/coastal_research/ingest_r11.py + scripts/ingest.py expect."""
    today = time.strftime("%Y-%m-%d")
    recs = []
    for s in sites:
        coastal = s["state"] in COASTAL_STATES
        rec = {
            "record_id": f"R11-RAMSAR-{re.sub(r'[^a-z0-9]+','-', s['name'].lower()).strip('-')}",
            "canonical_name": f"{s['name']} (Ramsar)",
            "acronym": None,
            "parent_org": "Ramsar Convention on Wetlands",
            "facility_type": "protected-area-federal",
            "country": "US",
            "region": s["state"],
            "hq": {"address": None, "lat": s["lat"], "lng": s["lng"]},
            "locations": [{
                "label": s["name"], "address": None,
                "lat": s["lat"], "lng": s["lng"], "role": "headquarters",
            }],
            "research_areas": [
                "estuaries-and-wetlands",
                "coastal-terrestrial-ecosystems",
                "wildlife-conservation",
                "tidal-wetlands" if coastal else "long-term-ecological-research",
            ],
            "networks": ["RAMSAR"],
            "funders": [{"name": "Ramsar Convention",
                         "relation": "international-designation"}],
            "url": "https://www.ramsar.org/wetland/united-states-of-america",
            "contact": None,
            # facilities.established is INT32 (year). Pull the 4-digit
            # year out of the wikipedia date string ("1 September 1998").
            "established": (
                int(re.search(r"(\d{4})", s["designated"]).group(1))
                if s["designated"] and re.search(r"(\d{4})", s["designated"])
                else None
            ),
            "extra": {
                "designation_kind": "ramsar-site",
                "area_acres": s["area_acres"],
                "designated": s["designated"],
                "is_coastal": coastal,
                "description": s["description"],
            },
            "provenance": {
                "source_url": WIKI_URL,
                "retrieved_at": today,
                "confidence": "high",
                "agent": "R11",
            },
        }
        recs.append(rec)
    FACS_OUT.parent.mkdir(parents=True, exist_ok=True)
    FACS_OUT.write_text(json.dumps(recs, indent=2))
    return len(recs)


def main() -> int:
    print(f"[ramsar] fetching {WIKI_URL}", file=sys.stderr)
    html = fetch_html()
    sites = parse_table(html)
    print(f"[ramsar] parsed {len(sites)} US Ramsar sites", file=sys.stderr)
    coastal = sum(1 for s in sites if s["state"] in COASTAL_STATES)
    print(f"[ramsar]   coastal-relevant: {coastal}", file=sys.stderr)
    n_geo = write_geojson(sites)
    n_fac = write_facilities(sites)
    print(f"[ramsar] wrote GeoJSON: {n_geo} features → {GEO_OUT.relative_to(ROOT)}",
          file=sys.stderr)
    print(f"[ramsar] wrote facility records: {n_fac} → {FACS_OUT.relative_to(ROOT)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
