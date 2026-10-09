# J-AZWATER — Arizona Water Observatory collections as pointer records

## Scope

Every collection of the Arizona Water Observatory API
(<https://arizonawaterobservatory-api.rtd.asu.edu>), as one `data_archives`
row and one `data_products` row per collection. AWO
(<https://arizonawaterobservatory.asu.edu>) is hosted at Arizona State
University with the Internet of Water (Center for Geospatial Solutions,
Lincoln Institute of Land Policy); the API is a pygeoapi deployment whose
source is <https://github.com/cgs-earth/ArizonaWaterObservatory>.

Metadata and links only, as for J-ENVIRODATA: no features, time series or
tiles are requested. Most collections front another agency's service, so
the record names that upstream source rather than treating AWO as the
originator.

Excluded: the collections' data; the upstream agencies' own metadata; the
AWO web application's dashboards.

## Sources

1. `https://arizonawaterobservatory-api.rtd.asu.edu/collections?f=json` —
   the only document the records are built from: title, description,
   keywords, extent, parameter names, query types, and the `canonical` /
   `documentation` / `methodology` links.
2. `https://arizonawaterobservatory-api.rtd.asu.edu/?f=json` — the
   service description.
3. `.../openapi?f=json` — path inventory, used for the endpoint templates.

## Inputs

- `schema/vocab/archive_types.csv` (`aggregator`), `data_formats.csv`
  (`geojson`, `json`), `data_licenses.csv` (`unknown`).

## Outputs

`scripts/fetch_az_water_observatory.py` writes, in the shapes
`scripts/load_lto_archives.py` reads:

- `data/raw/J-AZWATER/archives.json` — the `arizona-water-observatory` archive.
- `data/raw/J-AZWATER/data_products.json` — one row per collection.
- `data/raw/J-AZWATER/api_endpoints.json` — seven endpoint templates.

## Method

- Two requests; responses cached under `_state/`, `--offline` rebuilds.
- Per product: `identifier` is the collection id; `url` is the
  collection's HTML page; `api_url` is its API root; `category` says what
  kind of access it offers (feature collection, EDR time series and
  grids, both, or map layer), derived from `itemType`, `data_queries` and
  the map link; `variables_text` lists up to 40 parameter names with the
  total; bounding box and dates come from `extent`.
- `license_slug` is `unknown`. The API document declares the MIT License,
  which covers the software; each upstream dataset has its own terms.
- No facility link is asserted: AWO is a data service, not a site.
- Example calls in `api_endpoints` are written to return metadata or a
  bounded response; an unbounded `items` or `locations` call can return a
  megabyte or more.

## Known landmarks

- 26 products, each with `url` and `api_url` under
  `https://arizonawaterobservatory-api.rtd.asu.edu/`.
- `ArizonaWaterWells` (ADWR Groundwater Site Inventory) is present as a
  feature collection with time series, spanning 1902 to 2025.
- `ASU_LCRB_GRACE` carries the dates 2003-10-01 to 2023-09-01.
- `snotel-edr` and `rise-edr` list more than 100 parameters each and
  their `variables_text` is truncated with the total stated.
