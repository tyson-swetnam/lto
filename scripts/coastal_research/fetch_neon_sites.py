#!/usr/bin/env python3
"""Fetch all NEON field sites from the NEON Data Portal API and emit:

  1. ``public/overlays/neon-sites.geojson`` — a point-feature GeoJSON
     overlay registered as the new map layer.
  2. ``data/raw/R11_coastal_ecosystems/facilities_neon_sites.json`` —
     R11-shaped facility records the existing ``ingest_r11.py``
     consumes.

Source: https://data.neonscience.org/api/v0/sites — public, no key
required, returns 81 NEON field sites (Core + Gradient, terrestrial +
aquatic) with site code, name, lat/lng, state, ecological domain, and
the data products available at each.

Idempotent. Re-running overwrites both outputs.
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
API = "https://data.neonscience.org/api/v0/sites"
OUT_OVERLAY = ROOT / "public" / "overlays" / "neon-sites.geojson"
OUT_FAC = ROOT / "data" / "raw" / "R11_coastal_ecosystems" / "facilities_neon_sites.json"
OUT_RAW = (ROOT / "network_synth_spatial_analysis" / "coastal_protected"
           / "neon_sites.geojson")

# 23 ocean coastal states + AK + HI + 5 territories. NEON sites in
# these are flagged is_coastal=True in the facility record so the
# downstream Map view can highlight them, but ALL NEON sites are
# included in the overlay regardless.
COASTAL_STATES = {
    "AL", "AK", "CA", "CT", "DE", "FL", "GA", "HI", "LA", "ME", "MD",
    "MA", "MS", "NH", "NJ", "NY", "NC", "OR", "RI", "SC", "TX", "VA",
    "WA", "PR", "VI", "GU", "MP", "AS",
}

US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AR": "Arkansas", "AZ": "Arizona",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "IA": "Iowa", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "MA": "Massachusetts",
    "MD": "Maryland", "ME": "Maine", "MI": "Michigan", "MN": "Minnesota",
    "MO": "Missouri", "MS": "Mississippi", "MT": "Montana", "NC": "North Carolina",
    "ND": "North Dakota", "NE": "Nebraska", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NV": "Nevada", "NY": "New York", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "PR": "Puerto Rico",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VA": "Virginia",
    "VI": "U.S. Virgin Islands", "VT": "Vermont", "WA": "Washington",
    "WI": "Wisconsin", "WV": "West Virginia", "WY": "Wyoming",
    "GU": "Guam", "MP": "Northern Mariana Islands", "AS": "American Samoa",
}


def fid(name: str, acronym: str | None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out


def fetch_sites() -> list[dict]:
    req = urllib.request.Request(API, headers={"User-Agent": "cod-kmap/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")).get("data") or []


def write_overlay(sites: list[dict]) -> int:
    """Point-feature GeoJSON for the map overlay."""
    feats = []
    for s in sites:
        if s.get("siteLatitude") is None or s.get("siteLongitude") is None:
            continue
        # Strip the trailing ' NEON' suffix some site names carry; the
        # NEON brand is already implied by the layer.
        nm = re.sub(r"\s+NEON\s*$", "", s.get("siteName") or "").strip()
        feats.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(s["siteLongitude"]),
                                float(s["siteLatitude"])],
            },
            "properties": {
                "name": nm,
                "site_code": s.get("siteCode"),
                "site_type": s.get("siteType"),     # CORE | GRADIENT
                "state": s.get("stateCode"),
                "state_name": s.get("stateName"),
                "domain_code": s.get("domainCode"),
                "domain_name": s.get("domainName"),
                "kind": "neon-field-site",
                "manager": "National Ecological Observatory Network",
                "is_coastal": s.get("stateCode") in COASTAL_STATES,
                "n_data_products": len(s.get("dataProducts") or []),
                "source": API,
                "url": f"https://www.neonscience.org/field-sites/{(s.get('siteCode') or '').lower()}",
            },
        })
    fc = {
        "type": "FeatureCollection",
        "features": feats,
        "metadata": {
            "source": API,
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "feature_count": len(feats),
            "license": "Public domain (US federal data)",
        },
    }
    OUT_OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    OUT_OVERLAY.write_text(json.dumps(fc))
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    OUT_RAW.write_text(json.dumps(fc, indent=2))
    return len(feats)


def write_facilities(sites: list[dict]) -> int:
    """R11 facility-record JSON the existing ingest_r11.py loads."""
    today = time.strftime("%Y-%m-%d")
    recs = []
    for s in sites:
        lat = s.get("siteLatitude")
        lng = s.get("siteLongitude")
        if lat is None or lng is None:
            continue
        nm = re.sub(r"\s+NEON\s*$", "", s.get("siteName") or "").strip()
        # Use the format 'NEON ABBY — Abby Road' so the facility list
        # surfaces both the human-readable name and the NEON site code.
        canonical_name = f"NEON {s['siteCode']} — {nm}" if nm else f"NEON {s['siteCode']}"
        state = s.get("stateCode")
        coastal = state in COASTAL_STATES
        recs.append({
            "record_id": f"R11-NEON-{slug(s.get('siteCode') or canonical_name)}",
            "canonical_name": canonical_name,
            "acronym": s.get("siteCode"),
            "parent_org": "National Ecological Observatory Network",
            # NEON sites are a federal observing-network field site, not
            # a protected area in the cod-kmap taxonomy. Use the
            # 'observatory' facility_type slug so they cluster with
            # other ocean / atmospheric observatory points.
            "facility_type": "observatory",
            "country": "US",
            "region": US_STATE_NAMES.get(state, state),
            "hq": {"address": None, "lat": lat, "lng": lng},
            "locations": [{
                "label": canonical_name,
                "address": None,
                "lat": lat, "lng": lng,
                "role": "field-station",
            }],
            "research_areas": [
                "long-term-ecological-research",
                "coastal-terrestrial-ecosystems"
                if coastal else "long-term-ecological-research",
            ],
            "networks": ["NEON"],
            "funders": [{"name": "National Science Foundation",
                         "relation": "parent-agency"}],
            "url": f"https://www.neonscience.org/field-sites/{(s.get('siteCode') or '').lower()}",
            "contact": None,
            "established": None,
            "extra": {
                "site_type": s.get("siteType"),
                "domain_code": s.get("domainCode"),
                "domain_name": s.get("domainName"),
                "is_coastal": coastal,
                "n_data_products": len(s.get("dataProducts") or []),
            },
            "provenance": {
                "source_url": API,
                "retrieved_at": today,
                "confidence": "high",
                "agent": "R11",
            },
        })
    OUT_FAC.parent.mkdir(parents=True, exist_ok=True)
    OUT_FAC.write_text(json.dumps(recs, indent=2))
    return len(recs)


def main() -> int:
    print(f"[neon] fetching {API}", file=sys.stderr)
    sites = fetch_sites()
    print(f"[neon] {len(sites)} sites in API response", file=sys.stderr)
    coastal = sum(1 for s in sites if s.get("stateCode") in COASTAL_STATES)
    print(f"[neon]   coastal-state subset: {coastal}", file=sys.stderr)

    n_overlay = write_overlay(sites)
    n_fac = write_facilities(sites)
    print(f"[neon] wrote overlay: {n_overlay} features → "
          f"{OUT_OVERLAY.relative_to(ROOT)}", file=sys.stderr)
    print(f"[neon] wrote facility records: {n_fac} → "
          f"{OUT_FAC.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
