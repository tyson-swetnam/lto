# R-XREF — Cross-sphere reconciliation

## Scope

This is a **post-hoc** reconciliation agent. It does not emit new
facilities; it audits the union of all `R-*` outputs and writes a
mapping of `facility_id` → corrected `secondary_spheres`, plus a list
of cross-agent duplicates (same physical site emitted by two R-agents).

## Inputs

- All `data/raw/R-*/facilities_*.json` files written by Wave B.

## Outputs

- `data/raw/R-XREF/sphere_overrides.json` — array of `{ facility_id,
  primary_sphere, secondary_spheres, rationale }` records that the
  ingest pipeline applies as a final overlay.
- `data/raw/R-XREF/duplicates.json` — array of duplicate clusters
  `{ canonical_name, agents: [...], facility_ids: [...], suggested_keep_id }`.
- `data/raw/R-XREF/coverage_report.md` — markdown summary of coverage by
  sphere, network, ecosystem type, life zone, and state.

## Method

1. Load every `R-*` output. Build a candidate-duplicate index keyed on
   `(lower(canonical_name), round(hq_lat, 3), round(hq_lng, 3))` and on
   `acronym`.
2. For each candidate cluster, choose the keep record by priority:
   `R-TER-LTER > R-TER-EFR > R-TER-NEON > R-AGR > R-CRY > R-ATM >
   R-AQ-FRESH > R-AQ-OCEAN-CULL > R-TER-OTHER`. The other records merge
   their `secondary_spheres` and `networks` into the keep record.
3. Apply the canonical multi-sphere assignments below.
4. Generate the coverage report against:
   - Peters 2013 Table 1-1 (50 EcoTrends sites — every one must appear).
   - Lugo 2006 Figure 1 (77 EFR + co-listed LTER + 12 EFR-MAB
     overlaps).
   - NEON 81-site list.
   - LTAR 18-site list.
   - All 11 IOOS RAs + 29 NERRs.

## Canonical multi-sphere overrides

| Site | primary_sphere | secondary_spheres |
|---|---|---|
| Hubbard Brook Experimental Forest | terrestrial | atmosphere, freshwater |
| H.J. Andrews Experimental Forest | terrestrial | atmosphere, freshwater |
| Coweeta Hydrologic Laboratory | terrestrial | freshwater |
| Niwot Ridge | terrestrial | cryosphere, atmosphere |
| Bonanza Creek | terrestrial | atmosphere, cryosphere |
| Toolik Field Station | terrestrial | cryosphere, freshwater |
| McMurdo Dry Valleys | cryosphere | terrestrial, freshwater |
| Palmer Station | ocean-estuarine | cryosphere, atmosphere |
| Jornada (LTER + LTAR + NEON) | terrestrial | atmosphere, agriculture |
| Konza Prairie (LTER + NEON) | terrestrial | atmosphere |
| Kellogg Biological Station (LTER + LTAR) | terrestrial | agriculture |
| Sevilleta | terrestrial | atmosphere |
| Reynolds Creek (LTAR + EcoTrends RCE) | agriculture | terrestrial, freshwater |
| Walnut Gulch (LTAR + ARS) | agriculture | terrestrial, freshwater |
| Loch Vale (USGS WEBB + USGS) | freshwater | cryosphere, terrestrial |
| Sleepers River (USGS WEBB) | freshwater | cryosphere, terrestrial |
| Bondville IL (SURFRAD + AmeriFlux + NADP) | atmosphere | agriculture |
| Park Falls / WLEF (AmeriFlux + TCCON) | atmosphere | terrestrial |
| Mauna Loa Observatory | atmosphere | terrestrial |
| Barrow / Utqiaġvik | atmosphere | cryosphere |
| Bartlett Experimental Forest (USFS-EFR + NEON BART) | terrestrial | atmosphere |
| Central Plains Experimental Range (LTAR + NEON CPER) | agriculture | terrestrial |
| Santa Rita Experimental Range (LTAR + NEON SRER) | agriculture | terrestrial |
| Wind River Experimental Forest (USFS-EFR + NEON WREF) | terrestrial | atmosphere |
| Bartlett (NEON BART + USFS-EFR) | terrestrial | atmosphere |

## Known landmarks for the coverage report

- **All 50 EcoTrends sites (Peters 2013 Table 1-1)** must be present in
  the union of R-* outputs.
- **All 77 EFRs (Lugo 2006 Figure 1)** must be present.
- **All 81 NEON sites** must be present (R-TER-NEON output).
- **All 18 LTAR sites** must be present (R-AGR output).
- **All 11 IOOS RAs + all 29 NERRs** must be in the post-cull ocean output.
