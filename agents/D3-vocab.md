# D3 — Controlled vocabularies agent

## Scope
Maintain the controlled vocabularies the rest of the pipeline uses for
facility types and research areas. These CSVs ship in the repo and are loaded
by both `scripts/ingest.py` (as CHECK-constraint sources) and `web/src/filters.js`
(as facet option sources).

## Outputs
- `schema/vocab/facility_types.csv`
- `schema/vocab/research_areas.csv`
- `schema/vocab/networks.csv` (curated canonical network names + aliases)

## `facility_types.csv`
Columns: `slug,label,description`

Required slugs (initial set):
- `federal`                   — US federal agency facility
- `state`                     — US state agency facility
- `local-gov`                 — US county / city / special district
- `university-marine-lab`     — Higher-ed operated marine lab or field station
- `university-institute`      — Campus-based research institute / center
- `nonprofit`                 — 501(c)(3) research / conservation org
- `foundation`                — Grantmaking foundation
- `network`                   — Multi-institution network / consortium / RA
- `international-federal`     — Non-US national agency (DFO, IMARPE, etc.)
- `international-university`  — Non-US university marine lab
- `international-nonprofit`   — Non-US NGO
- `industry`                  — Private / industry research facility
- `vessel`                    — Research vessel as a mobile facility
- `observatory`               — Cabled observatory / ocean observing platform
- `virtual`                   — Organization without a single physical HQ

## `research_areas.csv`
Columns: `slug,label,gcmd_uri,parent_slug`

Seeded from the NASA GCMD Science Keywords "Oceans" and "Cryosphere" branches,
plus a few coastal-specific additions:
- oceanography (parent)
  - physical-oceanography
  - chemical-oceanography
  - biological-oceanography
- coastal-processes (parent)
  - coastal-erosion
  - sediment-transport
  - shoreline-change
- estuaries-and-wetlands
- marine-ecosystems (parent)
  - coral-reefs
  - seagrass
  - kelp-forests
  - mangroves
- fisheries-and-aquaculture
- marine-geology
- marine-biogeochemistry
- ocean-acidification
- ocean-observing-systems
- marine-policy-and-socio-economics
- remote-sensing
- harmful-algal-blooms
- harmful-marine-debris-and-plastics
- tsunamis-and-coastal-hazards
- climate-and-sea-level

Keep the list lean (≤ 40 entries) for usable filter UI; nest finer concepts
under a parent.

## `networks.csv`
Columns: `slug,label,aliases,level`
Example: `ioos,IOOS,"Integrated Ocean Observing System|U.S. IOOS",us-national`

## Updates
Changes to the vocab require a bump to `schema/vocab/VERSION` and coordination
with R-agents so their emitted slugs still validate.
