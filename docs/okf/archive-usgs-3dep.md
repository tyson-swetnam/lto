---
type: Data Archive
title: "USGS 3D Elevation Program"
description: "U.S. Geological Survey, National Geospatial Program — program holding long-term observatory records."
resource: "https://www.usgs.gov/3d-elevation-program"
tags: [program, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

National lidar/IfSAR collection; 1m DEM (3DEP Elevation Source Data), Lidar Point Cloud (LPC) entwine-tiled in COPC/EPT format; distributed via The National Map and the s3://usgs-lidar-public requester-pays bucket. retrieved_at=2026-05-06; agent=J-A-USGS [via J-A-USGS]

# Access

- Archive home: <https://www.usgs.gov/3d-elevation-program>
- API root (`rest`): <https://apps.nationalmap.gov/tnmaccess/> — see the [rest guide](./access-rest.md)
- API documentation: <https://apps.nationalmap.gov/tnmaccess/#/product>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| search | GET | application/json | <https://apps.nationalmap.gov/tnmaccess/api/products?bbox={west},{south},{east},{north}&datasets=Lidar Point Cloud (LPC)&outputFormat=JSON> | curl 'https://apps.nationalmap.gov/tnmaccess/api/products?bbox=-72.1,44.4,-72.0,44.5&datasets=Lidar%20Point%20Cloud%20(LPC)&outputFormat=JSON' |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [prd-tnm](https://www.usgs.gov/the-national-map-data-delivery) | us-west-2 | public-read | `StagedProducts/Elevation/1m/Projects/` |
| s3 | [usgs-lidar-public](https://registry.opendata.aws/usgs-lidar/) | us-west-2 | requester-pays | `Projects/` |

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [USGS 3DEP 1-meter Digital Elevation Model](https://www.usgs.gov/3d-elevation-program) | geotiff | 2010-01-01–present | n/a |
