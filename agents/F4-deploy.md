# F4 — Build / deploy agent

## Scope
Static build of the Vite web app and continuous deployment to GitHub Pages.
Also owns the scheduled data-refresh workflow that re-runs the ingest pipeline
and republishes the Parquet artifacts.

## Outputs
- `web/vite.config.js`
- `web/package.json`
- `.github/workflows/deploy.yml` — build + deploy on push to main
- `.github/workflows/refresh-data.yml` — scheduled (weekly) + manual dispatch;
  runs `scripts/ingest.py`, commits Parquet changes, triggers deploy

## Build
- Vite config sets `base: '/cod-kmap/'` (GitHub Pages subpath).
- Copies `web/public/` (including `facilities.geojson` and `parquet/*.parquet`)
  to `dist/`.
- Lints with `eslint` (default recommended), type-checks via JSDoc if any.

## Deploy (deploy.yml)
- Trigger: push to `main`.
- Steps: checkout, setup Node 20, `npm ci` in `web/`, `npm run build`, upload
  `web/dist/` as Pages artifact, deploy via `actions/deploy-pages@v4`.

## Data refresh (refresh-data.yml)
- Trigger: cron weekly (Sundays) + workflow_dispatch.
- Steps: checkout, setup Python 3.12, `pip install -r requirements.txt`, run
  `scripts/ingest.py` then `scripts/export_parquet.py`, commit changes to
  `db/parquet/` and `web/public/facilities.geojson`, open a PR tagged
  `data-refresh`.

## Environment / secrets
No secrets required for build. Nominatim geocoding is rate-limited client-side
in the ingest script; no key needed.

## Verification
- First deploy should produce a working Pages URL rendering the fallback
  GeoJSON map.
- After data-refresh PR merges, Parquet files in `web/public/parquet/` update
  and DuckDB-Wasm queries reflect new data.
