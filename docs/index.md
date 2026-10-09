# lto — U.S. Long-Term Observatories

`lto` is an interactive map and database cataloguing United States long-term
environmental observatories across seven interlocking spheres. The site is a
static MapLibre + DuckDB-Wasm front-end backed by a Python ingest pipeline
that loads research-agent JSON into DuckDB and exports Parquet + GeoJSON.
It is forked and extended from
[`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap) (MIT).

## New Mexico and ARID focus

The site opens on New Mexico and the Southwest drylands. It carries a layer
for UNM's ARID Institute — its partner centers, projects and people — and an
index of every layer in EnviroData-NM, the state's environmental data portal.
The national catalogue is all still here: switch the **Scope** filter to
*All U.S.* See [ARID & New Mexico](./arid.md).

## The seven spheres

- **Atmosphere** — gas-flux, deposition, radiation, and trace-gas networks
  (NOAA-GML, NADP, AmeriFlux, ARM, CASTNET, IMPROVE, SURFRAD, TCCON).
- **Cryosphere** — glaciers, snow, sea-ice, and permafrost observatories
  (USGS Benchmark Glaciers, SNOTEL, CRREL, Toolik, McMurdo Dry Valleys).
- **Terrestrial / Ecological** — long-term ecology and forest research
  (NSF LTER, NEON, USFS Experimental Forests & Ranges, NPS-IM, LTREB).
- **Agriculture** — long-term cropping, rangeland, and soil networks
  (USDA-ARS LTAR, ARS Rangelands, USDA Climate Hubs, SCAN, KBS-AG).
- **Aquatic — Ocean & Estuarine** — coastal, ocean, and estuary networks
  (IOOS Regional Associations, OOI, NERRS, NMS, NEP, MarineGEO).
- **Aquatic — Freshwater** — rivers, lakes, and watersheds
  (USGS NWIS / WEBB / HBN, GLEON, NTL-LTER, Hubbard Brook, EPA NARS).

## Inclusion gate

The default filter on the map and list views is the **Peters et al. 2013
≥10-year continuous-record threshold** (USDA ARS Tech. Bulletin 1931).
Facilities below that threshold are kept in the database and shown; tick
**Show only facilities with ≥10y record** in the filter panel to hide them.

## Read next

- [arid](./arid.md) — the ARID Institute layer, the scope lens, and EnviroData-NM.
- [spheres](./spheres.md) — anchor networks and landmark sites per sphere.
- [networks](./networks.md) — full controlled-vocabulary inventory.
- [coverage](./coverage.md) — current record counts and landmark-coverage gaps.
- [methods](./methods.md) — the wave/agent pipeline and provenance rules.
- [data-model](./data-model.md) — schema quick-reference for the DuckDB tables.
- [sources](./sources.md) — foundational papers and data providers.
- [loops](./loops.md) — agent-loop pattern and CI enrichment.

Source repository: <https://github.com/tyson-swetnam/lto>.
