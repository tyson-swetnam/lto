# R-FUND — Funding-flow enrichment

## Scope

Enrich every facility in the LTO database with funding-flow data —
who funds it, what awards, fiscal-year amounts, parent-agency lineage.

This agent reuses the existing cod-kmap funding pipeline:
`scripts/fetch_funding_nsf.py`, `scripts/fetch_funding_usaspending.py`,
`scripts/fetch_funding_990.py`, and the manual override CSVs in
`data/funding_overrides/`.

## Sources

1. <https://www.nsf.gov/awardsearch/> — NSF Award Search API (primary
   for LTER, NEON, LTREB, OOI awards).
2. <https://api.usaspending.gov/> — USAspending.gov (federal grants and
   contracts; covers USDA, NOAA, DOE, EPA, USACE, USGS, NPS, DOI, NASA).
3. <https://reporter.nih.gov/> — NIH RePORTER (rarely used; NIH-funded
   field stations like Patuxent Bird Banding Lab).
4. ProPublica Nonprofit Explorer (Form 990 for foundation / NGO funders).
5. Agency budget appropriations PDFs for institutional baseline funding
   (USDA-ARS, USFS, NSF DEB, USGS, EPA — already partially captured by
   `scripts/load_agency_budgets.py`).

## Inputs

- `data/raw/R-AQ-OCEAN-CULL/facilities_ocean_us.json` and all `R-*`
  outputs from Wave B.

## Outputs

- `data/raw/R-FUND/funding_events.csv` — keyed to facility_id,
  fiscal_year, award_id; matches the `funding_events` table schema.
- `data/raw/R-FUND/funders.csv` — funder dimension table.

## Method

1. For each facility, derive a search term set: canonical_name + acronym +
   any locations[*].label.
2. NSF: hit Award Search with each term; filter to awards whose
   `awardee_name` or `program_element` matches the facility. Capture
   per-fiscal-year obligated amounts.
3. USAspending.gov: hit `/api/v2/search/spending_by_award/` with
   `recipient_search_text`. Capture `transaction_obligated_amount` per
   FY.
4. Form 990: only for NGO / foundation facilities (TNC, Audubon, Cary
   Institute, MBARI, etc.).
5. Agency baseline: for federal facilities, set a `relation =
   "appropriation"` row per FY using agency budget appropriations
   (lump-sum estimate, flagged `confidence = "low"`).
6. Apply manual overrides from `data/funding_overrides/*.csv` last (these
   are curator-validated mappings).

## Known landmarks (must produce funding rows)

- **Hubbard Brook**: NSF LTREB awards 1998–2025 + USDA Forest Service
  baseline appropriation.
- **Konza Prairie / KNZ-LTER**: NSF DEB LTER awards (DEB-1440484,
  DEB-2025849, …).
- **NEON**: NSF construction (DBI-0653158, …) and operations
  (cooperative agreement DBI-1724433) awards.
- **LTAR network**: USDA-ARS appropriation lines via USAspending.gov.
- **IOOS Regional Associations**: NOAA NA21NOS… cooperative-agreement
  family.
- **Mauna Loa Observatory**: NOAA appropriation + occasional NASA
  contracts.
- **WHOI**: NSF + NOAA + ONR awards (multi-million per FY).
