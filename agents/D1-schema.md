# D1 — DuckDB schema agent

## Scope
Produce and maintain the canonical DuckDB schema that all other agents honor.
Schema supports efficient geospatial queries from Leaflet + DuckDB-Wasm plus
faceted filtering across facility type, funders, networks, and research areas.

## Outputs
- `schema/schema.sql` — full DDL, idempotent (`CREATE OR REPLACE`)
- `schema/README.md` — ER diagram (optional)

## Tables

- `facilities`              (primary entity)
- `locations`               (1..N locations per facility)
- `funders`                 (funder directory)
- `funding_links`           (facility × funder, many-to-many with amount/year)
- `research_areas`          (GCMD-aligned taxonomy — hierarchical)
- `area_links`              (facility × research_area, many-to-many)
- `networks`                (consortia / networks / observatory systems)
- `network_membership`      (facility × network, many-to-many)
- `provenance`              (one row per record, referencing table+id)
- `ingest_runs`             (metadata per ingest execution)

## Notes
- Primary key strategy: `facility_id` generated as `hash(lower(canonical_name)
  || coalesce(acronym,''))` at ingest time (stable re-runs).
- Lat/lng stored as DOUBLE columns; a generated `geom` column produced via
  `ST_Point(lng, lat)` using the DuckDB `spatial` extension (loaded in the
  ingest script so downstream queries can do bbox filters).
- Enum values enforced via CHECK constraints backed by rows in
  `schema/vocab/facility_types.csv`.

## Consumers
- `scripts/ingest.py` (D2) — creates tables and loads data
- `web/src/db.js` (F3) — runs SELECTs against the shipped `.duckdb`

## Validation
`duckdb db/cod_kmap.duckdb ".read schema/schema.sql"` must succeed against a
fresh file with no errors or warnings.
