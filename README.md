# lto — Long-Term Observatories of the United States

An interactive map and database cataloguing U.S. long-term environmental observatories
across seven interlocking spheres:

- **Atmosphere** — NOAA GML / Mauna Loa, NADP, AmeriFlux, ARM, CASTNET, IMPROVE, SURFRAD …
- **Cryosphere** — USGS Benchmark Glaciers, SNOTEL, CRREL, Toolik, McMurdo Dry Valleys, Juneau Icefield …
- **Terrestrial / Ecological** — NSF LTER, NEON (81 sites), USFS Experimental Forests & Ranges (77),
  NPS Inventory & Monitoring, MAB Biosphere Reserves, NWRS, USFS RNAs, LTREB …
- **Arid** — Jornada Basin and Sevilleta LTERs, NEON desert domains,
  Great Basin Experimental Range, Mojave Global Change Facility,
  NPS Sonoran Desert Network …
- **Agriculture** — USDA-ARS Long-Term Agroecosystem Research (LTAR), ARS Rangelands,
  USDA Climate Hubs, SCAN, KBS-AG …
- **Aquatic — Ocean & Estuarine** — IOOS Regional Associations, OOI, NERRS (29),
  National Marine Sanctuaries, NEP, MarineGEO, NPS Coastal, NAML labs …
- **Aquatic — Freshwater** — USGS NWIS / WEBB / Hydrologic Benchmark Network,
  GLEON, North Temperate Lakes LTER, Hubbard Brook, EPA NARS …

The site uses the long-term threshold from Peters et al. 2013 (≥10 years of record)
as the default inclusion gate.

## New Mexico and ARID focus

The catalogue is national, but the site opens on **New Mexico and the Southwest
drylands** and carries a layer for the University of New Mexico's
[ARID Institute](https://arid.unm.edu) — its partner centers, projects and people —
plus an index of every layer in [EnviroData-NM](https://envirodata-nm.unm.edu), the
state's environmental data portal. The EnviroData-NM records are pointers: metadata
and links back to the portal's own download and OGC endpoints, with no data copied.
The [Arizona Water Observatory](https://arizonawaterobservatory.asu.edu)'s OGC API
collections are indexed the same way.
Switch the **Scope** filter to *All U.S.* for the whole catalogue. See
[`docs/arid.md`](docs/arid.md).

## Repository layout

This repo is a **two-stack** project (forked-and-adapted from
[`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap)):

1. **Python data pipeline** (`scripts/`, `schema/`, `data/`) — research subagents
   (`agents/R*-*.md`) emit JSON facility records; `scripts/ingest.py` and the
   `load_*.py` loaders write them into a local [DuckLake](https://ducklake.select)
   store of record (DuckDB 2.0, SQLite catalog at `db/lto_catalog.sqlite`, data
   files in `db/lake/`, both gitignored); `scripts/export_parquet.py` writes
   Parquet + GeoJSON to `public/`. The committed `public/parquet/` is the canonical
   copy of the data, and a fresh clone rebuilds the lake from it.
2. **Static MapLibre + DuckDB-Wasm site** (`index.html`, `src/`, `public/`) —
   published to GitHub Pages with **no build step**.

## Origins

Source repository for the engine: <https://github.com/tyson-swetnam/cod-kmap>
(MIT). Coastal/ocean facilities present in this database originate from cod-kmap;
terrestrial, atmospheric, cryospheric, agricultural, and freshwater coverage is
new in `lto`.

Reference framing for site selection and long-term thresholds:

- Peters, D.P.C. *et al.* 2013. **Long-Term Trends in Ecological Systems: A
  Basis for Understanding Responses to Global Change.** USDA ARS Tech.
  Bulletin 1931.
- Lugo, A.E. *et al.* 2006. **Long-Term Research at the USDA Forest Service's
  Experimental Forests and Ranges.** *BioScience* 56(1): 39–48.

## Quick start

Python 3.11 or newer (DuckDB 2.0).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/rebuild_lake_from_parquet.py  # public/parquet/ → db/lto_catalog.sqlite + db/lake/
python scripts/ingest.py          # data/raw/R*/*.json → upsert into the lake; reloads schema/vocab/*.csv
python scripts/qa.py              # data-quality + schema-constraint gate
python scripts/export_parquet.py  # lake → public/parquet/ + public/facilities.geojson
python scripts/export_view_caches.py
python -m http.server 5173        # then open http://localhost:5173/
```

To look at the site only, skip the Python steps: `python -m http.server 5173`
serves the committed `public/` data as is.

## License

MIT — see `LICENSE`.
