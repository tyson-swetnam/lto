# lto — U.S. Long-Term Observatories

`lto` is an interactive map and database cataloguing United States long-term
environmental observatories across seven interlocking spheres. As of
2026-10-25 it holds 446 facilities and 1,310 people. The site is a static
MapLibre + DuckDB-Wasm front-end (DuckDB 1.5.6 in the browser) that reads
Parquet files over HTTP. Behind it, a Python pipeline loads research-agent
and fetched-source JSON into a DuckLake store of record (DuckDB 2.0), checks
it with a QA gate, and exports Parquet + GeoJSON.
It is forked and extended from
[`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap) (MIT).

## New Mexico and ARID focus

The site opens on New Mexico and the Southwest drylands. It carries a layer
for UNM's ARID Institute (its partner centers, projects and people). It also
indexes every layer in EnviroData-NM, the state's environmental data portal,
and every API collection of the Arizona Water Observatory. The national
catalogue is all still here: switch the **Scope** filter from *Southwest
drylands* to *All U.S.* See [ARID & New Mexico](./arid.md).

## The seven spheres

- **Atmosphere** — gas-flux, deposition, radiation, and trace-gas networks
  (NOAA-GML, NADP, AmeriFlux, ARM, CASTNET, IMPROVE, SURFRAD, TCCON).
- **Cryosphere** — glaciers, snow, sea-ice, and permafrost observatories
  (USGS Benchmark Glaciers, SNOTEL, CRREL, Toolik, McMurdo Dry Valleys).
- **Terrestrial / Ecological** — long-term ecology and forest research
  (NSF LTER, NEON, USFS Experimental Forests & Ranges, NPS-IM, LTREB).
- **Arid** — hot and cold deserts, dryland shrublands and grasslands
  (Jornada Basin and Sevilleta LTERs, NEON desert sites, NPS-IM Sonoran
  Desert Network, USGS Canyonlands). Split out of Terrestrial in August 2026.
- **Agriculture** — long-term cropping, rangeland, and soil networks
  (USDA-ARS LTAR, ARS Rangelands, USDA Climate Hubs, SCAN, KBS-AG).
- **Aquatic — Ocean & Estuarine** — coastal, ocean, and estuary networks
  (IOOS Regional Associations, OOI, NERRS, NMS, NEP, MarineGEO).
- **Aquatic — Freshwater** — rivers, lakes, and watersheds
  (USGS NWIS / WEBB / HBN, GLEON, NTL-LTER, Hubbard Brook, EPA NARS).

## Inclusion gate

The long-term reference is the **Peters et al. 2013 ≥10-year
continuous-record threshold** (USDA ARS Tech. Bulletin 1931). As of
2026-10-25, 320 of the 446 facilities meet it. Facilities below the
threshold stay in the database and are shown by default. Tick **Show only
facilities with ≥10y record** in the filter panel to hide them.

## Read next

- [arid](./arid.md) — the ARID Institute layer, the scope lens, EnviroData-NM
  and the Arizona Water Observatory.
- [spheres](./spheres.md) — anchor networks and landmark sites per sphere.
- [networks](./networks.md) — full controlled-vocabulary inventory.
- [coverage](./coverage.md) — record counts and landmark-coverage gaps.
- [methods](./methods.md) — the wave/agent pipeline, the DuckLake store and
  provenance rules.
- [data-model](./data-model.md) — schema quick-reference for the tables.
- [knowledge map](./knowledge-map.md) — how the Network tab sizes and labels
  research areas.
- [data access](./okf/index.md) — how to reach each data archive.
- [sources](./sources.md) — foundational papers and data providers.
- [loops](./loops.md) — the parallel agent-loop pattern.

Source repository: <https://github.com/tyson-swetnam/lto>.
