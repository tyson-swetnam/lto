#!/usr/bin/env python3
"""Convert the four new coastal-terrestrial overlays into facility-record
JSON files that the existing scripts/ingest.py pipeline can ingest.

Output (one file per layer, all under data/raw/R11_coastal_ecosystems/):

  facilities_fws_coastal.json       — coastal USFWS units (NWR, WMD, COORD, NM)
  facilities_nps_coastal.json       — coastal NPS units (parks, seashores,
                                       monuments, etc.) from the LRD service
  facilities_usfs_special.json      — coastal RNAs / Experimental Forests /
                                       Botanical / Natural / Scenic areas
  facilities_wilderness_coastal.json — coastal designated Wilderness Areas

Each record matches the schema scripts/ingest.py expects: canonical_name,
acronym, parent_org, facility_type, country, region (state name), hq
(address/lat/lng), locations[], research_areas[], networks[], funders[],
url, contact, established, provenance.

The HQ point is the polygon's representative_point() — guaranteed to be
inside the geometry, which is what we want for a "where do I stick the
map dot" coordinate. Real HQ visitor-centre coordinates can be added
later by hand for individual high-value units.

Idempotent: rerun overwrites the four JSON files. Skip-list at the top
keeps known duplicates from being re-ingested. The facility_id is hashed
the same way scripts/ingest.py hashes (sha1(name+acronym)[:16]) so
re-ingesting one of these records onto an existing row is a no-op upsert.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent.parent
OVERLAYS = ROOT / "public" / "overlays"
OUT_DIR = ROOT / "data" / "raw" / "R11_coastal_ecosystems"

# Names already present as facilities in cod-kmap — skip to avoid creating
# a second record. Filled out from gap_report.md cross-validation; keep
# the list short and deterministic so re-runs are stable.
SKIP_NAMES_BY_LAYER: dict[str, set[str]] = {
    "coastal-nps-units": {
        # The 3 NPS units that already exist as facility rows.
        "Cape Cod National Seashore",
        "Cape Hatteras National Seashore",
        "Point Reyes National Seashore",
    },
}


def slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out


def fid(name: str, acronym: str | None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# Per-layer build configuration -------------------------------------------

US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "CA": "California", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MS": "Mississippi", "NH": "New Hampshire", "NJ": "New Jersey",
    "NY": "New York", "NC": "North Carolina", "OR": "Oregon", "RI": "Rhode Island",
    "SC": "South Carolina", "TX": "Texas", "VA": "Virginia", "WA": "Washington",
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "GU": "Guam",
    "MP": "Northern Mariana Islands", "AS": "American Samoa",
}


def title_name(s: str, layer_id: str) -> str:
    """Convert FWS uppercase to title-case, leave NPS already-title alone."""
    if layer_id == "coastal-fws-units":
        words = s.title().split()
        small = {"And", "Of", "The", "On", "For", "At", "In", "By"}
        return " ".join(w if i == 0 else (w.lower() if w in small else w)
                        for i, w in enumerate(words))
    return s


def fws_record(props: dict, hq: tuple[float, float]) -> dict:
    name = title_name(props["name"], "coastal-fws-units")
    acr = props.get("acronym")  # the FWS literal code (e.g. RACH for Rachel Carson)
    kind = props.get("kind", "national-wildlife-refuge")
    state = props.get("state")
    return {
        "record_id": f"R11-FWS-{slug(name)}",
        "canonical_name": name,
        "acronym": acr,
        "parent_org": "U.S. Fish and Wildlife Service",
        "facility_type": "protected-area-federal",
        "country": "US",
        "region": US_STATE_NAMES.get(state, state),
        "hq": {"address": None, "lat": hq[1], "lng": hq[0]},
        "locations": [{
            "label": name,
            "address": None,
            "lat": hq[1], "lng": hq[0],
            "role": "headquarters",
        }],
        "research_areas": [
            "estuaries-and-wetlands",
            "coastal-terrestrial-ecosystems",
            "salt-marshes",
        ],
        "networks": ["NWRS"],
        "funders": [{"name": "U.S. Fish and Wildlife Service", "relation": "parent-agency"}],
        "url": None,
        "contact": None,
        "established": None,
        "extra": {
            "designation_kind": kind,
            "area_acres": props.get("area_acres"),
            "min_coast_km": props.get("min_coast_km"),
            "geometry_simplified": props.get("geometry_simplified"),
        },
        "provenance": {
            "source_url": props.get("source"),
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "confidence": "high",
            "agent": "R11",
        },
    }


def nps_record(props: dict, hq: tuple[float, float]) -> dict:
    name = props["name"]
    code = props.get("acronym")  # NPS UNIT_CODE (4-letter) is on the literal field
    kind = props.get("kind", "")  # NPS UNIT_TYPE preserved verbatim
    state = props.get("state")
    return {
        "record_id": f"R11-NPS-{slug(name)}",
        "canonical_name": name,
        "acronym": code,
        "parent_org": "National Park Service",
        "facility_type": "protected-area-federal",
        "country": "US",
        "region": US_STATE_NAMES.get(state, state),
        "hq": {"address": None, "lat": hq[1], "lng": hq[0]},
        "locations": [{
            "label": name,
            "address": None,
            "lat": hq[1], "lng": hq[0],
            "role": "headquarters",
        }],
        "research_areas": [
            "coastal-terrestrial-ecosystems",
            "estuaries-and-wetlands",
            "marine-ecology",
        ],
        "networks": ["NPS-IM"],   # NPS Inventory & Monitoring
        "funders": [{"name": "National Park Service", "relation": "parent-agency"}],
        "url": f"https://www.nps.gov/{code.lower()}/index.htm" if code else None,
        "contact": None,
        "established": None,
        "extra": {
            "designation_kind": kind,
            "min_coast_km": props.get("min_coast_km"),
        },
        "provenance": {
            "source_url": props.get("source"),
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "confidence": "high",
            "agent": "R11",
        },
    }


def usfs_special_record(props: dict, hq: tuple[float, float]) -> dict:
    name = props["name"]
    kind = (props.get("kind") or "").lower().replace(" ", "-")
    state = props.get("state")
    return {
        "record_id": f"R11-USFS-{slug(name)}",
        "canonical_name": name,
        "acronym": None,
        "parent_org": "U.S. Forest Service",
        "facility_type": "protected-area-federal",
        "country": "US",
        "region": US_STATE_NAMES.get(state, state),
        "hq": {"address": None, "lat": hq[1], "lng": hq[0]},
        "locations": [{
            "label": name, "address": None,
            "lat": hq[1], "lng": hq[0], "role": "headquarters",
        }],
        "research_areas": [
            "coastal-terrestrial-ecosystems",
            "long-term-ecological-research",
        ],
        "networks": ["USFS-RNA-EF"],
        "funders": [{"name": "U.S. Forest Service", "relation": "parent-agency"}],
        "url": None,
        "contact": None,
        "established": None,
        "extra": {
            "designation_kind": kind,
            "area_acres": props.get("area_acres"),
            "min_coast_km": props.get("min_coast_km"),
        },
        "provenance": {
            "source_url": props.get("source"),
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "confidence": "high",
            "agent": "R11",
        },
    }


def wilderness_record(props: dict, hq: tuple[float, float]) -> dict:
    name = props["name"]
    state = props.get("state")
    return {
        "record_id": f"R11-WILD-{slug(name)}",
        "canonical_name": name,
        "acronym": None,
        "parent_org": "National Wilderness Preservation System",
        "facility_type": "protected-area-federal",
        "country": "US",
        "region": US_STATE_NAMES.get(state, state),
        "hq": {"address": None, "lat": hq[1], "lng": hq[0]},
        "locations": [{
            "label": name, "address": None,
            "lat": hq[1], "lng": hq[0], "role": "headquarters",
        }],
        "research_areas": [
            "coastal-terrestrial-ecosystems",
            "wildlife-conservation",
        ],
        "networks": ["NWPS"],
        "funders": [{"name": "U.S. Forest Service", "relation": "parent-agency"}],
        "url": None, "contact": None, "established": None,
        "extra": {
            "area_acres": props.get("area_acres"),
            "min_coast_km": props.get("min_coast_km"),
            "geometry_simplified": props.get("geometry_simplified"),
        },
        "provenance": {
            "source_url": props.get("source"),
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "confidence": "high",
            "agent": "R11",
        },
    }


def state_protected_record(props: dict, hq: tuple[float, float]) -> dict:
    name = props["name"]
    kind = props.get("kind", "state-protected")
    state = props.get("state")
    manager = props.get("manager") or "State agency"
    return {
        "record_id": f"R11-STAT-{slug(name)}",
        "canonical_name": name,
        "acronym": None,
        "parent_org": manager,
        "facility_type": "protected-area-state",
        "country": "US",
        "region": US_STATE_NAMES.get(state, state),
        "hq": {"address": None, "lat": hq[1], "lng": hq[0]},
        "locations": [{
            "label": name, "address": None,
            "lat": hq[1], "lng": hq[0], "role": "headquarters",
        }],
        "research_areas": [
            "coastal-terrestrial-ecosystems",
            "estuaries-and-wetlands",
            "wildlife-conservation",
        ],
        "networks": [],
        "funders": [{"name": manager, "relation": "parent-agency"}],
        "url": None, "contact": None, "established": None,
        "extra": {
            "designation_kind": kind,
            "area_acres": props.get("area_acres"),
            "min_coast_km": props.get("min_coast_km"),
            "geometry_simplified": props.get("geometry_simplified"),
            "manager": manager,
        },
        "provenance": {
            "source_url": props.get("source"),
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "confidence": "high",
            "agent": "R11",
        },
    }


def ngo_pvt_record(props: dict, hq: tuple[float, float]) -> dict:
    name = props["name"]
    kind = props.get("kind", "private-conservation")
    state = props.get("state")
    manager = props.get("manager") or "NGO / private"
    fac_type = ("protected-area-private"
                if kind.startswith(("private-", "local-"))
                or "ngo" in kind
                else "protected-area-private")
    return {
        "record_id": f"R11-NGO-{slug(name)}",
        "canonical_name": name,
        "acronym": None,
        "parent_org": manager,
        "facility_type": fac_type,
        "country": "US",
        "region": US_STATE_NAMES.get(state, state),
        "hq": {"address": None, "lat": hq[1], "lng": hq[0]},
        "locations": [{
            "label": name, "address": None,
            "lat": hq[1], "lng": hq[0], "role": "headquarters",
        }],
        "research_areas": [
            "coastal-terrestrial-ecosystems",
            "wildlife-conservation",
        ],
        "networks": [],
        "funders": [{"name": manager, "relation": "manager"}],
        "url": None, "contact": None, "established": None,
        "extra": {
            "designation_kind": kind,
            "area_acres": props.get("area_acres"),
            "min_coast_km": props.get("min_coast_km"),
            "manager": manager,
        },
        "provenance": {
            "source_url": props.get("source"),
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "confidence": "high",
            "agent": "R11",
        },
    }


LAYER_BUILDERS = {
    "coastal-fws-units": ("facilities_fws_coastal.json", fws_record),
    "coastal-nps-units": ("facilities_nps_coastal.json", nps_record),
    "coastal-usfs-special": ("facilities_usfs_special.json", usfs_special_record),
    "coastal-wilderness": ("facilities_wilderness_coastal.json", wilderness_record),
    "coastal-state-protected": ("facilities_state_protected.json", state_protected_record),
    "coastal-ngo-private": ("facilities_ngo_private.json", ngo_pvt_record),
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    totals = {}
    for layer_id, (out_name, builder) in LAYER_BUILDERS.items():
        in_path = OVERLAYS / f"{layer_id}.geojson"
        with in_path.open() as f:
            d = json.load(f)
        skip = SKIP_NAMES_BY_LAYER.get(layer_id, set())
        records = []
        seen_ids = set()
        for ft in d.get("features") or []:
            props = ft["properties"]
            nm = props.get("name", "").strip()
            if not nm or nm in skip:
                continue
            try:
                geom = shape(ft["geometry"])
                rep = geom.representative_point()
            except Exception:
                continue
            rec = builder(props, (float(rep.x), float(rep.y)))
            this_id = fid(rec["canonical_name"], rec.get("acronym"))
            if this_id in seen_ids:
                continue
            seen_ids.add(this_id)
            records.append(rec)
        out_path = OUT_DIR / out_name
        out_path.write_text(json.dumps(records, indent=2))
        totals[layer_id] = len(records)
        print(f"  {out_name:42s} {len(records):4d} records")
    print(f"[ok] wrote {sum(totals.values())} R11 facility records to "
          f"{OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
