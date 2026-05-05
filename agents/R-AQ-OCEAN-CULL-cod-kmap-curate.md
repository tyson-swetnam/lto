# R-AQ-OCEAN-CULL — Curate cod-kmap heritage data for U.S. ocean & estuarine scope

## Scope

This agent does **not** collect new data. It reviews the existing
`data/raw/R1..R10/facilities_*.json` outputs vendored from cod-kmap and
re-emits the U.S.-and-territory subset under the LTO ocean/estuarine
sphere, dropping non-U.S. facilities per the project's U.S.-only scope.

Keep:
- All R1 records (U.S. federal).
- All R2 records (U.S. universities).
- All R3 records (networks/consortia operating in the U.S.).
- All R4 records (U.S. state/local/NGO).
- All R10 records (COMPASS-DOE synthesis-networks; U.S.-focused).
- R8 records that fall in U.S. territories (PR, VI).
- Any R7 records that are U.S.-funded Antarctic ocean stations (rare).

Drop:
- All R5 records (Canada).
- All R6 records (Mexico, Central America).
- Most R7 records (South America) — flag any U.S.-funded research as
  candidates for keep.
- Non-territory R8 records (Cuba, DR, Haiti, Bahamas, Jamaica).

## Sources

This is a curation pass against vendored data; the only "source" is
`data/raw/R*/facilities_*.json`.

## Inputs

- `data/raw/R1/facilities_*.json` … `data/raw/R10/facilities_*.json`.
- `schema/vocab/spheres.csv`.

## Outputs

- `data/raw/R-AQ-OCEAN-CULL/facilities_ocean_us.json` — combined,
  deduplicated U.S. + territory + U.S.-funded Antarctic facility records,
  each with `primary_sphere = "ocean-estuarine"` (override to `freshwater`
  for inland-water-only facilities like Great Lakes labs, where applicable),
  preserving cod-kmap network memberships and provenance.
- `data/raw/R-AQ-OCEAN-CULL/dropped.json` — records dropped from scope,
  with reason field, for audit.

## Method

1. Load every JSON under `data/raw/R{1..10}/` into memory.
2. For each record:
   - If `country in {US, PR, VI, AS, GU, MP}` → keep.
   - Else if `country == AQ` AND `funders[*].name` includes a U.S. agency
     (NSF, NOAA, USAP, NASA) → keep with note.
   - Else → drop with reason recorded.
3. Add LTO-required fields:
   - `primary_sphere = "ocean-estuarine"` for marine / estuarine /
     coastal / Great-Lakes facilities; `freshwater` for any
     freshwater-only facilities accidentally captured by cod-kmap (e.g.
     a riverine NEP).
   - `secondary_spheres` = `["terrestrial"]` for coastal-watershed labs
     (NERR upland portions, NPS coastal protected-area land), `["atmosphere"]`
     where the facility runs a flux tower.
   - `record_length_years` and `long_term_threshold_met` — best-effort
     from the existing `established` field (`record_length_years = 2026 -
     established`).
   - Carry over the existing `record_id` as a stable join key, but prefix
     `R-AQ-OCEAN-CULL-` and a sequence number for the new ID.
4. Deduplicate by `facility_id` (the cod-kmap hash); emit one merged
   record when the same facility appears in multiple R-agents.

## Known landmarks (must keep)

- **NOAA PMEL** (Seattle, WA + Newport, OR field station).
- **NOAA AOML** (Miami, FL).
- **Woods Hole Oceanographic Institution / WHOI** (MA).
- **Scripps Institution of Oceanography** (CA).
- **Lamont-Doherty Earth Observatory** (NY).
- All 11 IOOS Regional Associations (NERACOOS, MARACOOS, SECOORA, GCOOS,
  CARICOOS, SCCOOS, CeNCOOS, NANOOS, AOOS, PacIOOS, plus great-lakes if
  applicable).
- All 29 NERR reserves.
- **OOI Coastal Pioneer**, **OOI Coastal Endurance**, **OOI Global
  Irminger**, **OOI Global Argentine** (those with U.S.-relevant coverage).
- All 14 NMS sanctuaries plus marine national monuments.
- All 28 NEP estuary programs.
- **MarineGEO** Smithsonian network (US members).
