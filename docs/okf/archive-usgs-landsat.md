---
type: Data Archive
title: "USGS Landsat Archive (EROS Center)"
description: "U.S. Geological Survey, Earth Resources Observation and Science Center — repository holding long-term observatory records."
resource: "https://earthexplorer.usgs.gov/"
tags: [repository, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Landsat Collection 2 Level-1 and Level-2 surface reflectance/temperature; distributed through EarthExplorer, Machine-to-Machine (M2M) API, and the s3://usgs-landsat requester-pays bucket (us-west-2). 1972-present (Landsat 1-9). retrieved_at=2026-05-06; agent=J-A-USGS [via J-A-USGS]

# Access

- Archive home: <https://earthexplorer.usgs.gov/>
- API root (`rest`): <https://m2m.cr.usgs.gov/api/api/json/stable/> — see the [rest guide](./access-rest.md)
- API documentation: <https://m2m.cr.usgs.gov/api/docs/json/>
- DOIs minted here start with `10.5066`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| search | POST | application/json | <https://m2m.cr.usgs.gov/api/api/json/stable/scene-search> | curl -X POST -H 'X-Auth-Token: $TOKEN' -d '{"datasetName":"landsat_ot_c2_l2","sceneFilter":{"spatialFilter":{"filterType":"mbr","lowerLeft":{"latitude":36.86,"longitude":-111.59},"upperRight":{"latitude":36.87,"longitude":-111.58}}}}' https://m2m.cr.usgs.gov/api/api/json/stable/scene-search |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [nasa-3dep-snapshot](https://registry.opendata.aws/nasa-3dep-snapshot/) | us-west-2 | public-read | `Projects/` |
| s3 | [usgs-landsat](https://registry.opendata.aws/usgs-landsat/) | us-west-2 | requester-pays | `collection02/level-2/standard/oli-tirs/` |

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Landsat Collection 2 Level-2 Surface Reflectance/Temperature](https://doi.org/10.5066/P9OGBGM6) | geotiff | 1982-07-01–present | n/a |
