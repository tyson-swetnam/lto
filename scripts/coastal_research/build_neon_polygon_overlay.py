#!/usr/bin/env python3
"""Convert the raw NEON Field_Sampling_Boundaries pull into a clean
overlay GeoJSON for cod-kmap.

Replaces the previous point-based overlay (public/overlays/neon-sites.geojson)
with the authoritative polygon boundaries from NEON's published feature
service. The polygons are the actual sampling footprints — terrestrial
plots, AOP flight boxes, and aquatic watersheds — that NEON has
designated as their field sampling areas.

Source service:
  https://services1.arcgis.com/CMacGMvXwrlrpmOR/arcgis/rest/services/
  Field_Sampling_Boundaries/FeatureServer/0
  (Owned by NEON / Battelle Ecology, hosted on Esri AGOL.)

The raw pull lives in
``network_synth_spatial_analysis/coastal_protected/neon_field_sampling_boundaries.geojson``
and the published, properties-normalised overlay goes in
``public/overlays/neon-sites.geojson`` (overwriting the previous
point-only version).

Idempotent.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = (ROOT / "network_synth_spatial_analysis" / "coastal_protected"
       / "neon_field_sampling_boundaries.geojson")
OUT = ROOT / "public" / "overlays" / "neon-sites.geojson"

COASTAL_STATES = {
    "AL", "AK", "CA", "CT", "DE", "FL", "GA", "HI", "LA", "ME", "MD",
    "MA", "MS", "NH", "NJ", "NY", "NC", "OR", "RI", "SC", "TX", "VA",
    "WA", "PR", "VI", "GU", "MP", "AS",
}


def main() -> int:
    if not RAW.exists():
        print(f"[err] raw NEON polygons not found: {RAW}", file=sys.stderr)
        print(f"      run scripts/coastal_research/fetch_arcgis_resumable.py first",
              file=sys.stderr)
        return 2

    with RAW.open() as f:
        d = json.load(f)
    feats_in = d.get("features") or []
    print(f"[neon] reading {len(feats_in)} polygon boundaries", file=sys.stderr)

    feats_out = []
    for ft in feats_in:
        p = ft.get("properties") or {}
        geom = ft.get("geometry")
        if not geom:
            continue
        site_id = (p.get("siteID") or "").strip()
        site_name = re.sub(r"\s+NEON\s*$", "", (p.get("siteName") or "")).strip()
        site_type = (p.get("siteType") or "").strip()  # 'Core Terrestrial' / 'Gradient Terrestrial' / 'Core Aquatic' / etc
        domain_name = (p.get("domainName") or "").strip()
        domain_num = p.get("domainNumb")
        site_host = (p.get("siteHost") or "").strip()
        active = bool(p.get("activeSampling"))
        area_acres = p.get("acres")

        feats_out.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "name": site_name or site_id,
                "site_code": site_id,
                "site_type": site_type,
                # domainNumb is sometimes already 'D01' string, sometimes
                # an integer 1; normalise to the 'Dnn' form.
                "domain_code": (
                    str(domain_num) if isinstance(domain_num, str) and domain_num
                    else (f"D{int(domain_num):02d}" if domain_num is not None else None)
                ),
                "domain_name": domain_name,
                "kind": "neon-field-site",
                "manager": "National Ecological Observatory Network",
                "site_host": site_host or None,
                "active_sampling": active,
                "area_acres": (round(float(area_acres), 1) if area_acres else None),
                "url": f"https://www.neonscience.org/field-sites/{site_id.lower()}" if site_id else None,
                "source": ("https://services1.arcgis.com/CMacGMvXwrlrpmOR/arcgis/"
                           "rest/services/Field_Sampling_Boundaries/FeatureServer/0"),
            },
        })

    fc = {
        "type": "FeatureCollection",
        "features": feats_out,
        "metadata": {
            "source": ("https://services1.arcgis.com/CMacGMvXwrlrpmOR/arcgis/"
                       "rest/services/Field_Sampling_Boundaries/FeatureServer/0"),
            "owner": "Battelle Ecology / NEON",
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "feature_count": len(feats_out),
            "license": "NEON Data Use License — public, unrestricted",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fc))
    print(f"[neon] wrote {len(feats_out)} polygon features → "
          f"{OUT.relative_to(ROOT)}  ({os.path.getsize(OUT)//1024} KB)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
