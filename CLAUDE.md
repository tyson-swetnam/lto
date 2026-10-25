# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo shape

`lto` (Long-Term Observatories of the United States) is a **two-stack** project, forked and adapted from [`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap):

1. **Python data pipeline** (`scripts/`, `schema/`, `data/`) — ingests JSON from a fleet of research subagents (`agents/*.md`) into a **DuckLake** store of record (DuckDB 2.0, SQLite catalog), then exports Parquet + GeoJSON + JSON view caches to `public/`.
2. **Static MapLibre + DuckDB-Wasm site** (`index.html`, `src/`, `public/`) — published to GitHub Pages with **no build step**. ES modules + CDN importmap; do not introduce npm/Vite.

The browser fetches `public/parquet/*.parquet` over HTTP range requests via DuckDB-Wasm, with `public/facilities.geojson` as a first-paint fallback and `public/cache/*.json` as a fast path for three views (see gotchas). The browser never touches the lake.

**There is no `db/lto.duckdb` any more.** The store is `db/lto_catalog.sqlite` (catalog) + `db/lake/` (data files), both gitignored, opened only through `scripts/lto_db.py`. See [DuckLake store](#ducklake-store).

## Common commands

```bash
# Python pipeline (run from repo root, in a venv; Python >= 3.11 for duckdb 2.0)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # pins duckdb==2.0.0

python scripts/rebuild_lake_from_parquet.py  # FIRST after a clone or pull — rebuild the lake from public/parquet/
python scripts/ingest.py               # data/raw/R*/*.json → upsert into the lake
python scripts/ingest.py --skip-geocode  # use .geocode_cache.json only
python scripts/qa.py                   # data-quality + integrity gate (exits non-zero on failure)
python scripts/export_parquet.py       # lake → public/parquet/*, public/facilities.geojson (--db-out db/parquet for a local copy)
python scripts/export_view_caches.py   # → public/cache/{browse_cards,people_cards,project_cards,site_groups}.json
python scripts/lake_maintenance.py     # compact files, expire snapshots > 90 days (optional, before export)
python scripts/build_web_overlays.py   # network_synth_spatial_analysis/ → public/overlays/*.geojson + manifest.json

# Web UI
python -m http.server 5173             # then open http://localhost:5173/
```

The canonical post-edit sequence is: mutate the lake → `qa.py` → `export_parquet.py` → `export_view_caches.py`. Skipping the last step leaves the Browse, People and Projects tabs showing stale data. `rebuild_db_from_parquet.py` is a deprecated shim that runs the lake rebuild.

There is no test framework. `qa.py` is the only correctness gate; add new invariants there rather than introducing pytest. Its JS parse check needs `node` on PATH and is skipped without it (`pip install nodejs-wheel-binaries` provides one). Its first database check re-enforces every PRIMARY KEY / UNIQUE / FOREIGN KEY / CHECK / NOT NULL in `schema/schema.sql` against the lake (see gotchas). It also asserts: no null `facility_type`/`country`, every `facility_type` resolves against the vocab table, every facility has a `provenance` row, and every geocoded facility falls inside its country's bbox (`BBOX_BY_COUNTRY`).

`RUNBOOK.md` is the operator guide for the external-API enrichment passes (ORCID → OpenAlex → NSF/USAspending/990 → recompute derived tables). Follow it rather than re-deriving the order; those scripts need real network access and `OPENALEX_API_KEY` set.

## DuckLake store

- **Layout.** `db/lto_catalog.sqlite` is the DuckLake 1.1 catalog (tables, snapshots, commit messages, small inlined writes); `db/lake/` holds its parquet data files. SQLite was chosen over a DuckDB-file catalog because it has no DuckDB storage-version trap and readers never block. **Writers are serialised:** `lto_db.transaction()` holds an exclusive `flock` on `<catalog>.lock` from `BEGIN` to `COMMIT`, so a second writer waits (it prints `[lock] … waiting`). Without it two overlapping transactions could each pass `assert_integrity` and commit a duplicate key or an orphan. A write outside `transaction()` is not serialised. Snapshot ids are local and mean nothing across clones.
- **One way in.** Every script calls `lto_db.connect()` (`read_only=True` for readers, `snapshot=n` for time travel). It attaches the lake as `lake` and runs `USE lake`, so unqualified names work. It raises `LakeNotFound` rather than silently creating an empty lake; only the rebuild passes `create=True`.
- **Pointing at another lake** (tests, CI, scratch): `LTO_LAKE_CATALOG=/path/cat.sqlite` and optionally `LTO_LAKE_DATA=/path/data/` (defaults to `<catalog dir>/lake`), or `--catalog` / `--lake-data` on any script. An explicit `--catalog` ignores `$LTO_LAKE_DATA`, and the rebuild refuses to pair a non-default catalog with `db/lake/`. With a non-default catalog, `export_parquet.py` and `export_view_caches.py` write to `<catalog dir>/export/` instead of `public/`; pass `--out`/`--geojson` to publish from one deliberately. Never experiment on `db/` when a scratch lake will do.
- **One run, one snapshot.** Loaders and `compute_*` wrap their writes in `with lto_db.transaction(con, "script_name: what changed"):`, which commits once with an author and message (nothing is committed if nothing changed). Autocommit statements each make their own snapshot and data file; don't write outside a transaction.
- **History.** From `python` with `import lto_db; con = lto_db.connect(read_only=True)`:
  ```sql
  SELECT snapshot_id, snapshot_time, author, commit_message FROM lake.snapshots() ORDER BY 1 DESC;
  SELECT * FROM facilities AT (VERSION => 12) WHERE facility_id = '…';            -- table as of snapshot 12
  SELECT change_type, person_id, role FROM ducklake_table_changes('lake', 'main', 'facility_personnel', 12, 15);
  ```
  `lto_db.connect(snapshot=12)` attaches the whole lake read-only at that snapshot. To restore a table, `DELETE` + `INSERT … SELECT … AT (VERSION => n)` in one transaction; `CREATE OR REPLACE TABLE … AS SELECT … AT (…)` drops NOT NULL/DEFAULT.
- **Maintenance.** `scripts/lake_maintenance.py` flushes inlined rows, merges small files, folds delete files, expires snapshots older than `--older-than-days` (default 90; `--no-expire`, `--dry-run`) and deletes unreferenced files. It fails if any table's row count or content hash changes. Expired snapshots can no longer be time-travelled to. Don't run it while another process writes.
- **The lake is disposable; `public/parquet/` is not.** Unexported lake changes are lost on a rebuild. `lto_db.ensure_schema(con)` adds new `schema.sql` tables/columns/views in place so a schema edit doesn't force a rebuild.

## Critical gotchas

- **The canonical committed artifact is `public/parquet/*.parquet`.** The lake (`db/lto_catalog.sqlite`, `db/lake/`) and `db/parquet/` are gitignored. After pulling, run `scripts/rebuild_lake_from_parquet.py` before anything that opens the lake. It always builds from `public/parquet/` (a stale `db/parquet/` used to win and revert pulled data); `--parquet db/parquet` loads a local export on purpose. A spec-1.1 catalog needs DuckDB 2.0; DuckDB 1.x clients cannot open it. Exported parquet still reads in DuckDB 1.1+.

- **Constraints are logical, enforced by QA, not at write time.** DuckLake rejects PRIMARY KEY, UNIQUE, FOREIGN KEY, CHECK, indexes and sequences. `schema/schema.sql` keeps them all, but is executed only in an in-memory "spec" database; the lake is created column-only (types, NOT NULL, DEFAULT — those *are* enforced). `qa.py` (via `lto_db.integrity_violations`) fails on any duplicate key, orphan reference, failed CHECK or column drift from `schema.sql`, and loaders call `lto_db.assert_integrity(con, tables)` before COMMIT so a bad batch rolls back. The same check covers the derived tables' keys (`lto_db.DERIVED_CONSTRAINTS`; their producers assert them) and the references `schema.sql` leaves undeclared — projects, `registry_facilities`, `person_registry.person_id` (`lto_db.SOFT_REFERENCES`). An unknown table name passed to `assert_integrity` raises. The old foreign-key update block is gone: `UPDATE facilities SET facility_type = …` works on referenced rows — and so does renaming a key, which orphans children silently until QA catches it.

- **Upserts are `MERGE`, never `INSERT OR REPLACE` / `INSERT OR IGNORE` / `ON CONFLICT`.** Those need a primary key and fail on the lake. Use `lto_db.merge_upsert(con, table, key_cols, source, …)` (`insert_only=True` for insert-if-absent, `coalesce=` to keep existing non-NULLs). A `MERGE` whose source repeats a key inserts both rows; `merge_upsert` de-duplicates with `DISTINCT ON`. Stage per-row loops in a TEMP table and merge once.

- **Create stages with `lto_db.create_temp_like(con, name, select_sql)`, never `CREATE TEMP TABLE t AS SELECT … LIMIT 0`.** DuckDB 2.0.0 has a silent data-loss bug: a DuckDB-native (TEMP or in-memory) table created by an empty CTAS inside a transaction, then bulk-filled by one `INSERT … SELECT` of ≥ 122,880 rows (one row group), reads back as 0 rows. That holds whether the source is a lake table, a TEMP table or a registered Arrow/pandas object, and a `merge_upsert` sourced from it writes nothing. `executemany` fills and DuckLake tables are unaffected, which is why no committed data was lost, but switching a stage to a bulk fill would trip it. `create_temp_like` declares the columns explicitly, which avoids it.

- **DuckDB 2.0 Python API.** `Relation.fetchone()` is removed (use `lto_db.scalar()` / `lto_db.rows()`); single-arrow lambdas fail (`lambda x: x + 1`, not `x -> x + 1`); `con.execute(q).pl()` / `.arrow()` are removed (use `con.sql(q).pl()` / `.to_arrow_table()`). `execute().fetchone()` then another `execute()` is fine, but a relation-API call (`.sql`, `.table`, `.register`) on a connection with a half-read `execute()` result raises `ResourceInUseException`. Reading a `TIMESTAMPTZ` into Python needs `pytz`.

- **Three views bypass DuckDB entirely.** `src/views/list.js`, `src/views/people.js` and `src/views/projects.js` fetch `public/cache/browse_cards.json` / `people_cards.json` / `project_cards.json` (plus `site_groups.json` for the Projects tab's network groups) first and only fall through to DuckDB-Wasm if the fetch 404s. That JSON is materialised offline by `scripts/export_view_caches.py` from the same SQL. Consequence: **changing the SQL in those view files, or the underlying data, has no visible effect until you re-run `export_view_caches.py` and commit the JSON.** Keep the cache SQL and the in-file fallback SQL in sync — they must produce identical row shapes, and the cache SQL orders every list (and uses `list_sum`) so output is byte-stable.

- **Views live in three places.** `schema/schema.sql` defines helper views (`v_facility_map`, `v_facility_enriched`, `v_region_enriched`, `v_facility_funding_by_year`, `v_funder_funding_by_year`, `v_funding_ledger`, `v_facility_key_personnel`, `v_person_enriched`, `v_person_areas_enriched`, …). The rebuild and `ensure_schema` create them in the lake; they don't survive parquet export, so the subset the frontend needs is re-created in the browser by `src/db.js` after registering parquet tables. Add new views in **both** `schema.sql` and `src/db.js` or the SQL tab will lose them.

- **Browser SQL is DuckDB 1.5 SQL.** `index.html` pins `@duckdb/duckdb-wasm@1.33.1-dev65.0` (core v1.5.6; no stable 2.0 wasm exists). Anything in `src/` or that `src/db.js` re-creates must run on 1.5, and `qa.py` fails if a `src/views` query returns DECIMAL/HUGEINT.

- **Arrow LIST/STRUCT columns are not plain JS arrays.** DuckDB-Wasm (1.29 through 1.33.x) returns Arrow Vectors that have `.length` but fail `Array.isArray()`. Always run row results through `arrowToPlain()` / `unwrapRow()` from `src/db.js` before downstream view code touches them — see the comment block in that file for the trap this fixed.

- **Map sources need `Feature` shapes, not raw rows.** `query()` in `src/db.js` wraps each row in `{ type: 'Feature', geometry: { type: 'Point', coordinates: [...] }, properties: ... }` and drops rows with null coordinates. MapLibre silently skips rows that lack `geometry`.

- **Vocabularies are duplicated** between `schema/vocab/` (canonical, used by ingest/QA) and `public/vocab/` (served to the browser for filter labels). Keep them in sync — commit `c08fd86` fixed exactly this drift; `cp schema/vocab/*.csv public/vocab/` is the fix.

- **`export_parquet.py` hard-fails on a missing table.** Every table in `TABLES` is checked before any file is written; a missing one aborts the export with nothing written (`ALLOW_MISSING` is the explicit exception list, empty today). Output is deterministic: rows are ordered by primary key then all columns, every column is written OPTIONAL, the GeoJSON is ordered by id, and files are written via temp + rename. Re-exporting unchanged data gives byte-identical files, so a diff in `public/` is a real change.

- **`export_parquet.py` is the only writer of `public/parquet/`.** `compute_*`, `build_mvg_layout.py` and `check_url_health.py` write their tables into the lake (`lto_db.replace_table`); export publishes them. Keep derived numeric columns in the types the parquet already holds (e.g. cast `total_citations` to DOUBLE, not HUGEINT) or a computed lake exports different bytes from a rebuilt one.

- **The OpenAlex topic crosswalk must be copied from data, never typed.** `data/vocab_crosswalk/openalex_to_area.csv` maps OpenAlex topic/concept ids to `research_areas`; `compute_area_metrics.py` uses it for every per-area number. Its first version had recalled ids ("Kelp" carried the id of "Global warming") and filed dryland ecologists under marine debris. Take id and name together from `publication_topics`; `qa.py` fails on an id whose label disagrees with the data or an unknown area. People-card totals (pubs, citations, h-index) come from `authorship`, not from this table.

- **`COMMIT_*.sh` are one-shot driver scripts**, gitignored, not source. Don't read them as documentation of current state — they are historical commit drivers.

- **The national raw inputs are not in the repo.** `data/raw/**/*.json` is gitignored, so the 445 original facilities cannot be re-ingested from source; `public/parquet/` is their only copy. `ingest.py` upserts into an existing lake (it raises `LakeNotFound` on a fresh clone) and leaves facilities absent from `data/raw` alone. For a facility it does load, the raw record's spheres, ecosystems, life zones and research areas replace the lake's (so re-run `add_arid_sphere.py` after it), and every vocab table is reloaded from `schema/vocab/*.csv` — `qa.py` warns when a vocab table and its CSV differ, i.e. before an ingest would ship the difference. Committed exceptions: `data/raw/R-ARID/`, `data/raw/J-ENVIRODATA/`, `data/raw/J-AZWATER/`, `data/raw/R-PEOPLE2/`, `data/raw/R-PEOPLE2-BIO/`, `data/raw/R-ESTUARY/` (Connecticut NERR and CHNEP, added 2026-10-25 from fetched NOAA/EPA/program pages; today the only `facilities_*.json` ingest picks up, so corrections to those two rows go in that file, not `facility_fixes.csv`) and `data/raw/J-ESTUARY/` (their archive links, loaded by `load_lto_archives.py` and pinned by `facility_id`, since a fuzzy name match against a lake without those rows lands on another reserve).

- **`facilities.state` is derived.** Any loader that adds facilities must be followed by `scripts/backfill_facility_state.py`, or the new rows drop out of the New Mexico and drylands lenses. `qa.py` fails on a US facility with coordinates and no state.

- **Merged people stay merged.** `dedupe_people.py` merges on identifiers, or on a reviewed pair in `data/seed/people_merge_seed.csv` (spellings of one name at the same facility, or a fetched ORCID/OpenAlex record), and logs every merge in `data/seed/people_merge_log.csv`. Every people loader reads ids through `load_people_research.canonical_person_id`, so a seed CSV or research file written before a merge never re-creates the duplicate; `qa.py` fails if a merged id is back, or if two person_ids at one facility are spellings of one name (`same_person_name`). Loaders only fill a person's homepage/notes/identifiers; they never overwrite what a research batch wrote.

- **Merged facilities stay merged.** `merge_facilities.py` merges only reviewed, cited pairs in `data/seed/facility_merge_seed.csv` (survivor_id, duplicate_id, evidence, optional location_label, optional drop_personnel: space-separated `person_id:role` rows of the duplicate to delete rather than move, e.g. a network director listed on every node; a pair the duplicate lacks stops the run). It moves or drops every child row: on a personnel collision the row with evidence wins, then `_FP_RANK`; the survivor's facet set (spheres, networks, area_links, …) wins; a site point more than 1 km from the survivor's points and HQ is kept, its id re-minted and, if it carried the duplicate's name, relabelled; funding ids are re-derived. Each merge is logged in `data/seed/facility_merge_log.csv` (a scratch `--catalog` run logs next to its catalog instead). `lto_db.canonical_facility_id()` redirects a merged id wherever a committed file names one (`load_people_research`, the `fetch_funding_*` overrides, `backfill_facility_ror --apply-log`, `seed_people_from_openalex`). `ingest.py` *drops* a raw record whose id was merged (`[merged] skip`) instead of redirecting it, because its upsert would overwrite the survivor's curated values. `qa.py` fails if a merged id is back in `facilities` and warns if an override CSV or `facility_fixes.csv` still names one. In-place corrections with a cited source per value go in `data/seed/facility_fixes.csv` (`apply_facility_fixes.py`): `set` on a facility column (a blank value means NULL), facets (spheres, networks, area_links, facility_ecosystems), and keyed rows via the `key` column (`locations` by location_id, `facility_personnel` by `person_id:role`, `facility_archives` by archive_id, `data_products` by product_id, `funding_events` by event_id); `remove` on locations, personnel, archives, products and funding events, where `funding_events remove superseded-by-award <source>` deletes an award-less stub only once that source has written an award row with an amount. `facility_personnel set role` renames the key (applied before other sets, which then name the new role); `data_products assign` moves a product to the row's facility. `--dry-run` lists removes whose key matches no row. A merge or fix that drops a person's last facility role leaves facility-inherited `person_areas` rows behind; `compute_person_areas.py` prunes them and `qa.py` fails until it has run.

- **Merged funders stay merged.** `merge_funders.py` merges reviewed pairs in `data/seed/funder_merge_seed.csv` (survivor_id, duplicate_id, optional `|`-separated aliases, evidence). Pick the survivor a live fetcher mints (NSF = blake2b('national science foundation'), not ingest's sha1('nsf')). It re-keys every `funding_events` row with the hash family that minted it (ingest stub, load_lto_funding sha1, NSF/USAspending blake2b, agency-budget, 990), drops a re-keyed row only when it is the same event the survivor already has (logging any relation or citation lost), fills the survivor's NULL type/country/url/notes, deletes the duplicate's derived `funder_area_funding` rows (re-run `compute_area_metrics.py`) and logs to `data/seed/funder_merge_log.csv`. `lto_db.canonical_funder(id, name)` reads that log and redirects the merged id plus both hash families' ids of each merged name, alias and kept name, returning the survivor's name; every writer that mints a funder id (`ingest.py`, `load_lto_funding.py`, `fetch_funding_*.py`, `load_agency_budgets.py`, `seed_funding_events_sample.py`, `migrate_funding_events.py`) goes through it, and `load_lto_funding.py` upserts funders with `coalesce` so a merged name's raw record never blanks the survivor's url/type. `qa.py` fails if a redirected id is back in `funders` or `funding_events`, and warns if a funding input names a merged funder id or name. When a removed event's funder is merged, add a `remove` row for its re-keyed id too, or a re-run of its loader brings it back.

- **Contact details are not published.** `people.email` is not written by the loaders and `export_parquet.EXPORT_REDACT` blanks it on export; `qa.py` fails if `public/parquet/people.parquet` carries one. Views and SQL-tab examples must not select it.

## Regional focus: ARID and New Mexico

The catalogue is national, but the site opens on New Mexico and the Southwest drylands and carries a layer for UNM's ARID Institute and for EnviroData-NM. `docs/arid.md` is the human-facing writeup.

- **Scope lens** — `SCOPES` in `src/filters.js` (ARID / New Mexico / Southwest drylands (default) / All U.S.). Each lens is defined twice, as SQL and as a test over GeoJSON-fallback properties (`state`, `has_arid_sphere`, `in_arid_network`, written by `export_parquet.py`); keep the two in step. Nothing is deleted to make the narrower views.
- **ARID layer** — `fetch_arid_site.py` → `data/raw/R-ARID/arid_site.json` (what each page says, as written); curated identity and projects in `data/seed/arid_{people,projects,partner_centers}.csv`; `load_arid.py` writes facilities (network `arid-unm`), people, `projects`, `project_personnel`, `project_facilities`. A name the people seed does not know stops the load on purpose.
- **EnviroData-NM** — `fetch_envirodata_nm.py` → `data/raw/J-ENVIRODATA/*.json` → `load_lto_archives.py`. One `data_archives` row and one `data_products` row per portal layer. **Metadata and links only; never copy features** — the portal's terms forbid redistribution. Its catalogue endpoint is undocumented.
- **Arizona Water Observatory** — `fetch_az_water_observatory.py` → `data/raw/J-AZWATER/*.json` → `load_lto_archives.py`. One archive (`arizona-water-observatory`) and one product per OGC API collection, built from the API's `/collections` document alone. Pointers only, like EnviroData-NM; `POINTER_ARCHIVES` in `qa.py` holds the host each archive's links must stay on.
- Everything in this layer is fetched or cites a fetched page. Do not fill it from model recall.

## MESA project on the CyVerse Data Store

The published copy of the lake lives at `/iplant/home/tswetnam/lto`, an enrolled MESA project (`mesa.enabled=true`; AVU history as `snapshot_<id>.parquet` under `.mesa/ducklake/`). `scripts/publish_to_mesa.py` is the only way content gets there; read its docstring before publishing.

- **Publish from a clean `main`.** `--dry-run` stages to `.mesa_publish/` and writes `.mesa_publish_avus.json` without uploading. The upload itself needs `gocmd`; mesa-mcp's `ds_upload_file` only returns instructions.
- **Metadata goes through mesa-mcp, never `imeta`.** Only writes made through mesa-mcp are mirrored into the project's DuckLake history. One `ds_add_avus` call is one snapshot, so batch per target.
- **iRODS adds AVUs, it never replaces them.** Delete a superseded value (`ds_delete_avu`, by attribute and exact value) before adding its replacement. The root carries one DataCite record (canonical `datacite.*` names plus the CyVerse-template names such as `Description` and `Subject`; the mixed-case pairs are intentional), seven `envo.*` sphere terms, and one current `lto.publish.*` stamp.
- **Table AVUs are the stable facts only** (`lto.table.name`, `.description`, `.kind`, `.generator`, `.columns`), sourced from `schema/table_descriptions.csv`. Row counts and checksums go in `TABLES.json` / `MANIFEST.json`. A new table needs a row in that CSV or the publish preflight fails.
- **Keep AVU values under ~400 characters.** Values near 900 characters lost the server response through mesa-mcp: the write landed but was not mirrored to DuckLake.
- **The DuckLake catalog is per machine** (`~/.mesa/ducklake/catalog.duckdb`). On a machine where the project is not yet registered, run `mesa_ducklake_init_project` once (idempotent) before writing AVUs, or the writes are not recorded.

## Domain model

Facilities are classified along the LTO **seven-sphere** model (`spheres`, `facility_spheres` with a `primary` role): atmosphere, cryosphere, terrestrial/ecological, arid, agriculture, aquatic-ocean/estuarine, aquatic-freshwater. `arid` was split out of terrestrial for the drylands work (commit e6d3741). Orthogonal facets are `ecosystem_types` and `life_zones` (via `facility_ecosystems` / `facility_life_zones`). The Peters et al. 2013 long-term threshold (≥10 years of record), stored as `facilities.record_length_years` and `long_term_threshold_met`, is surfaced as the optional "≥10y" filter. It is off by default; the site opens on the Southwest drylands lens. `docs/data-model.md` and `docs/spheres.md` are the human-facing writeups.

Beyond facilities the schema covers: regions (overlay polygons + `facility_regions` containment edges), people (`facility_personnel`, `publications`, `publication_topics`, `authorship`, `person_areas`, `collaborations`), data archives (Wave J: `data_archives`, `data_products`, `api_endpoints`, `cloud_buckets`), and precomputed MVG groupings (`facility_primary_groups`, `person_primary_groups`, `person_area_metrics`, `area_coverage_matrix`). The authoritative table lists are `TABLES` in `scripts/export_parquet.py` (export side) and the `tables` array in `src/db.js` (frontend side) — they must agree.

## Script families

`scripts/` has ~60 files; they fall into groups, and the group tells you when to run one. All of them open the lake through `lto_db.py`.

- **Core pipeline** — `lto_db.py` (shared helper), `rebuild_lake_from_parquet.py`, `ingest.py`, `qa.py`, `export_parquet.py`, `export_view_caches.py`, `lake_maintenance.py`, `geocode.py`.
- **`load_*.py`** — idempotent loaders for hand/agent-authored JSON+CSV under `data/raw/<AGENT>/` and `data/seed/`. Each `MERGE`s on a deterministic ID hash, so re-runs update rather than duplicate, one snapshot per run (`load_people_research.py` writes one per input file).
- **`enrich_people_*.py`** — external identity/bibliometric APIs (ORCID, OpenAlex, Google Scholar). Strict matching by design: a wrong ORCID is worse than a missing one, so unmatched rows stay NULL.
- **`fetch_funding_*.py`** — NSF Award Search, USAspending, IRS 990. Write into `funding_events` keyed `sha1(funder||facility||award_id||fiscal_year)`.
- **`compute_*.py`** + `build_mvg_layout.py` — derived tables (collaborations, person/area metrics, MVG primary groups and layout), written into the lake with `replace_table`. Re-run after anything that grows the publication or funding graph, in this order: `compute_collaborations` → `compute_person_areas` → `compute_primary_groups` → `compute_area_metrics` (its funding and coverage tables join `facility_primary_groups`) → `build_mvg_layout`.
- **URL hygiene** — `check_url_health.py` (HTTP HEAD sweep → `url_health` lake table + CSV), `url_hygiene.py` (pattern rewrites), `apply_*_url_*.py`. Decision logs land in `data/seed/*.csv`; those CSVs are the reviewable artifact.

`data/seed/` is the manually-curated layer (personnel seeds, ORCID resolution log, URL health/hygiene logs) and is committed — treat it as input, not output.

## Pipeline / wave model

Subagents are organized in waves; each `agents/<ID>-*.md` declares scope, sources, inputs, outputs, method, and known-landmark QA checks. Beyond the original `R1..R10`, later waves add sphere-specific agents (`R-ATM`, `R-CRY`, `R-TER-*`, `R-AGR`, `R-AQ-*`), `R-PEOPLE`, `H-FUND-PUB`, `J-DATA`, and `L-URL-FIX`. Older agent specs still name `db/cod_kmap.duckdb` / `db/lto.duckdb`; read those as "the lake".

```
Wave 1  D1 schema  + D3 vocabulary           → schema/, schema/vocab/
Wave 2  R1..R8 regional research agents      → data/raw/R*/facilities_*.json
Wave 3  R9 funding-flows, R10 COMPASS sites  → data/raw/R9/, data/raw/R10/
Wave 4  D2 ingest pipeline                   → DuckLake (db/lto_catalog.sqlite + db/lake/) → public/parquet/
Wave 5  F1..F4 frontend + deploy             → src/, public/, .github/workflows/deploy.yml
Wave 6  verification + iteration
```

`ingest.py` globs `data/raw/R*` only — agent directories must start with `R` to be picked up. Every research record must conform to the shared facility JSON schema documented in `agents/README.md` (record_id, canonical_name, facility_type from `schema/vocab/facility_types.csv`, ISO-2 country, hq + locations, research_areas slugs, networks, funders with `relation`, **provenance with source_url + confidence**). D2 dedupes by facility_id, URL, and fuzzy-name + 5 km haversine.

When network access is unavailable, the working pattern is the parallel-subagent fan-out described in `agents/H-FUND-PUB.md` and `agents/R-PEOPLE.md`: agents write single JSON files into `data/raw/<AGENT>/`, then a `load_lto_*.py` script upserts them.

## Frontend layout

- `index.html` — importmap pulls `maplibre-gl` + `@duckdb/duckdb-wasm` (pinned `1.33.1-dev65.0`, core v1.5.6) from esm.sh; loads `src/main.js` as a module.
- `src/main.js` — bootstraps map, filters, overlays, hash-router, then the 9 routes (`/`, `/browse`, `/network`, `/projects`, `/people`, `/data`, `/sql`, `/stats`, `/docs`). Sub-routes like `/people/<id>`, `/projects/<id>`, `/data/<archive_id>/products` and `/docs/<slug>` dispatch on the first path segment.
- `src/db.js` — DuckDB-Wasm init, parquet view registration, helper views, `query()` (returns GeoJSON Features), and the Arrow→JS unwrap helpers. Each `CREATE OR REPLACE VIEW` is individually try/caught so one missing parquet doesn't break the rest.
- `src/config.js` — `DATA_BASE` resolves all data fetches relative to `index.html`; never hardcode `/public/` paths in views.
- `src/map.js` — `TYPE_COLORS` is the single source of truth for facility-type colours (must match polygon overlay colours in `public/overlays/manifest.json`). The legend also supports colour-by-sphere.
- `src/overlays.js` — lazy-loads polygon layers via `public/overlays/manifest.json`. `DEFAULT_OFF` controls first-paint visibility (heavy / cluttering layers default off).
- `src/views/{list,stats,docs,network,projects,people,datasets,sql}.js` — one per top-tab (`list.js` backs `/browse`, `datasets.js` backs `/data`). `/docs` reads markdown from `docs/` at runtime.

The site degrades in three tiers: GeoJSON fallback → JSON view caches → full DuckDB-Wasm. Changes must not assume DuckDB is ready; `renderList` can be called before `initDB()` resolves.

## CI workflows

- `deploy.yml` (push to `main`) — stages only `index.html`, `favicon.svg`, `src/`, `public/`, `docs/`. Anything outside those paths (agents, scripts, schema, data/raw) is **not** on the live site. Adding a new runtime-fetched directory means editing this staging step.
- `refresh-data.yml` (weekly, Sun 06:00 UTC) — rebuild lake from parquet → `load_arid` → `load_lto_archives` → `backfill_facility_state` → qa → export_parquet → export_view_caches, opens a PR. It does not run `ingest.py` (no raw national inputs in CI).
- `url-health.yml` (weekly, Mon 07:00 UTC) — rebuild lake from parquet → HEAD sweep → hygiene → qa → re-export, opens a PR.

Both scheduled workflows run Python 3.12, rebuild the lake from scratch each run (nothing but pip is cached; the ducklake/sqlite extensions download from extensions.duckdb.org), and open PRs rather than pushing; review the data diffs before merging. The loaders they re-run keep `created_at`/`updated_at` on unchanged rows, so a week with no input change opens no data diff.

Repository settings the YAML depends on (set 2026-10-23): "Allow GitHub Actions to create and approve pull requests" is **on** (`can_approve_pull_request_reviews: true`), with default token permissions left at `read` — each data workflow requests `contents: write` + `pull-requests: write` itself. "Refresh data" is enabled again (it had been `disabled_inactivity`). If GitHub disables a scheduled workflow for inactivity again, `gh workflow enable "Refresh data"`. If the PR step fails with "not permitted to create or approve pull requests", check `gh api repos/tyson-swetnam/lto/actions/permissions/workflow` and re-set it with `echo '{"default_workflow_permissions":"read","can_approve_pull_request_reviews":true}' | gh api -X PUT repos/tyson-swetnam/lto/actions/permissions/workflow --input -` (a JSON body; the `-F` form once read back as `false`).

## External datasets

- `data/raw/synthesis-networks/` is a verbatim MIT-licensed snapshot of [COMPASS-DOE/synthesis-networks](https://github.com/COMPASS-DOE/synthesis-networks). Do **not** edit these files; treat them as upstream. R10 (`scripts/build_r10_from_spatial.py`) derives `data/raw/R10/facilities_synthesis_networks.json` from `network_synth_spatial_analysis/` GeoJSON layers.
- `network_synth_spatial_analysis/coastal_protected/` is gitignored except for the bundled outputs that `build_web_overlays.py` produces.
