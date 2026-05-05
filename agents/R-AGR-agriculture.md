# R-AGR — Agriculture observatories

## Scope

U.S. long-term **agricultural** observatories. Covers agroecosystems
managed for cropping, rangeland grazing, irrigation, or dairy/livestock
research, with ≥10-year continuous record.

Includes:
- USDA-ARS Long-Term Agroecosystem Research (LTAR) network — 18 sites.
- USDA-ARS Range Research Laboratories (Jornada, Walnut Gulch, Reynolds
  Creek, Central Plains, Fort Keogh, Grasslands, Grazinglands, Eastern
  Oregon, Sheep Experiment Station).
- USDA Climate Hubs (10 regional hubs).
- NRCS Soil Climate Analysis Network (SCAN).
- Land-Grant University Experiment Stations with documented long-term
  experiments (e.g. Morrow Plots U. Illinois, Sanborn Field U. Missouri,
  Magruder Plots Oklahoma State, Lethbridge Old Crop Rotations, Rothamsted
  US analogs).
- KBS Long-Term Ecological Research Agricultural site (KBS-LTER).
- Mead UNL Carbon Sequestration Project / Mead Eddy-Flux site (NEB).

## Sources

1. <https://ltar.ars.usda.gov/sites/> — LTAR site directory (primary).
2. <https://www.ars.usda.gov/research/locations/> — ARS research locations.
3. <https://www.climatehubs.usda.gov/> — Climate Hubs.
4. <https://www.nrcs.usda.gov/wps/portal/wcc/home/aboutScan/> — SCAN.
5. <https://lter.kbs.msu.edu/> — KBS-LTER.
6. <https://nature.berkeley.edu/biometlab/> and other land-grant long-term
   experiment compendia.

## Inputs

- `schema/vocab/{spheres,networks,facility_types}.csv`.
- Peters et al. 2013 Table 1-1 — ARS sites overlapping with EcoTrends
  (Eastern Oregon Agricultural Research Center, Fort Keogh, Grassland
  Soil and Water, Grazinglands, Jornada, Reynolds Creek).

## Outputs

- `data/raw/R-AGR/facilities_agr.json`.

## Method

1. One record per LTAR site with `facility_type = "ltar-site"`,
   `primary_sphere = "agriculture"`, `networks = ["ltar", …]`. Many LTAR
   sites are also LTER (Jornada, KBS) — set `secondary_spheres =
   ["terrestrial"]` and add `lter` to networks.
2. ARS rangeland research labs as `facility_type = "experimental-forest-range"`
   (the slug covers ARS RR labs in our vocab) with `primary_sphere =
   "agriculture"`, secondary `terrestrial`.
3. Climate Hubs: `facility_type = "federal"`, `networks = ["climate-hubs"]`,
   role of HQ = `office`.
4. SCAN: emit as a single network record for now (one row per long-record
   SCAN station with ≥30y record; defer broad rollout to a later wave).
5. Land-grant long-term experiments: `facility_type = "university-field-station"`,
   `networks = ["ars-lt-experiments"]`.

## Known landmarks

- **Jornada Experimental Range / LTAR** (NM, 1912 — also USDA-ARS
  rangeland, also LTER).
- **Walnut Gulch Experimental Watershed / LTAR** (AZ, 1953).
- **Reynolds Creek LTAR** (ID, 1962 — also EcoTrends RCE).
- **Central Plains Experimental Range / LTAR** (CO, 1939 — also NEON CPER).
- **Fort Keogh Livestock and Range Research Lab** (MT, 1924).
- **Grasslands Soil and Water Research Lab** (TX).
- **Grazinglands Research Lab** (OK).
- **Eastern Oregon Agricultural Research Center / EOARC** (OR).
- **Kellogg Biological Station LTER-AG** (MI, 1988).
- **Morrow Plots** (U. Illinois, 1876 — oldest U.S. continuous agricultural
  experiment).
- **Sanborn Field** (U. Missouri, 1888).
- **Magruder Plots** (Oklahoma State, 1892).
- **Mead UNL Carbon Sequestration / NEB** (NE, 2001).
- **U.S. Sheep Experiment Station** (DuBois, ID, 1915).
- All 10 USDA Climate Hubs (Northeast, Northern Forests, Midwest,
  Southeast, Southern Plains, Northern Plains, Northwest, Pacific
  Islands, Caribbean, Southwest).
