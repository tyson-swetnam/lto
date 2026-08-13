# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo shape

`lto` (Long-Term Observatories of the United States) is a **two-stack** project, forked and adapted from [`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap):

1. **Python data pipeline** (`scripts/`, `schema/`, `data/`) — ingests JSON from a fleet of research subagents (`agents/*.md`) into DuckDB, then exports Parquet + GeoJSON + JSON view caches to `public/`.
2. **Static MapLibre + DuckDB-Wasm site** (`index.html`, `src/`, `public/`) — published to GitHub Pages with **no build step**. ES modules + CDN importmap; do not introduce npm/Vite.

The browser fetches `public/parquet/*.parquet` over HTTP range requests via DuckDB-Wasm, with `public/facilities.geojson` as a first-paint fallback and `public/cache/*.json` as a fast path for two views (see gotchas).

**The DuckDB file is still named `db/cod_kmap.duckdb`** — every script hardcodes that name. README.md's `db/lto.duckdb` is wrong; ignore it.

## Common commands

```bash
# Python pipeline (run from repo root, in a venv)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/rebuild_db_from_parquet.py  # FIRST after any pull — recreate db/cod_kmap.duckdb from committed db/parquet/
python scripts/ingest.py               # data/raw/R*/*.json → db/cod_kmap.duckdb
python scripts/ingest.py --skip-geocode  # use .geocode_cache.json only
python scripts/qa.py                   # data-quality gate (exits non-zero on failure)
python scripts/export_parquet.py       # db/cod_kmap.duckdb → db/parquet/*, public/parquet/*, public/facilities.geojson
python scripts/export_view_caches.py   # → public/cache/{browse_cards,people_cards}.json
python scripts/build_web_overlays.py   # network_synth_spatial_analysis/ → public/overlays/*.geojson + manifest.json

# Web UI
python -m http.server 5173             # then open http://localhost:5173/
```

The canonical post-edit sequence is: mutate the DB → `qa.py` → `export_parquet.py` → `export_view_caches.py`. Skipping the last step leaves the Browse and People tabs showing stale data.

There is no test framework. `qa.py` is the only correctness gate; add new invariants there rather than introducing pytest. It asserts: no null `facility_type`/`country`, every `facility_type` resolves against the vocab table, every facility has a `provenance` row, and every geocoded facility falls inside its country's bbox (`BBOX_BY_COUNTRY`).

`RUNBOOK.md` is the operator guide for the external-API enrichment passes (ORCID → OpenAlex → NSF/USAspending/990 → recompute derived tables). Follow it rather than re-deriving the order; those scripts need real network access and `OPENALEX_MAILTO` set.

## Critical gotchas

- **DuckDB on-disk format is not portable across versions** (e.g. 1.5.x writes a file 1.3.x cannot read). The `.duckdb` file is gitignored; the canonical committed artifact is `db/parquet/*.parquet`. After pulling, run `scripts/rebuild_db_from_parquet.py` before doing anything that opens the DB. See that script for the full rationale.

- **Two views bypass DuckDB entirely.** `src/views/list.js` and `src/views/people.js` fetch `public/cache/browse_cards.json` / `people_cards.json` first and only fall through to DuckDB-Wasm if the fetch 404s. That JSON is materialised offline by `scripts/export_view_caches.py` from the same SQL. Consequence: **changing the SQL in those view files, or the underlying data, has no visible effect until you re-run `export_view_caches.py` and commit the JSON.** Keep the cache SQL and the in-file fallback SQL in sync — they must produce identical row shapes.

- **Views don't survive parquet export.** `schema/schema.sql` defines helper views (`v_facility_map`, `v_facility_enriched`, `v_region_enriched`, `v_facility_funding_by_year`, `v_funder_funding_by_year`, `v_funding_ledger`, `v_facility_key_personnel`, `v_person_enriched`, `v_person_areas_enriched`, …) — the subset the frontend needs is re-created in the browser by `src/db.js` after registering parquet tables. Add new views in **both** places or the SQL tab will lose them.

- **Arrow LIST/STRUCT columns are not plain JS arrays.** DuckDB-Wasm 1.29 returns Arrow Vectors that have `.length` but fail `Array.isArray()`. Always run row results through `arrowToPlain()` / `unwrapRow()` from `src/db.js` before downstream view code touches them — see the comment block in that file for the trap this fixed.

- **Map sources need `Feature` shapes, not raw rows.** `query()` in `src/db.js` wraps each row in `{ type: 'Feature', geometry: { type: 'Point', coordinates: [...] }, properties: ... }` and drops rows with null coordinates. MapLibre silently skips rows that lack `geometry`.

- **Vocabularies are duplicated** between `schema/vocab/` (canonical, used by ingest/QA) and `public/vocab/` (served to the browser for filter labels). Keep them in sync — commit `c08fd86` fixed exactly this drift; `cp schema/vocab/*.csv public/vocab/` is the fix.

- **`export_parquet.py` fails soft on missing tables.** A `CatalogException` is swallowed and the table is skipped, leaving whatever stale parquet is already in `public/parquet/`. A "successful" export can therefore ship old data for a table a `compute_*` script hasn't produced yet — check the `[ok] exported …` line against the skip list.

- **`COMMIT_*.sh` are one-shot driver scripts**, gitignored, not source. Don't read them as documentation of current state — they are historical commit drivers.

## Domain model

Facilities are classified along the LTO **six-sphere** model (`spheres`, `facility_spheres` with a `primary` role): atmosphere, cryosphere, terrestrial/ecological, agriculture, aquatic-ocean/estuarine, aquatic-freshwater. Orthogonal facets are `ecosystem_types` and `life_zones` (via `facility_ecosystems` / `facility_life_zones`). The default inclusion gate is the Peters et al. 2013 long-term threshold (≥10 years of record) — `facilities.record_length_years` and `long_term_threshold_met`, surfaced as the "≥10y" filter. `docs/data-model.md` and `docs/spheres.md` are the human-facing writeups.

Beyond facilities the schema covers: regions (overlay polygons + `facility_regions` containment edges), people (`facility_personnel`, `publications`, `publication_topics`, `authorship`, `person_areas`, `collaborations`), data archives (Wave J: `data_archives`, `data_products`, `api_endpoints`, `cloud_buckets`), and precomputed MVG groupings (`facility_primary_groups`, `person_primary_groups`, `person_area_metrics`, `area_coverage_matrix`). The authoritative table lists are `TABLES` in `scripts/export_parquet.py` (export side) and the `tables` array in `src/db.js` (frontend side) — they must agree.

## Script families

`scripts/` has ~55 files; they fall into groups, and the group tells you when to run one:

- **Core pipeline** — `ingest.py`, `qa.py`, `export_parquet.py`, `export_view_caches.py`, `rebuild_db_from_parquet.py`, `geocode.py`.
- **`load_*.py`** — idempotent loaders for hand/agent-authored JSON+CSV under `data/raw/<AGENT>/` and `data/seed/`. Each upserts on a deterministic ID hash, so re-runs update rather than duplicate.
- **`enrich_people_*.py`** — external identity/bibliometric APIs (ORCID, OpenAlex, Google Scholar). Strict matching by design: a wrong ORCID is worse than a missing one, so unmatched rows stay NULL.
- **`fetch_funding_*.py`** — NSF Award Search, USAspending, IRS 990. Write into `funding_events` keyed `sha1(funder||facility||award_id||fiscal_year)`.
- **`compute_*.py`** — derived tables (collaborations, person/area metrics, MVG primary groups). Re-run after anything that grows the publication or funding graph; they write parquet directly as well as into the DB.
- **URL hygiene** — `check_url_health.py` (HTTP HEAD sweep), `url_hygiene.py` (pattern rewrites), `apply_*_url_*.py`. Decision logs land in `data/seed/*.csv`; those CSVs are the reviewable artifact.

`data/seed/` is the manually-curated layer (personnel seeds, ORCID resolution log, URL health/hygiene logs) and is committed — treat it as input, not output.

## Pipeline / wave model

Subagents are organized in waves; each `agents/<ID>-*.md` declares scope, sources, inputs, outputs, method, and known-landmark QA checks. Beyond the original `R1..R10`, later waves add sphere-specific agents (`R-ATM`, `R-CRY`, `R-TER-*`, `R-AGR`, `R-AQ-*`), `R-PEOPLE`, `H-FUND-PUB`, `J-DATA`, and `L-URL-FIX`.

```
Wave 1  D1 schema  + D3 vocabulary           → schema/, schema/vocab/
Wave 2  R1..R8 regional research agents      → data/raw/R*/facilities_*.json
Wave 3  R9 funding-flows, R10 COMPASS sites  → data/raw/R9/, data/raw/R10/
Wave 4  D2 ingest pipeline                   → db/cod_kmap.duckdb, db/parquet/
Wave 5  F1..F4 frontend + deploy             → src/, public/, .github/workflows/deploy.yml
Wave 6  verification + iteration
```

`ingest.py` globs `data/raw/R*` only — agent directories must start with `R` to be picked up. Every research record must conform to the shared facility JSON schema documented in `agents/README.md` (record_id, canonical_name, facility_type from `schema/vocab/facility_types.csv`, ISO-2 country, hq + locations, research_areas slugs, networks, funders with `relation`, **provenance with source_url + confidence**). D2 dedupes by facility_id, URL, and fuzzy-name + 5 km haversine.

When network access is unavailable, the working pattern is the parallel-subagent fan-out described in `agents/H-FUND-PUB.md` and `agents/R-PEOPLE.md`: agents write single JSON files into `data/raw/<AGENT>/`, then a `load_lto_*.py` script upserts them.

## Frontend layout

- `index.html` — importmap pulls `maplibre-gl` + `@duckdb/duckdb-wasm` from esm.sh; loads `src/main.js` as a module.
- `src/main.js` — bootstraps map, filters, overlays, hash-router, then the 7 routes (`/`, `/browse`, `/network`, `/people`, `/sql`, `/stats`, `/docs`). Sub-routes like `/people/<id>` and `/docs/<slug>` dispatch on the first path segment.
- `src/db.js` — DuckDB-Wasm init, parquet view registration, helper views, `query()` (returns GeoJSON Features), and the Arrow→JS unwrap helpers. Each `CREATE OR REPLACE VIEW` is individually try/caught so one missing parquet doesn't break the rest.
- `src/config.js` — `DATA_BASE` resolves all data fetches relative to `index.html`; never hardcode `/public/` paths in views.
- `src/map.js` — `TYPE_COLORS` is the single source of truth for facility-type colours (must match polygon overlay colours in `public/overlays/manifest.json`). The legend also supports colour-by-sphere.
- `src/overlays.js` — lazy-loads polygon layers via `public/overlays/manifest.json`. `DEFAULT_OFF` controls first-paint visibility (heavy / cluttering layers default off).
- `src/views/{list,stats,docs,network,people,sql}.js` — one per top-tab (`list.js` backs `/browse`). `/docs` reads markdown from `docs/` at runtime.

The site degrades in three tiers: GeoJSON fallback → JSON view caches → full DuckDB-Wasm. Changes must not assume DuckDB is ready; `renderList` can be called before `initDB()` resolves.

## CI workflows

- `deploy.yml` (push to `main`) — stages only `index.html`, `favicon.svg`, `src/`, `public/`, `docs/`. Anything outside those paths (agents, scripts, schema, data/raw) is **not** on the live site. Adding a new runtime-fetched directory means editing this staging step.
- `refresh-data.yml` (weekly, Sun 06:00 UTC) — ingest → qa → export_parquet → export_view_caches, opens a PR with the parquet/GeoJSON/cache diffs.
- `url-health.yml` (weekly, Mon 07:00 UTC) — rebuild from parquet → HEAD sweep → hygiene → re-export, opens a PR.

Both scheduled workflows open PRs rather than pushing; review the data diffs before merging.

## External datasets

- `data/raw/synthesis-networks/` is a verbatim MIT-licensed snapshot of [COMPASS-DOE/synthesis-networks](https://github.com/COMPASS-DOE/synthesis-networks). Do **not** edit these files; treat them as upstream. R10 (`scripts/build_r10_from_spatial.py`) derives `data/raw/R10/facilities_synthesis_networks.json` from `network_synth_spatial_analysis/` GeoJSON layers.
- `network_synth_spatial_analysis/coastal_protected/` is gitignored except for the bundled outputs that `build_web_overlays.py` produces.
