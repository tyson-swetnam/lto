# Data model

The DuckDB schema is defined in `schema/schema.sql`. The browser registers
each table as a Parquet-backed view on first load (see `src/db.js`), then
re-creates the helper views (`v_facility_funding_by_year`,
`v_funder_funding_by_year`, `v_facility_key_personnel`, `v_funding_ledger`,
`v_person_enriched`) — those don't survive Parquet export and **must be
defined in both** `schema/schema.sql` and `src/db.js` to stay in sync.

## Core facility tables

These are inherited from the cod-kmap engine and used unchanged.

| Table | Purpose |
|---|---|
| `facilities` | One row per observatory. `facility_id` (hash), `canonical_name`, `acronym`, `parent_org`, `facility_type`, `country`, `region`, `established`, `record_length_years`, `long_term_threshold_met`, `url`, `data_portal_url`, provenance fields. |
| `locations` | One row per HQ + satellite location. `facility_id`, `label`, `address`, `lat`, `lng`, `role` (headquarters / field-station / observatory / vessel / mooring-array / buoy / lab / weather-station / streamgage / flux-tower / glacier-site / snow-station). |
| `funders` | Funder catalogue (NSF, USDA, NOAA, DOE, USGS, NASA, EPA …). |
| `funding_events` | `(facility_id, funder_id, relation, year_start, year_end, amount_usd)`. Filled by `R-FUND`. |
| `networks` | Controlled vocabulary from `schema/vocab/networks.csv`. |
| `network_membership` | `(facility_id, network_slug)` join table. |
| `research_areas` | Slugs from `schema/vocab/research_areas.csv` (GCMD-aligned). |
| `area_links` | `(facility_id, area_slug)` join table. |

## LTO extension tables

Added in Wave A to support the six-sphere model.

| Table | Purpose |
|---|---|
| `spheres` | Catalogue of the six spheres + display labels. |
| `ecosystem_types` | EcoTrends + WWF biome slugs (`schema/vocab/ecosystem_types.csv`). |
| `life_zones` | Holdridge life-zone slugs per Lugo et al. 2006 (`schema/vocab/life_zones.csv`). |
| `facility_spheres` | `(facility_id, sphere, role)` where `role` ∈ {primary, secondary}. |
| `facility_ecosystems` | `(facility_id, ecosystem_slug)`. |
| `facility_life_zones` | `(facility_id, life_zone_slug)`. |

## People-side tables

Added in Wave F (R-PEOPLE-*).

| Table | Purpose |
|---|---|
| `people` | One row per person: `person_id` (name+homepage hash), `name`, `name_family`, `name_given`, `email`, `orcid`, `openalex_id`, `google_scholar_id`, `homepage_url`, `research_interests`, `status`. |
| `facility_personnel` | `(facility_id, person_id, role, title, is_key_personnel, start_date, end_date)`. Roles: `lead-PI`, `co-PI`, `founding-PI`, `information-manager`, `director`, `deputy-director`, `site-manager`, `domain-manager`, `manager`, `superintendent`, `coordinator`, `faculty`, `emeritus`, `technical-staff`, `executive-officer`. |
| `publications` | DOI-keyed publication catalogue. |
| `authorship` | `(person_id, doi, position)`. |
| `person_areas` | `(person_id, area_slug)`. |
| `collaborations` | Person-pair edges derived from co-authorship. |

## Region-side tables

Polygon overlays and containment edges.

| Table | Purpose |
|---|---|
| `regions` | Polygon catalogue (LME, FMP regions, NPS units, USFS regions, Climate Hubs). |
| `region_area_links` | `(region_id, area_slug)`. |
| `facility_regions` | `(facility_id, region_id)` containment edges, computed by point-in-polygon at ingest time. |

## Helper views

Defined in **both** `schema/schema.sql` and `src/db.js`. Re-create them
in both places when adding a new view.

- `v_facility_funding_by_year` — facility-level annual funding totals.
- `v_funder_funding_by_year` — funder-level annual totals.
- `v_facility_key_personnel` — flatten `facility_personnel` to one row
  per (facility, key person).
- `v_funding_ledger` — long-form ledger for the Funding tab.
- `v_person_enriched` — `people` + best-available identifier flag for
  the People tab.

The full table list driving the front-end is the `tables` array near
`src/db.js:142`.
