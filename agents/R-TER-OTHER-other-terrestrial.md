# R-TER-OTHER — Other terrestrial / ecological observatories

## Scope

U.S. terrestrial long-term observatories that are NOT in the LTER, EFR, or
NEON networks (those are handled by R-TER-LTER, R-TER-EFR, R-TER-NEON).

Includes:
- UNESCO Man and the Biosphere (MAB) US Biosphere Reserves (47 reserves).
- NPS Inventory & Monitoring (I&M) network parks (32 networks across the
  National Park System; emit one record per I&M network HQ + selected
  long-record park units).
- NWRS National Wildlife Refuges with ≥30-year monitoring programs.
- USFS Research Natural Areas (>250) — emit only those with active
  long-term ecological monitoring (≥10y).
- Organization of Biological Field Stations (OBFS) member field stations
  with documented long-term monitoring.
- University of California Natural Reserve System (UC-NRS, 41 reserves).

Excludes: protected areas without active long-term monitoring; sites
covered by R-TER-LTER, R-TER-EFR, R-TER-NEON.

## Sources

1. <https://en.unesco.org/biosphere/eu-na> — MAB US directory.
2. <https://www.nps.gov/im/networks.htm> — NPS I&M networks.
3. <https://www.fws.gov/refuges/> — NWRS refuge directory.
4. <https://www.fs.usda.gov/research/rmrs/research-natural-areas> — RNAs.
5. <https://www.obfs.org/find-a-station> — OBFS member directory.
6. <https://ucnrs.org/reserves/> — UC-NRS reserves.

## Inputs

- All earlier R-TER outputs (to avoid duplicates).
- `schema/vocab/*.csv`.

## Outputs

- `data/raw/R-TER-OTHER/facilities_other.json`.

## Method

1. For each MAB Biosphere Reserve, emit one record with `facility_type =
   "protected-area-federal"` (or `"protected-area-state"` for state-managed)
   and `networks = ["mab-us", …]`. Link to the underlying NPS / NWRS / USFS
   protected-area facility ID via the `parent_org` field.
2. For NPS-IM, emit one record per network HQ (32 records) with
   `facility_type = "federal"`, `networks = ["nps-im"]`.
3. NWRS: filter to refuges with documented long-term programs (waterbird
   surveys, long-record vegetation plots). Mark `record_length_years`
   conservatively from the documented start of the dataset, not the
   refuge establishment year.
4. RNA: only emit RNAs with active monitoring. Otherwise leave for a
   future expansion.
5. OBFS / UC-NRS: emit member stations as
   `facility_type = "university-field-station"` with `networks =
   ["ofs"]` or `["nrs"]`.

## Known landmarks

- **Sequoia & Kings Canyon Biosphere Reserve** (CA, MAB).
- **Big Bend Biosphere Reserve** (TX, MAB).
- **Aleutian Islands Biosphere Reserve** (AK, MAB).
- **NPS-IM Sierra Nevada Network** (CA).
- **NPS-IM Greater Yellowstone Network** (WY/MT/ID).
- **Patuxent Research Refuge** (MD, NWRS, with the Patuxent Bird Banding
  Lab long-record).
- **Hawaiian Forest Bird Survey** (HI, NWRS / USGS PIERC, long-record).
- **UC-NRS Sagehen Creek Field Station** (CA).
- **UC-NRS Bodega Marine Reserve** (CA, also marine — co-list with
  R-AQ-OCEAN-CULL).
- **Rocky Mountain Biological Laboratory** (CO, OBFS).
- **Mountain Lake Biological Station** (VA, OBFS, also NEON MLBS).
- **Cary Institute of Ecosystem Studies** (NY, OBFS).
- **Smithsonian Environmental Research Center / SERC** (MD).
