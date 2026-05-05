# lto — Long-Term Observatories of the United States

An interactive map and database cataloguing U.S. long-term environmental observatories
across six interlocking spheres:

- **Atmosphere** — NOAA GML / Mauna Loa, NADP, AmeriFlux, ARM, CASTNET, IMPROVE, SURFRAD …
- **Cryosphere** — USGS Benchmark Glaciers, SNOTEL, CRREL, Toolik, McMurdo Dry Valleys, Juneau Icefield …
- **Terrestrial / Ecological** — NSF LTER, NEON (81 sites), USFS Experimental Forests & Ranges (77),
  NPS Inventory & Monitoring, MAB Biosphere Reserves, NWRS, USFS RNAs, LTREB …
- **Agriculture** — USDA-ARS Long-Term Agroecosystem Research (LTAR), ARS Rangelands,
  USDA Climate Hubs, SCAN, KBS-AG …
- **Aquatic — Ocean & Estuarine** — IOOS Regional Associations, OOI, NERRS (29),
  National Marine Sanctuaries, NEP, MarineGEO, NPS Coastal, NAML labs …
- **Aquatic — Freshwater** — USGS NWIS / WEBB / Hydrologic Benchmark Network,
  GLEON, North Temperate Lakes LTER, Hubbard Brook, EPA NARS …

The site uses the long-term threshold from Peters et al. 2013 (≥10 years of record)
as the default inclusion gate.

## Repository layout

This repo is a **two-stack** project (forked-and-adapted from
[`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap)):

1. **Python data pipeline** (`scripts/`, `schema/`, `data/`) — research subagents
   (`agents/R*-*.md`) emit JSON facility records; `scripts/ingest.py` loads them
   into DuckDB; `scripts/export_parquet.py` writes Parquet + GeoJSON to `public/`.
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

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/ingest.py          # data/raw/R*/*.json → db/lto.duckdb
python scripts/qa.py
python scripts/export_parquet.py
python -m http.server 5173        # then open http://localhost:5173/
```

## License

MIT — see `LICENSE`.
