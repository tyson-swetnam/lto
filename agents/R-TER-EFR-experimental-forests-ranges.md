# R-TER-EFR — USFS Experimental Forests & Ranges (EFR)

## Scope

The 77 formally designated USDA Forest Service Experimental Forests and
Experimental Ranges (per Lugo et al. 2006 BioScience 56(1):39–48), covering
196,300 ha and 14 of the 38 Holdridge life zones in the conterminous U.S.,
plus Caribbean subtropical and Alaskan boreal sites.

Includes USDA-ARS Range Research Laboratories that co-locate with the EFR
network in the Lugo 2006 framing.

## Sources

1. <https://www.fs.usda.gov/research/programs/efr> — EFR program (primary).
2. <https://www.fsl.orst.edu/lter/pubs/webdocs/reports/lugobiosci.cfm>
   — supplemental tables to Lugo et al. 2006 with per-EFR coordinates,
   forest cover type, and Holdridge life zone.
3. Adams et al. 2004 (USDA Tech Bulletin) — historical EFR establishment
   dates and acreage.
4. <https://nrs.fs.fed.us/ef/> — Northern Research Station EFRs.
5. <https://www.srs.fs.usda.gov/research/forests-grasslands/> — Southern
   Research Station EFRs.
6. <https://www.fs.usda.gov/rmrs/experimental-forests-ranges> — Rocky
   Mountain Research Station EFRs.
7. <https://www.fs.usda.gov/research/pnw/efr> — Pacific Northwest Research
   Station EFRs.

## Inputs

- `schema/vocab/{spheres,facility_types,networks,life_zones,ecosystem_types}.csv`.
- Lugo et al. 2006 Table 1 (Holdridge life zone counts) — already extracted
  to `life_zones.csv`.

## Outputs

- `data/raw/R-TER-EFR/facilities_efr.json`.

## Method

1. One record per EFR with:
   - `facility_type = "experimental-forest-range"`.
   - `primary_sphere = "terrestrial"`. Many EFRs span freshwater
     (gauged watersheds) and atmosphere (long-record meteorology) — set
     `secondary_spheres` accordingly. Use known-watershed EFRs (Coweeta,
     Hubbard Brook, San Dimas, Caspar Creek, Marcell, Fernow, Andrews,
     Caspar) → secondary `freshwater`. Use known-atmosphere-instrumented
     EFRs (Andrews, Hubbard Brook, Howland, Niwot, Bondville, Bonanza,
     Marcell) → secondary `atmosphere`.
   - `parent_org = "USDA Forest Service <Station name>"`.
   - `networks = ["usfs-rna-ef", …]` + LTER, MAB-US, LTREB where applicable.
2. `established` = year EFR was designated; `record_length_years` from
   start of weather records (often earlier than designation).
3. `life_zones` per Lugo 2006 Holdridge classification. Use slugs from
   `schema/vocab/life_zones.csv`.
4. `ecosystem_types` per EcoTrends categories where assignable; otherwise
   from forest cover type (oak-hickory, loblolly-shortleaf, ponderosa pine,
   etc.).
5. Mark dual EFR/LTER sites with both `lter` and `usfs-rna-ef` in networks.
6. Mark dual EFR/MAB sites with `mab-us`. The 12 EFR-MAB overlaps per Lugo
   2006 must be tagged.

## Known landmarks (must appear, ≥30 of 77)

- **Hubbard Brook Experimental Forest** (NH, 1955) — USFS+LTER+LTREB.
- **H.J. Andrews Experimental Forest** (OR, 1948) — USFS+LTER.
- **Coweeta Hydrologic Laboratory** (NC, 1934) — USFS+LTER.
- **Bonanza Creek Experimental Forest** (AK, 1963) — USFS+LTER.
- **Luquillo Experimental Forest** (PR, 1939) — USFS+LTER, MAB.
- **Fernow Experimental Forest** (WV, 1934).
- **Bent Creek Experimental Forest** (NC).
- **Cascade Head Experimental Forest** (OR).
- **Caspar Creek Experimental Watershed** (CA).
- **Crossett Experimental Forest** (AR).
- **Fraser Experimental Forest** (CO).
- **Glacier Lakes Ecosystem Experiments Site / GLEES** (WY, 1990s).
- **Harrison Experimental Forest** (MS).
- **Marcell Experimental Forest** (MN).
- **Priest River Experimental Forest** (ID, 1911).
- **Santee Experimental Forest** (SC).
- **Silas Little Experimental Forest** (NJ).
- **Black Mountain Experimental Forest** (CA).
- **Escambia Experimental Forest** (AL).
- **Great Basin Experimental Range** (UT).
- **Starkey Experimental Forest and Range** (OR).
- **Howland Forest Research Site** (ME) — proxy for Penobscot EF.
- **San Dimas Experimental Forest** (CA, 1933).
- **Donaldson Tract Experimental Forest** (FL).
- **Sandy Hill Experimental Forest** (FL).
- **Chequamegon-Nicolet Long-term Soil Productivity** (WI).
