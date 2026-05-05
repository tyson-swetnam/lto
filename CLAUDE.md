# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo shape

cod-kmap is a **two-stack** project:

1. **Python data pipeline** (`scripts/`, `schema/`, `data/`) — ingests JSON from a fleet of research subagents (`agents/R*-*.md`) into DuckDB, then exports Parquet + GeoJSON to `public/`.
2. **Static MapLibre + DuckDB-Wasm site** (`index.html`, `src/`, `public/`) — published to GitHub Pages with **no build step**. ES modules + CDN importmap; do not introduce npm/Vite.

The browser fetches `public/parquet/*.parquet` over HTTP range requests via DuckDB-Wasm, with `public/facilities.geojson` as a first-paint fallback.

## Common commands

```bash
# Python pipeline (run from repo root, in a venv)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/ingest.py               # data/raw/R*/*.json → db/cod_kmap.duckdb
python scripts/ingest.py --skip-geocode  # use .geocode_cache.json only
python scripts/qa.py                   # data-quality gate (exits non-zero on failure)
python scripts/export_parquet.py       # db/cod_kmap.duckdb → db/parquet/*, public/parquet/*, public/facilities.geojson
python scripts/build_web_overlays.py   # network_synth_spatial_analysis/ → public/overlays/*.geojson + manifest.json
python scripts/rebuild_db_from_parquet.py  # recreate db/cod_kmap.duckdb from committed db/parquet/ (use after pulling)

# Web UI
python -m http.server 5173             # then open http://localhost:5173/
```

There is no test framework. `qa.py` is the only correctness gate; add new invariants there rather than introducing pytest.

## Critical gotchas

- **DuckDB on-disk format is not portable across versions** (e.g. 1.5.x writes a file 1.3.x cannot read). The `.duckdb` file is gitignored; the canonical committed artifact is `db/parquet/*.parquet`. After pulling, run `scripts/rebuild_db_from_parquet.py` before doing anything that opens the DB. See `scripts/rebuild_db_from_parquet.py` for the full rationale.

- **Views don't survive parquet export.** `schema/schema.sql` defines helper views (`v_facility_funding_by_year`, `v_funder_funding_by_year`, `v_facility_key_personnel`, `v_funding_ledger`, `v_person_enriched`) — these are re-created in the browser by `src/db.js` after registering parquet tables. Add new views in **both** places or the SQL tab will lose them.

- **Arrow LIST/STRUCT columns are not plain JS arrays.** DuckDB-Wasm 1.29 returns Arrow Vectors that have `.length` but fail `Array.isArray()`. Always run row results through `arrowToPlain()` / `unwrapRow()` from `src/db.js` before downstream view code touches them — see the comment block in that file for the trap this fixed.

- **Map sources need `Feature` shapes, not raw rows.** `query()` in `src/db.js` wraps each row in `{ type: 'Feature', geometry: { type: 'Point', coordinates: [...] }, properties: ... }` and drops rows with null coordinates. MapLibre silently skips rows that lack `geometry`.

- **Vocabularies are duplicated** between `schema/vocab/` (canonical, used by ingest/QA) and `public/vocab/` (served to the browser for filter labels). Keep them in sync — there is a recent commit `c08fd86` that fixed exactly this drift.

- **`COMMIT_*.sh` are one-shot driver scripts**, gitignored, not source. Don't read them as documentation of current state — they are historical commit drivers.

## Pipeline / wave model

Subagents are organized in waves; each `agents/<ID>-*.md` declares scope, sources, inputs, outputs, method, and known-landmark QA checks.

```
Wave 1  D1 schema  + D3 vocabulary           → schema/, schema/vocab/
Wave 2  R1..R8 regional research agents      → data/raw/R*/facilities_*.json
Wave 3  R9 funding-flows, R10 COMPASS sites  → data/raw/R9/, data/raw/R10/
Wave 4  D2 ingest pipeline                   → db/cod_kmap.duckdb, db/parquet/
Wave 5  F1..F4 frontend + deploy             → src/, public/, .github/workflows/deploy.yml
Wave 6  verification + iteration
```

Every research record must conform to the shared facility JSON schema documented in `agents/README.md` (record_id, canonical_name, facility_type from `schema/vocab/facility_types.csv`, ISO-2 country, hq + locations, research_areas slugs, networks, funders with `relation`, **provenance with source_url + confidence**). D2 dedupes by facility_id, URL, and fuzzy-name + 5 km haversine.

Beyond facilities, the schema and pipeline now cover: regions (overlay polygons + `facility_regions` containment edges), people (`facility_personnel`, `publications`, `authorship`, `person_areas`, `collaborations`), and precomputed MVG groupings (`facility_primary_groups`, `person_primary_groups`, area metrics). The full table list driving the frontend is the `tables` array in `src/db.js:142`.

## Frontend layout

- `index.html` — importmap pulls `maplibre-gl` + `@duckdb/duckdb-wasm` from esm.sh; loads `src/main.js` as a module.
- `src/main.js` — bootstraps map, filters, overlays, hash-router, then 7 views.
- `src/db.js` — DuckDB-Wasm init, parquet view registration, helper views, `query()` (returns GeoJSON Features), and the Arrow→JS unwrap helpers.
- `src/map.js` — `TYPE_COLORS` is the single source of truth for facility-type colours (must match polygon overlay colours in `public/overlays/manifest.json`).
- `src/overlays.js` — lazy-loads polygon layers via `public/overlays/manifest.json`. `DEFAULT_OFF` controls first-paint visibility (heavy / cluttering layers default off).
- `src/views/{list,stats,docs,network,people,sql}.js` — one per top-tab. `/docs` reads markdown from `docs/` at runtime.

The deploy workflow (`.github/workflows/deploy.yml`) only stages `index.html`, `favicon.svg`, `src/`, `public/`, and `docs/`. Anything outside those paths (agents, scripts, schema, data/raw) is **not** on the live site.

## External datasets

- `data/raw/synthesis-networks/` is a verbatim MIT-licensed snapshot of [COMPASS-DOE/synthesis-networks](https://github.com/COMPASS-DOE/synthesis-networks). Do **not** edit these files; treat them as upstream. R10 (`scripts/build_r10_from_spatial.py`) derives `data/raw/R10/facilities_synthesis_networks.json` from `network_synth_spatial_analysis/` GeoJSON layers.
- `network_synth_spatial_analysis/coastal_protected/` is gitignored except for the bundled outputs that `build_web_overlays.py` produces.
