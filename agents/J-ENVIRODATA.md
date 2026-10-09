# J-ENVIRODATA — EnviroData-NM layers as pointer records

## Scope

Every visible layer of EnviroData-NM (<https://envirodata-nm.unm.edu>),
New Mexico's environmental data portal, as one `data_archives` row and
one `data_products` row per layer.

The portal is run by Natural Heritage New Mexico, a division of the
Museum of Southwestern Biology at UNM, under the 2021 Environmental
Database Act (HB51). Its terms do not permit redistributing the data, so
this agent records **metadata and links only** and never downloads a
layer's features. The catalogue is a lakehouse-style index over the
portal's own endpoints, plus metadata the portal does not surface in one
place (bounding box, schema, feature count, upstream service).

Excluded: hidden layers and groups; the layers' feature data; the
upstream agencies' own ArcGIS metadata.

## Sources

1. `https://envirodata-nm.unm.edu/explore/api/layers` — the catalogue:
   groups, layers, descriptions, download flag, upstream service.
   Undocumented; found by inspection.
2. `https://envirodata-nm.unm.edu/ogc/layers` — geometry type per layer.
3. `/ogc/wms/<layer>?service=WMS&request=GetCapabilities` — bounding box.
4. `/ogc/attributes/<layer>?limit=0` — column names and feature count,
   with no rows.
5. <https://envirodata-nm.unm.edu/cms/about/> and `/terms` — who runs
   the portal and on what terms.

## Inputs

- `schema/vocab/data_formats.csv` (`ogc-wms`), `data_licenses.csv`
  (`envirodata-nm-terms`), `archive_types.csv` (`data-portal`).
- The `ARID` and `Museum of Southwestern Biology` facility rows from
  R-ARID, for the two `facility_archives` links. Load R-ARID first.

## Outputs

`scripts/fetch_envirodata_nm.py` writes, in the shapes
`scripts/load_lto_archives.py` already reads:

- `data/raw/J-ENVIRODATA/archives.json` — the `envirodata-nm` archive.
- `data/raw/J-ENVIRODATA/data_products.json` — one row per layer.
- `data/raw/J-ENVIRODATA/api_endpoints.json` — six endpoint templates.
- `data/raw/J-ENVIRODATA/facility_archives.json` — links to MSB and ARID.

## Method

- One request per second; per-layer responses are cached under `_state/`
  so a run can resume, and `--offline` rebuilds the JSON from the cache.
- Per product: `identifier` is the portal's layer name; `url` is the
  GeoJSON download where the portal allows it and the WMS capabilities
  document where it does not; `api_url` is the layer's WMS endpoint;
  `category` is the portal's group path; `description` is the portal's
  abstract as plain text; `variables_text` is the column list.
- The upstream ArcGIS host is recorded in `notes` as where the portal
  harvested from. It is the server, not necessarily the originating
  agency, and is worded that way.
- A layer whose service errors still gets a record, with the failure and
  date in its `notes`.
- The ARID link is the lto project owner's statement, not something
  either website documents; its `notes` say so.

## Known landmarks

- 139 products, each with a `url` and `api_url` on
  `https://envirodata-nm.unm.edu/`.
- Six top-level categories: Wetlands, Forests, and Ecosystems; Ecosystem
  Conservation and Restoration; Environmental Quality; Reference; Energy
  Development; Community Health.
- "Current Wildfire Incidents (Last 7 Days)" is present under Wetlands,
  Forests, and Ecosystems.
- Layers with download disabled (oil and gas wells, State Land Office
  leases) have `format_slug = 'ogc-wms'` and no download URL.
