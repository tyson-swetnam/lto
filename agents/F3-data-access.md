# F3 — Data access agent (DuckDB-Wasm + GeoJSON fallback)

## Scope
Bridge the browser UI to the data. Primary mode: DuckDB-Wasm running SQL
against Parquet shards served from GitHub Pages via HTTP range requests.
Fallback for first-paint: a small static `facilities.geojson`.

## Outputs
- `web/src/db.js`
- `web/public/facilities.geojson` (produced by `scripts/export_parquet.py`)
- `web/public/parquet/*.parquet` (facilities, locations, funders, funding_links,
  research_areas, area_links, networks, network_membership, provenance)

## Behavior
1. On page load:
   - Fetch `facilities.geojson` (~200 KB gzipped — subset of fields) and hand to
     F1 immediately for first paint.
   - In parallel, import `@duckdb/duckdb-wasm`, spin up a worker, and attach the
     Parquet files as views using `httpfs`-style registered buffers.
2. When F2 emits a new `filterState`:
   - If DuckDB-Wasm is ready → run the full SQL query (see below).
   - Otherwise → filter the in-memory GeoJSON client-side (approximation).
3. Return features to F1 / F2 as a plain JS array.

## Reference query (built by `buildQuery(filterState)`)
```sql
SELECT f.facility_id AS id,
       f.canonical_name AS name,
       f.acronym,
       f.facility_type AS type,
       f.country,
       l.lat, l.lng,
       f.url,
       list(DISTINCT fu.name)     AS funders,
       list(DISTINCT ra.label)    AS areas,
       list(DISTINCT n.label)     AS networks
FROM facilities f
JOIN locations l        ON l.facility_id = f.facility_id AND l.role = 'headquarters'
LEFT JOIN funding_links fl ON fl.facility_id = f.facility_id
LEFT JOIN funders fu       ON fu.funder_id  = fl.funder_id
LEFT JOIN area_links al    ON al.facility_id = f.facility_id
LEFT JOIN research_areas ra ON ra.area_id = al.area_id
LEFT JOIN network_membership nm ON nm.facility_id = f.facility_id
LEFT JOIN networks n       ON n.network_id = nm.network_id
WHERE <filter fragment from F2>
GROUP BY f.facility_id, f.canonical_name, f.acronym, f.facility_type,
         f.country, l.lat, l.lng, f.url;
```

## Deliverable
```
export async function initDB() { ... }          // loads Wasm + Parquet
export async function loadFallback() { ... }    // returns GeoJSON features
export async function query(filterState) { ... }// returns features array
```

## Non-goals
- Writing back to the database from the browser.
- Auth — public read-only map.
