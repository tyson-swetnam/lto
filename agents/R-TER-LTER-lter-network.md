# R-TER-LTER — NSF LTER + LTREB long-term ecological sites

## Scope

All NSF Long-Term Ecological Research (LTER) sites currently in the
network (28 active as of 2026), plus selected NSF Long-Term Research in
Environmental Biology (LTREB) sites with ≥10 years of continuous record.

Note: marine LTERs (Palmer, MCR, CCE, NES, NGA) are catalogued here as
LTER members but use `primary_sphere = "ocean-estuarine"` (or
`"freshwater"` for NTL). McMurdo Dry Valleys uses `primary_sphere =
"cryosphere"` with secondary terrestrial. R-XREF reconciles overlaps.

## Sources

1. <https://lternet.edu/site/> — site index (primary).
2. Per-site primary URLs (Hubbard Brook, Konza, Jornada, Andrews, Sevilleta,
   Cedar Creek, Coweeta, Luquillo, Bonanza Creek, Niwot Ridge, Arctic,
   McMurdo, North Temperate Lakes, Plum Island, Florida Coastal Everglades,
   Georgia Coastal, Santa Barbara Coastal, Moorea Coral Reef, Palmer,
   Baltimore Ecosystem Study, Central Arizona-Phoenix, Kellogg Biological
   Station, Virginia Coast Reserve, Beaufort Lagoon Ecosystems, Northeast
   U.S. Shelf, Northern Gulf of Alaska, Minneapolis-St Paul Urban,
   California Current Ecosystem).
3. <https://portal.edirepository.org/> — Environmental Data Initiative
   (data portal URLs).
4. Peters et al. 2013 EcoTrends Tech. Bulletin 1931, Table 1-1 (initial
   site set + EcoTrends ecosystem-type assignment).

## Inputs

- `schema/vocab/*.csv`.
- For LTREB: <https://www.nsf.gov/funding/opportunities/long-term-research-environmental-biology-ltreb> award lookup.

## Outputs

- `data/raw/R-TER-LTER/facilities_lter.json`.

## Method

1. For each LTER site, emit one record with:
   - `facility_type` = `experimental-forest-range` for USFS-EFR-co-located
     LTERs (HBR, AND, BNZ, LUQ, CWT), else `university-field-station` for
     university-led sites, else `federal` for ARS/USFS-only.
   - `primary_sphere` per the table below.
   - `ecosystem_types` = the EcoTrends type from Peters 2013 Table 1-2.
   - `networks` = `["lter", …]` plus any co-listed networks.
2. For each site, list ≥1 location: HQ + a representative reference site
   (e.g. Watershed 6 at Hubbard Brook, Konza Prairie HQ at Manhattan KS).
3. Pull `established` from the site's history page; compute
   `record_length_years = 2026 - established` and set the threshold flag.
4. `data_portal_url` = the EDI scope landing page for the site.

## Sphere assignments (primary_sphere per LTER site)

| Site | Primary | Secondary |
|---|---|---|
| AND H.J. Andrews | terrestrial | atmosphere, freshwater |
| ARC Arctic | terrestrial | cryosphere, freshwater |
| BES Baltimore Ecosystem | terrestrial | atmosphere |
| BLE Beaufort Lagoon Ecosystems | ocean-estuarine | cryosphere |
| BNZ Bonanza Creek | terrestrial | atmosphere, cryosphere |
| CAP Central Arizona-Phoenix | terrestrial | atmosphere |
| CCE California Current | ocean-estuarine | |
| CDR Cedar Creek | terrestrial | |
| CWT Coweeta | terrestrial | freshwater |
| FCE Florida Coastal Everglades | ocean-estuarine | terrestrial |
| GCE Georgia Coastal Ecosystems | ocean-estuarine | terrestrial |
| HBR Hubbard Brook | terrestrial | atmosphere, freshwater |
| HFR Harvard Forest | terrestrial | atmosphere |
| JRN Jornada Basin | terrestrial | atmosphere, agriculture |
| KBS Kellogg Biological Station | terrestrial | agriculture |
| KNZ Konza Prairie | terrestrial | |
| LUQ Luquillo | terrestrial | freshwater |
| MCM McMurdo Dry Valleys | cryosphere | terrestrial, freshwater |
| MCR Moorea Coral Reef | ocean-estuarine | |
| MSP Minneapolis-St Paul Urban | terrestrial | freshwater |
| NES Northeast U.S. Shelf | ocean-estuarine | |
| NGA Northern Gulf of Alaska | ocean-estuarine | cryosphere |
| NTL North Temperate Lakes | freshwater | terrestrial |
| NWT Niwot Ridge | terrestrial | cryosphere |
| PAL Palmer Station | ocean-estuarine | cryosphere |
| PIE Plum Island Ecosystems | ocean-estuarine | terrestrial |
| SBC Santa Barbara Coastal | ocean-estuarine | |
| SEV Sevilleta | terrestrial | atmosphere |
| VCR Virginia Coast Reserve | ocean-estuarine | terrestrial |

## Known landmarks (must appear)

All 28 LTER sites listed above. Plus at least 5 LTREB sites including:
- **Coweeta–Long-term Hydrology and Climate** (LTREB, USFS-co-located).
- **Sapelo Island GCE LTREB**.
- **Mojave Global Change Facility** (LTREB).
- **Cary Institute Mirror Lake / Hubbard Brook LTREB**.
- **East River Watershed** (LTREB, CO).
