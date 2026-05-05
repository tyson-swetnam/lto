"""Build data/raw/R10/facilities_synthesis_networks.json from the GeoJSON
layers in network_synth_spatial_analysis/.

The spatial-analysis folder holds point layers for individual member sites of
the networks catalogued in the COMPASS Ecosphere paper (LTER, LTREB,
MarineGEO, Sentinel Site, NERR, NEP, NMS). The R3 agent only captured the
parent networks as single HQ records; R10 emits one facility per member site
so they appear on the map as individual coastal observatories — including the
terrestrial coastal ecosystems (LTREB salt-marsh plots, NERR reserves, LTER
coastal sites) that motivate this extension.

Idempotent: re-running overwrites data/raw/R10/facilities_synthesis_networks.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPATIAL = ROOT / "network_synth_spatial_analysis"
OUT = ROOT / "data" / "raw" / "R10" / "facilities_synthesis_networks.json"

SOURCE_URL = "https://github.com/COMPASS-DOE/synthesis-networks"
RETRIEVED = "2026-04-23"
CONFIDENCE = "medium"  # KML-derived points; coordinates authoritative, metadata sparse


# ----------------------------------------------------------------------
# Per-network catalogue metadata (used when the point layer carries only name+xy).
# Fields:
#   network_slug   : slug matched against schema/vocab/networks.csv
#   facility_type  : value from schema/vocab/facility_types.csv
#   parent_org     : operational parent
#   research_areas : list of slugs from schema/vocab/research_areas.csv
#   url            : authoritative program page
# ----------------------------------------------------------------------

NETWORK_META = {
    "LTER": {
        "network_slug": "lter-site",
        "facility_type": "network",
        "parent_org": "US Long-Term Ecological Research Network",
        "research_areas": [
            "long-term-ecological-research",
            "coastal-processes",
            "coastal-terrestrial-ecosystems",
            "estuaries-and-wetlands",
        ],
        "url": "https://lternet.edu/site/",
        "funders": [{"name": "NSF", "relation": "grant"}],
        "networks": ["LTER", "lter-site"],
    },
    "LTREB": {
        "network_slug": "ltreb",
        "facility_type": "network",
        "parent_org": "NSF Long-term Research in Environmental Biology",
        "research_areas": [
            "long-term-ecological-research",
            "coastal-terrestrial-ecosystems",
            "salt-marshes",
            "tidal-wetlands",
        ],
        "url": "https://www.nsf.gov/funding/opportunities/long-term-research-environmental-biology-ltreb",
        "funders": [{"name": "NSF", "relation": "grant"}],
        "networks": ["LTREB"],
    },
    "MarineGEO": {
        "network_slug": "marinegeo",
        "facility_type": "network",
        "parent_org": "Smithsonian Tennenbaum Marine Observatories Network",
        "research_areas": [
            "marine-ecosystems",
            "biological-oceanography",
            "coastal-processes",
        ],
        "url": "https://marinegeo.si.edu",
        "funders": [{"name": "Smithsonian Institution", "relation": "parent-agency"}],
        "networks": ["MarineGEO"],
    },
    "Sentinel": {
        "network_slug": "sentinel-site",
        "facility_type": "federal",
        "parent_org": "NOAA Sentinel Site Program",
        "research_areas": [
            "climate-and-sea-level",
            "coastal-processes",
            "estuaries-and-wetlands",
            "coastal-disturbance",
        ],
        "url": "https://oceanservice.noaa.gov/sentinel-sites/",
        "funders": [{"name": "NOAA", "relation": "parent-agency"}],
        "networks": ["Sentinel-Site"],
    },
    "NERR": {
        "network_slug": "nerrs",
        "facility_type": "federal",
        "parent_org": "NOAA Office for Coastal Management",
        "research_areas": [
            "estuaries-and-wetlands",
            "coastal-processes",
            "salt-marshes",
            "tidal-wetlands",
            "coastal-terrestrial-ecosystems",
        ],
        "url": "https://coast.noaa.gov/nerrs/",
        "funders": [{"name": "NOAA Office for Coastal Management", "relation": "parent-agency"}],
        "networks": ["NERRS"],
    },
    "NEP": {
        "network_slug": "nep",
        "facility_type": "nonprofit",
        "parent_org": "EPA National Estuary Program",
        "research_areas": [
            "estuaries-and-wetlands",
            "coastal-processes",
            "tidal-wetlands",
            "coastal-terrestrial-ecosystems",
        ],
        "url": "https://www.epa.gov/nep",
        "funders": [{"name": "EPA", "relation": "parent-agency"}],
        "networks": ["NEP"],
    },
    "NMS": {
        "network_slug": "nms",
        "facility_type": "federal",
        "parent_org": "NOAA Office of National Marine Sanctuaries",
        "research_areas": [
            "marine-ecosystems",
            "coastal-processes",
            "biological-oceanography",
            "coral-reefs",
        ],
        "url": "https://sanctuaries.noaa.gov",
        "funders": [{"name": "NOAA", "relation": "parent-agency"}],
        "networks": ["NMS"],
    },
}


def load_geojson(relative_path: str) -> list[dict]:
    """Return features list for the given spatial-analysis file."""
    with (SPATIAL / relative_path).open() as fh:
        data = json.load(fh)
    return [f for f in data["features"] if f.get("geometry", {}).get("type") == "Point"]


def classify(name: str) -> str | None:
    """Classify a site by its name into a NETWORK_META key."""
    n = name.strip()
    # Order matters — Sentinel Sites sometimes reuse NERR names.
    if re.search(r"\bLTREB\b", n):
        return "LTREB"
    if re.search(r"\bLTER\b", n):
        return "LTER"
    if re.search(r"\bSentinel\b", n, re.IGNORECASE):
        return "Sentinel"
    if re.search(r"\bNERR\b", n):
        return "NERR"
    if re.search(r"\bMarine Sanctuary\b|\bNational Marine Sanctuary\b", n, re.IGNORECASE):
        return "NMS"
    if re.search(r"\bNEP\b|Estuary Program|Estuaries Partnership|Estuary Partnership|Partnership for the .* Estuary", n):
        return "NEP"
    return None


def make_record(seq: int, name: str, lng: float, lat: float, category: str) -> dict:
    meta = NETWORK_META[category]
    canonical = name.strip()
    acronym = None
    # Derive acronym from trailing token if uppercase
    trailing = canonical.split()[-1]
    if trailing.isupper() and 2 <= len(trailing) <= 7 and trailing.isalpha():
        acronym = trailing

    # URL is left null for individual member sites so D2's URL-based dedup
    # does not collapse every LTER/LTREB/NERR into a single row; the program
    # URL lives on the parent network entry.
    record = {
        "record_id": f"R10-{seq:04d}",
        "canonical_name": canonical,
        "acronym": acronym,
        "parent_org": meta["parent_org"],
        "facility_type": meta["facility_type"],
        "country": "US",
        "region": None,
        "hq": {"address": None, "lat": lat, "lng": lng},
        "locations": [{
            "label": canonical,
            "address": None,
            "lat": lat,
            "lng": lng,
            "role": "field-station" if meta["facility_type"] == "network" else "observatory",
        }],
        "research_areas": list(meta["research_areas"]),
        "networks": list(meta["networks"]),
        "funders": list(meta["funders"]),
        "url": None,
        "contact": None,
        "established": None,
        "provenance": {
            "source_url": SOURCE_URL,
            "retrieved_at": RETRIEVED,
            "confidence": CONFIDENCE,
            "agent": "R10",
        },
    }
    return record


# NEP polygon metadata (year designated, EPA region) — enriches the point record.
def load_nep_attributes() -> dict[str, dict]:
    path = SPATIAL / "NEP_BoundariesFY19" / "NEP_Boundaries2019.geojson"
    data = json.loads(path.read_text())
    out: dict[str, dict] = {}
    for f in data["features"]:
        p = f["properties"]
        name = (p.get("NEP_NAME") or "").strip()
        if not name:
            continue
        out[name.lower()] = {
            "year": int(p["YEAR_DESIG"]) if p.get("YEAR_DESIG") else None,
            "epa_region": p.get("EPA_REGION"),
            "area_sqmi": p.get("AREA_SQMI"),
        }
    return out


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # ----- Dedicated network-specific point files -----
    lter = [(f["properties"]["Name"], *f["geometry"]["coordinates"][:2]) for f in load_geojson("Land_Cover/LTER.geojson")]
    marinegeo = [(f["properties"]["Name"], *f["geometry"]["coordinates"][:2]) for f in load_geojson("Land_Cover/MarineGeo.geojson")]

    # ----- Coastal_NetworkSites__My_Places.geojson is the master compilation -----
    my_places = [(f["properties"]["Name"], *f["geometry"]["coordinates"][:2])
                 for f in load_geojson("Coastal_NetworkSites__My_Places.geojson")]

    records: list[dict] = []
    seen: set[tuple[str, float, float]] = set()
    seq = 0

    def emit(name: str, lng: float, lat: float, category: str) -> None:
        nonlocal seq
        key = (name.lower(), round(lng, 4), round(lat, 4))
        if key in seen:
            return
        seen.add(key)
        seq += 1
        records.append(make_record(seq, name, lng, lat, category))

    # LTER sites (10) — coastal-LTER program members.
    for name, lng, lat in lter:
        emit(f"{name} (LTER site)" if "LTER" not in name else name, lng, lat, "LTER")

    # MarineGEO sites (4) — rename to include network acronym so the dedupe
    # key against My_Places stays clean.
    for name, lng, lat in marinegeo:
        emit(f"{name} MarineGEO", lng, lat, "MarineGEO")

    # My_Places master list — covers LTREB, NEP, NERR, Sentinel, NMS.
    nep_attrs = load_nep_attributes()
    for name, lng, lat in my_places:
        category = classify(name)
        if category is None:
            # Silently skip anything we can't classify (keeps record provenance clean).
            continue
        rec_name = name.strip()
        seq_before = seq
        emit(rec_name, lng, lat, category)
        if category == "NEP" and seq > seq_before:
            # enrich with year designated / EPA region when we can match NEP_Boundaries2019
            key = rec_name.lower().replace(" nep", "").strip()
            # try multiple key variants
            for probe in (key, rec_name.lower(), rec_name.lower().replace("program", "").strip(),
                          rec_name.lower().replace("partnership", "").strip()):
                if probe in nep_attrs:
                    attrs = nep_attrs[probe]
                    if attrs.get("year"):
                        records[-1]["established"] = attrs["year"]
                    if attrs.get("epa_region"):
                        records[-1]["region"] = f"EPA Region {attrs['epa_region']}"
                    break

    OUT.write_text(json.dumps(records, indent=2))
    print(f"[ok] wrote {len(records)} records to {OUT.relative_to(ROOT)}")

    # Summary by network
    counts: dict[str, int] = {}
    for r in records:
        key = r["networks"][0] if r["networks"] else "?"
        counts[key] = counts.get(key, 0) + 1
    for k, v in sorted(counts.items()):
        print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
