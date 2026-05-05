# cod-kmap validation report
_Run at 2026-04-19T03:02:02Z; branch claude/coastal-research-database-zZgWk; head ec23e97fecf80d5cc0fc1ffc92a8c877df66812b_

## Summary
**FAIL** — 2 high-severity issues found out of 6 checks.

1. **HIGH**: `filters.js` SQL references `ra.slug` and `n.slug` but the `research_areas` parquet has column `area_id` and `networks` parquet has column `network_id` — area and network filters will throw a SQL column-not-found error at runtime.
2. **HIGH**: 86 / 118 facilities (73%) have only a single funder link ("thin-funder"), suggesting funder data is incomplete for the majority of records.
3. LOW: 7 R7 South America landmarks (CENPAT, FURG, DINARA, IVIC) and 2 R8 Caribbean landmarks (Acuario Nacional de Cuba, Turks and Caicos Reef Fund/DECR) are absent from the DB.
4. LOW: Working tree is dirty — 17 modified files not staged for commit.

Total issues: 2 high, 2 low.

---

## Data integrity

| Metric | Value |
|--------|-------|
| Total facilities | 118 |
| Null hq_lat / hq_lng | 0 |
| Facilities with no research areas | 0 |
| Facilities with no funders | 0 |
| Thin-funder count (exactly 1 funder) | **86 / 118** |
| Duplicate (canonical_name, country) | 0 |

**Facility types:** federal 29, international-federal 19, university-marine-lab 17, network 15, international-university 13, state 8, international-nonprofit 7, nonprofit 6, foundation 3, observatory 1.

**Countries:** US 75, CA 12, MX 5, PA 3, and 17 more (20 total).

**Orphan checks:** area_links, funding_links, network_membership, locations — 0 orphans each. Provenance uses `record_id` (not `facility_id`); 0 orphaned facility records.

**Vocab coverage:** All `area_id` values in `area_links` resolve in `research_areas`; all `network_id` values in `network_membership` resolve in `networks`; all `facility_type` slugs resolve in `facility_types`. No vocab gaps.

**Landmark spot-check (R1–R8):**
- R1 (US federal): all 7 checked — FOUND.
- R2 (US universities): all 9 checked (SIO, WHOI, MBARI, MBL, HIMB, FHL, BML, VIMS, DISL) — FOUND.
- R3 (networks): IOOS + 4 regional associations — FOUND.
- R5 (Canada): BIO, IOS, ONC, BMSC — FOUND. DFO parent org not a standalone facility (expected).
- R6 (Mexico/CA): CICESE, ICML-UNAM, INAPESCA, ECOSUR, STRI, CIMAR — all FOUND.
- R7 (South America): INVEMAR, IMARPE, INIDEP, IFOP, SHOA, CDF, INOCAR — FOUND. **MISSING:** CENPAT-CONICET (AR), FURG (BR), DINARA (UY), IVIC/EDIMAR (VE).
- R8 (Caribbean): UPRM-DMS, UVI-CMES, CARICOOS, PIMS, DBML, PRML, CIM-UH, CIBIMA, GRC, UWI-CERMES — FOUND. **MISSING:** Acuario Nacional de Cuba, Turks and Caicos Reef Fund/DECR.

---

## Artifact cross-reference

| Artifact | Count | Match? |
|----------|-------|--------|
| DuckDB `facilities` table | 118 | — |
| `web/public/parquet/facilities.parquet` | 118 | PASS |
| `db/parquet/facilities.parquet` | 118 | PASS |
| `web/public/facilities.geojson` features | 118 | PASS |

**Required parquet files for F3 query** (`web/public/parquet/`): facilities, locations, funders, funding_links, research_areas, area_links, networks, network_membership — all 8 present.

**Vocab CSVs** (`web/public/vocab/` vs `schema/vocab/`): `facility_types.csv`, `networks.csv`, `research_areas.csv` — all byte-for-byte identical. `schema/vocab/VERSION` file has no counterpart in `web/public/vocab/` (minor, not functional).

---

## Web static assets

- `web/index.html`: references `/src/styles.css` (line 21) and `/src/main.js` (line 44) — PASS.
- `web/src/main.js`: imports `./map.js`, `./filters.js`, `./db.js` — PASS.
- `web/src/map.js`: imports `leaflet`, `leaflet.markercluster`, `./csv.js` — PASS.
- `web/src/filters.js`: imports `./csv.js` — PASS.
- `web/src/db.js`: imports `./filters.js` (applyFilters) and `@duckdb/duckdb-wasm` — PASS.
- `web/src/csv.js`: present — PASS.
- No broken relative imports detected.
- `web/package.json`: declares `leaflet ^1.9.4`, `leaflet.markercluster ^1.5.3`, `@duckdb/duckdb-wasm ^1.29.0` (deps) and `vite ^5.4.0` (devDep) — PASS.

---

## DB ↔ UI SQL contract

**`facilities.parquet` schema check** — columns referenced in `db.js` main query:
`canonical_name`, `facility_type`, `hq_lat`, `hq_lng`, `url`, `parent_org` — all present. PASS.

**Filter join correctness — BUG FOUND:**

The `applyFilters` function in `filters.js` generates SQL:
```sql
JOIN research_areas ra ON ra.area_id = al.area_id WHERE ra.slug IN (...)
JOIN networks n ON n.network_id = nm.network_id WHERE n.slug IN (...)
```
The `research_areas` parquet schema has columns `area_id`, `label`, `gcmd_uri`, `parent_id` — **no `slug` column**. The `networks` parquet has `network_id`, `label`, `level`, `url` — **no `slug` column**. Both filter subqueries will fail at runtime with a column-not-found error when a user selects an area or network filter.

**Fix:** Replace `ra.slug` → `ra.area_id` and `n.slug` → `n.network_id` in `filters.js` (lines 161 and 170). The underlying values are already slug-format strings (e.g. `oceanography`, `ioos`).

**`area_links` join column:** `area_id` — matches schema. PASS.
**`network_membership` join column:** `network_id` — matches schema. PASS.

---

## Agent specs

All required files present under `agents/`:
- Researcher: R1–R9 (9 files) — PASS.
- Design: D1–D3 (3 files) — PASS.
- Feature: F1–F4 (4 files) — PASS.
- `agents/README.md` present — PASS.

---

## Git state

Recent commits (last 3):
1. `9ade559` — `data(fix) + feat(web): audit fixes, 10 new records, UI design upgrade`
2. `7ec9257` — `data(R2-R8): seed 84 coastal research facilities + ingest pipeline fixes`
3. `b8bd699` — `data(R1): seed 25 flagship US federal coastal research facilities`

Commit messages are descriptive and follow conventional-commit style. PASS.

**Working tree:** 17 modified files (db, parquet exports, geojson) — not staged. These appear to be legitimate artifact updates that need committing.

---

## Action items (if any)

1. **[HIGH] Fix `filters.js` column name bug** — change `ra.slug` → `ra.area_id` (line 161) and `n.slug` → `n.network_id` (line 170). Area and network filters are currently broken.
2. **[HIGH] Investigate thin-funder coverage** — 86 facilities have only 1 funder link; many likely have secondary funders (e.g., NSF, state agencies) that were not captured. Run a funder-enrichment pass.
3. **[MED] Commit staged artifact changes** — 17 modified parquet/geojson/duckdb files in the working tree should be committed.
4. **[LOW] Add missing R7 landmarks** — CENPAT-CONICET (AR), FURG (BR), DINARA (UY), IVIC/EDIMAR (VE) are in the R7 spec but absent from the DB.
5. **[LOW] Add missing R8 landmarks** — Acuario Nacional de Cuba and Turks and Caicos Reef Fund/DECR are in the R8 spec but absent.
6. **[LOW] Add `VERSION` file to `web/public/vocab/`** — schema/vocab/ has a VERSION file not mirrored in the web-served vocab directory.
