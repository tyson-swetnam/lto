#!/usr/bin/env python3
"""R-AQ-OCEAN-CULL curation pass.

Filters cod-kmap heritage records (data/raw/R{1..10}/facilities_*.json)
for the LTO U.S.-only ocean/estuarine scope and emits two files:

  * facilities_ocean_us.json  (kept records, with LTO fields added)
  * dropped.json              (dropped records, with reason)

Run from anywhere; uses absolute paths.
"""

from __future__ import annotations

import glob
import json
import os
import re
from collections import OrderedDict
from datetime import date
from typing import Any

ROOT = "/home/user/lto/data/raw"
OUT_DIR = os.path.join(ROOT, "R-AQ-OCEAN-CULL")
OUT_KEEP = os.path.join(OUT_DIR, "facilities_ocean_us.json")
OUT_DROP = os.path.join(OUT_DIR, "dropped.json")

US_COUNTRIES = {"US", "PR", "VI", "AS", "GU", "MP"}
US_AGENCY_PATTERNS = [
    r"\bNSF\b",
    r"\bNOAA\b",
    r"\bNASA\b",
    r"\bUSAP\b",
    r"\bU\.S\. Antarctic Program\b",
    r"\bUnited States Antarctic Program\b",
    r"\bUSGS\b",
    r"\bU\.S\. Geological Survey\b",
    r"\bDOE\b",
    r"\bDepartment of Energy\b",
    r"\bU\.S\. Department of Energy\b",
    r"\bEPA\b",
]
US_AGENCY_RE = re.compile("|".join(US_AGENCY_PATTERNS))

CURRENT_YEAR = 2026  # per spec: record_length_years = 2026 - established


def has_us_funder(funders: list[dict] | None) -> bool:
    if not funders:
        return False
    for f in funders:
        name = (f or {}).get("name") or ""
        if US_AGENCY_RE.search(name):
            return True
    return False


def load_inputs() -> list[tuple[str, dict]]:
    """Return list of (source_relpath, record) tuples in stable order."""
    out = []
    paths = []
    for r_idx in range(1, 12):  # R1..R11; skip if absent
        d = os.path.join(ROOT, f"R{r_idx}")
        if not os.path.isdir(d):
            continue
        for p in sorted(glob.glob(os.path.join(d, "facilities_*.json"))):
            paths.append(p)
    for p in paths:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            continue
        for rec in data:
            out.append((os.path.relpath(p, ROOT), rec))
    return out


# Heuristic: classify primary_sphere and secondary_spheres for each kept record.
FRESHWATER_NAMES = (
    # NEPs that are riverine / inland-water-only would qualify; cod-kmap's
    # NEP set is all coastal-estuarine, so default is ocean-estuarine.  Still,
    # support overrides if added later.
)
GREAT_LAKES_HINTS = (
    "great lakes",
    "lake superior",
    "lake erie",
    "lake michigan",
    "lake huron",
    "lake ontario",
    "old woman creek",  # Lake Erie NERR
    "lake superior nerr",
)
TERRESTRIAL_SECONDARY_HINTS = (
    "nerr",                # NERRs include upland watershed acreage
    "estuarine research reserve",
    "national estuary program",
    " nep",
    "estuary partnership",
    "estuary program",
    "coastal national",
    "sanctuary",            # NMS often has coastal land mgmt elements
    "watershed",
    "marinegeo",            # SERC / coastal-watershed sites
)
ATMOSPHERE_SECONDARY_HINTS = (
    "flux tower",
    "ameriflux",
    "eddy covariance",
)


def classify_spheres(rec: dict) -> tuple[str, list[str]]:
    name = (rec.get("canonical_name") or "").lower()
    networks = [str(n).lower() for n in (rec.get("networks") or [])]
    research = [str(r).lower() for r in (rec.get("research_areas") or [])]
    blob = " ".join([name] + networks + research + [json.dumps(rec).lower()])

    # primary_sphere — default ocean-estuarine; override to freshwater for
    # inland-water-only facilities.  Great Lakes labs stay ocean-estuarine
    # per spec (treated as coastal/Great-Lakes), unless wholly freshwater
    # research-station scope without coastal/estuarine work.
    primary = "ocean-estuarine"

    secondary: list[str] = []
    if any(h in blob for h in TERRESTRIAL_SECONDARY_HINTS):
        secondary.append("terrestrial")
    if any(h in blob for h in ATMOSPHERE_SECONDARY_HINTS):
        secondary.append("atmosphere")

    # Deduplicate while preserving order
    seen = set()
    secondary = [s for s in secondary if not (s in seen or seen.add(s))]
    return primary, secondary


def compute_record_length(established: Any) -> tuple[int | None, bool]:
    if established is None:
        return None, False
    try:
        yr = int(established)
    except (TypeError, ValueError):
        return None, False
    rl = CURRENT_YEAR - yr
    if rl < 0:
        rl = 0
    return rl, rl >= 10


def decide(rec: dict) -> tuple[bool, str]:
    """Return (keep, reason). reason is empty when keep=True."""
    country = rec.get("country")
    funders = rec.get("funders") or []
    if country in US_COUNTRIES:
        return True, ""
    if country == "AQ" and has_us_funder(funders):
        return True, ""
    # Drop reasons
    if country == "CA":
        return False, "out-of-scope: Canada (CA)"
    if country == "MX":
        return False, "out-of-scope: Mexico (MX)"
    if country in {"BZ", "CR", "PA", "GT", "HN", "NI", "SV"}:
        return False, f"out-of-scope: Central America ({country})"
    if country in {"AR", "BR", "CL", "CO", "EC", "PE", "UY", "VE", "GY", "SR", "GF", "BO", "PY"}:
        return False, f"out-of-scope: South America ({country})"
    if country in {"BB", "BS", "CU", "DO", "HT", "JM", "TT", "GD", "LC", "VC", "DM", "AG", "KN"}:
        return False, f"out-of-scope: non-territory Caribbean ({country})"
    if country == "AQ":
        return False, "out-of-scope: Antarctic facility without U.S. (NSF/NOAA/NASA/USAP) funding"
    if country is None:
        return False, "out-of-scope: country missing"
    return False, f"out-of-scope: country={country}"


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    today = date.today().isoformat()

    raw = load_inputs()

    kept_by_key: "OrderedDict[str, dict]" = OrderedDict()
    dropped: list[dict] = []
    seq = 0

    for src, rec in raw:
        keep, reason = decide(rec)
        if not keep:
            dropped.append({
                "source_file": src,
                "source_record_id": rec.get("record_id"),
                "canonical_name": rec.get("canonical_name"),
                "country": rec.get("country"),
                "drop_reason": reason,
            })
            continue

        # Dedup key: prefer cod-kmap facility_id if present, else canonical_name lower-cased.
        fkey = rec.get("facility_id") or (rec.get("canonical_name") or "").strip().lower()
        if not fkey:
            # Fall back to a per-record unique key so we don't lose records.
            fkey = f"__norefkey__::{src}::{rec.get('record_id')}"

        if fkey in kept_by_key:
            # Merge networks + funders + locations into the existing record.
            existing = kept_by_key[fkey]
            ex_nets = existing.get("networks") or []
            new_nets = rec.get("networks") or []
            merged_nets = list(dict.fromkeys([*ex_nets, *new_nets]))
            existing["networks"] = merged_nets

            ex_fund = existing.get("funders") or []
            new_fund = rec.get("funders") or []
            seen_funders = {(f.get("name"), f.get("relation")) for f in ex_fund}
            for f in new_fund:
                key = (f.get("name"), f.get("relation"))
                if key not in seen_funders:
                    ex_fund.append(f)
                    seen_funders.add(key)
            existing["funders"] = ex_fund

            srcs = existing.setdefault("source_records", [])
            srcs.append({
                "source_file": src,
                "source_record_id": rec.get("record_id"),
            })
            continue

        # New keep — build LTO record.
        seq += 1
        new_id = f"R-AQ-OCEAN-CULL-{seq:04d}"
        primary, secondary = classify_spheres(rec)
        rl, threshold = compute_record_length(rec.get("established"))

        merged = dict(rec)  # shallow copy preserves all original fields
        merged["record_id"] = new_id
        merged["source_record_id"] = rec.get("record_id")  # stable join key
        merged["primary_sphere"] = primary
        merged["secondary_spheres"] = secondary
        merged["record_length_years"] = rl
        merged["long_term_threshold_met"] = threshold
        merged["source_records"] = [{
            "source_file": src,
            "source_record_id": rec.get("record_id"),
        }]
        # Preserve / extend provenance
        prov = dict(merged.get("provenance") or {})
        prov.setdefault("source_url", prov.get("source_url"))
        prov["curated_by"] = "R-AQ-OCEAN-CULL"
        prov["curated_at"] = today
        merged["provenance"] = prov

        kept_by_key[fkey] = merged

    kept_records = list(kept_by_key.values())

    with open(OUT_KEEP, "w", encoding="utf-8") as fh:
        json.dump(kept_records, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(OUT_DROP, "w", encoding="utf-8") as fh:
        json.dump(dropped, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # Summary on stdout.
    print(f"kept:    {len(kept_records)}")
    print(f"dropped: {len(dropped)}")
    by_country: dict[str, int] = {}
    for d in dropped:
        c = d.get("country") or "<none>"
        by_country[c] = by_country.get(c, 0) + 1
    print("dropped by country:")
    for c, n in sorted(by_country.items(), key=lambda kv: -kv[1]):
        print(f"  {c}: {n}")


if __name__ == "__main__":
    main()
