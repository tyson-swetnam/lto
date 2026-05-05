# R-AQ-FRESH — Freshwater observatories

## Scope

U.S. long-term **freshwater** observatories — rivers, lakes, headwater
watersheds, and groundwater monitoring. ≥10y record.

Includes:
- USGS National Water Information System (NWIS) long-record gauges
  (≥100-year stage/discharge stations as a curated subset).
- USGS Water, Energy, and Biogeochemical Budgets (WEBB) sites
  (Sleepers River VT, Loch Vale CO, Andrews Creek WA, Panola GA,
  Trout Lake WI, Allequash Creek WI, Icacos PR).
- USGS Hydrologic Benchmark Network (HBN, ~50 sites).
- North Temperate Lakes LTER (NTL, WI).
- Hubbard Brook Experimental Watershed reference catchments (NH).
- Great Lakes long-term monitoring labs (NOAA GLERL, EPA GLNPO).
- GLEON U.S. member sites.
- EPA National Aquatic Resource Surveys (NARS) — National Lakes Assessment,
  National Rivers and Streams Assessment, National Wetland Condition
  Assessment, National Coastal Condition Assessment (treat as one
  programmatic record per assessment).

Excludes: weather-station-only sites; non-U.S. sites; ocean / estuarine
sites (those go to R-AQ-OCEAN-CULL).

## Sources

1. <https://waterdata.usgs.gov/nwis> — NWIS (primary).
2. <https://water.usgs.gov/webb/> — WEBB.
3. <https://water.usgs.gov/nasqan/progdocs/factsheets/hbnfact/hbnfactsheet.html> — HBN.
4. <https://lter.limnology.wisc.edu/> — NTL-LTER.
5. <https://hubbardbrook.org/> — HBR hydrology.
6. <https://www.glerl.noaa.gov/> — GLERL.
7. <https://www.epa.gov/great-lakes-monitoring> — GLNPO.
8. <https://gleon.org/sites> — GLEON.
9. <https://www.epa.gov/national-aquatic-resource-surveys> — NARS.

## Inputs

- `schema/vocab/{spheres,networks,facility_types,research_areas}.csv`.
- Peters et al. 2013 Table 1-1 (Loch Vale Watershed, Walker Branch,
  Caspar Creek, North Temperate Lakes — already in the dataset).

## Outputs

- `data/raw/R-AQ-FRESH/facilities_fresh.json`.

## Method

1. NWIS: emit a single `streamgage-network` facility per long-record
   gauge OR per gauging-program HQ. Suggested approach: one record per
   ≥80-year-record gauge (about ~150 stations), each with
   `primary_sphere = "freshwater"`, `parent_org = "USGS Water Mission
   Area"`, `networks = ["nwis", "usgs-hbn"]` if HBN-listed.
2. WEBB: 7 records, each `facility_type = "field-station"`, `primary_sphere
   = "freshwater"`, with `secondary_spheres` per the catchment context.
3. HBN: emit subset (~50 stations) as light records linking to NWIS
   parent gauge.
4. NTL-LTER: 11 primary lakes (Trout Bog, Crystal, Sparkling, Big
   Muskellunge, Allequash, Trout, Mendota, Monona, Wingra, Fish, Madison
   chain). Use `lter` network and primary `freshwater`.
5. Hubbard Brook freshwater: emit Watershed 6 + Mirror Lake as separate
   freshwater facilities cross-linked to the HBR terrestrial record.
6. NOAA GLERL, EPA GLNPO: federal observatories with `networks` including
   `goos` and a Great-Lakes-specific tag (`great-lakes` research-area).
7. GLEON: emit U.S. member sites listed in the GLEON site directory.

## Known landmarks

- **Loch Vale Watershed** (CO, 1983 — USGS WEBB).
- **Sleepers River Research Watershed** (VT, 1959).
- **Andrews Creek / Andrews Forest** (OR, 1953 — co-listed with EFR).
- **Panola Mountain Research Watershed** (GA).
- **Trout Lake Station** (WI, NTL).
- **Allequash Creek** (WI, NTL).
- **Icacos** (PR — USGS WEBB tropical).
- **NOAA Great Lakes Environmental Research Laboratory / GLERL**
  (Ann Arbor, MI).
- **EPA Great Lakes National Program Office / GLNPO** (Chicago, IL).
- **Hubbard Brook Watershed 6 reference catchment** (NH, 1963).
- **Mirror Lake Long-term Monitoring** (NH, 1981 — Cary Institute).
- **Lake Mendota long-term limnological record** (WI, 1894 — among the
  longest continuous lake records in the world).
- **Toolik Lake** (AK — Arctic LTER).
- **USGS gauge 01400500 — Raritan River at Manville NJ** (1903–).
- **USGS gauge 06190500 — Yellowstone River at Corwin Springs MT**
  (1890–).
- **USGS gauge 11447650 — Sacramento River at Freeport CA** (1923–).
