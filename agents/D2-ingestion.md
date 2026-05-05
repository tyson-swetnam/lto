# D2 — Ingestion / normalization / geocoding agent

## Scope
Transform `data/raw/R*/` JSON+CSV into a clean, deduplicated DuckDB database
`db/cod_kmap.duckdb` plus Parquet exports suitable for DuckDB-Wasm HTTP-range
consumption.

## Outputs
- `scripts/ingest.py` — main entrypoint
- `scripts/geocode.py` — Nominatim-backed geocoder with JSON cache
- `scripts/qa.py` — data-quality assertions run at the end of ingest
- `scripts/export_parquet.py` — exports each table to
  `db/parquet/<table>.parquet` for Wasm HTTP-range reads
- `db/cod_kmap.duckdb`
- `db/parquet/*.parquet`

## Pipeline
1. **Load**: enumerate every `data/raw/R*/facilities_*.json`. Validate each
   record against the shared schema (see `agents/README.md`).
2. **Assign stable IDs**: `facility_id = hash(lower(canonical_name) ||
   coalesce(acronym,''))`.
3. **Dedup across agents**: for records with the same `facility_id` OR the
   same `url` OR `rapidfuzz.fuzz.token_set_ratio(name) >= 92` AND haversine
   distance of HQ coordinates < 5km, merge by picking the record with the
   highest `provenance.confidence`, keep its fields, union the locations,
   research areas, networks, funders.
4. **Geocode**: for any record with null `hq.lat` / `hq.lng` but an address,
   call Nominatim (respect rate limit — 1 req/s), cache results in
   `.geocode_cache.json`.
5. **Load to DuckDB**: insert into tables per `schema/schema.sql`. Load the
   `spatial` extension and materialize `geom`.
6. **Resolve network memberships**: read every agent's edge CSV (e.g.,
   R3 `network_membership.csv`) and resolve `member_record_id_hint` to real
   facility IDs using the dedup map.
7. **Provenance**: write one `provenance` row per ingested record citing
   source URL, agent, retrieval date, confidence.
8. **QA**: run `qa.py`; fail on any assertion.
9. **Export**: write Parquet.

## Dependencies (pinned in `requirements.txt`)
- duckdb
- polars
- rapidfuzz
- geopy
- pyyaml

## Usage
```
python scripts/ingest.py                # full rebuild
python scripts/ingest.py --skip-geocode # use cache only
python scripts/qa.py                    # standalone QA against existing DB
python scripts/export_parquet.py        # refresh Parquet exports
```

## QA assertions (examples)
- No `facilities` row with null `facility_type` or `country`.
- Every non-virtual facility has a location with non-null lat AND lng.
- All enum values for `facility_type` appear in `schema/vocab/facility_types.csv`.
- Every facility has ≥1 provenance row.
- Landmark coverage ≥95% (see per-agent "Known landmarks" sections).
- No lat/lng outside a continental bounding box per country (sanity).
