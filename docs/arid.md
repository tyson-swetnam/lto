# ARID and New Mexico

`lto` is a national catalogue with a regional focus. This page describes the
layer built around the University of New Mexico's
[ARID Institute](https://arid.unm.edu) (Accelerating Resilience Innovations
in Drylands) and around [EnviroData-NM](https://envirodata-nm.unm.edu), New
Mexico's environmental data portal, which this work is meant to support.

## The scope lens

The **Scope** control at the top of the filter panel narrows every facility
view. Nothing is removed from the data to make the narrower views.

| Scope | What it shows |
|---|---|
| ARID Institute & partners | The institute and the UNM centers and sites it lists |
| New Mexico | Every catalogued facility whose location falls in the state |
| Southwest drylands (default) | NM, AZ, UT, CO, NV, Texas west of 100°W, and any facility with an `arid` sphere |
| All U.S. | The whole catalogue |

The lens rests on `facilities.state`, which is derived, not typed: each
facility's HQ point is tested against U.S. Census state boundaries
(`scripts/backfill_facility_state.py`), and the decision for every facility
is logged in `data/seed/facility_state.csv`.

## The ARID layer

Everything in this layer is read from ARID's own web pages or from a
hand-reviewed seed that cites one. Nothing is recalled from memory.

- **The institute and its partner centers** are facility rows in the
  `arid-unm` network: ARID itself plus the eleven "Resources at UNM" on its
  Resources Hub (the Bosque Ecosystem Monitoring Program, the Center for
  Water and the Environment, the Museum of Southwestern Biology, and others).
  Sevilleta LTER was already catalogued and is linked, not duplicated.
- **Projects** have their own tab. A project is a body of work, not a
  place, so it is not a facility. Twelve are recorded: ARID's six listed
  projects, the four cores of CHANGES, and two CHANGES field efforts.
- **People** — the 26-member leadership team, four staff, and each
  project's named team — carry the *ARID* pill on the People tab.

Three rules keep the layer honest:

1. **A project has a map point only where its page names a place**, and
   `location_precision` says how exact it is. County and city points are
   centroids, drawn as hollow rings. Statewide projects have no point.
2. **Titles are kept as each page words them.** Where two pages disagree
   about a person, both versions survive on the rows they came from.
3. **A name the seed does not know stops the load.** A new face on the
   site, or a new misspelling, gets a human decision rather than a silently
   created duplicate.

## EnviroData-NM

EnviroData-NM is run by Natural Heritage New Mexico, a division of the
Museum of Southwestern Biology at UNM, under the 2021 Environmental
Database Act (HB51). The catalogue indexes all of its visible layers — 139
when last read — as records that **point back to the portal**.

- **No data is copied.** Each record holds metadata and links. Its title
  opens the portal's own download where the portal offers one, and the
  layer's WMS service otherwise.
- **What the index adds** is metadata the portal does not show in one
  place: bounding box, field names, feature count, geometry type, the
  upstream ArcGIS service each layer was harvested from, and when.
- **Find them** on the Data tab under *EnviroData-NM*, filterable by the
  portal's six categories, or in the SQL tab:
  `SELECT * FROM data_products WHERE archive_id = 'envirodata-nm'`.

The portal's catalogue endpoint is not documented and may change;
`scripts/fetch_envirodata_nm.py` fails loudly rather than writing an empty
index if it does.

## Arizona Water Observatory

The drylands lens reaches into Arizona, and so does the data index. The
[Arizona Water Observatory](https://arizonawaterobservatory.asu.edu) (AWO),
hosted at Arizona State University with the Internet of Water, publishes
state, federal and ASU-derived water datasets through one
[OGC API](https://arizonawaterobservatory-api.rtd.asu.edu/openapi?f=html).
Its 26 collections are catalogued the same way as EnviroData-NM: as
pointers, with no data copied.

- Each record links the collection's page and its API endpoint, and carries
  the spatial and temporal extent, the parameter list, which query types
  it answers (features, EDR time series, grids, maps), and the upstream
  agency service it fronts.
- Arizona-specific collections include the Department of Water Resources
  groundwater site inventory, groundwater basins, Active Management Areas
  and irrigation districts, the Central Arizona Project canal, and
  GRACE-derived groundwater storage change for the Lower Colorado basin.
- Several collections are regional or national in extent (SNOTEL, the
  National Water Model, Reclamation's RISE, PRISM); each record's bounding
  box says which.
- **Find them** on the Data tab under *Arizona Water Observatory*, or in
  SQL: `SELECT * FROM data_products WHERE archive_id = 'arizona-water-observatory'`.

## Refreshing the layer

```bash
python scripts/rebuild_db_from_parquet.py
python scripts/fetch_arid_site.py          # arid.unm.edu → data/raw/R-ARID/
python scripts/load_arid.py
python scripts/backfill_facility_state.py
python scripts/fetch_envirodata_nm.py      # ~5 min, one request per second
python scripts/fetch_az_water_observatory.py   # two requests
python scripts/load_lto_archives.py
python scripts/qa.py && python scripts/export_parquet.py && python scripts/export_view_caches.py
```

Agent specs: `agents/R-ARID.md`, `agents/J-ENVIRODATA.md` and `agents/J-AZWATER.md`.
