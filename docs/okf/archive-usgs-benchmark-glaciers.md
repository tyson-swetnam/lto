---
type: Data Archive
title: "USGS Benchmark Glacier Project Data Releases"
description: "USGS Alaska Science Center — program holding long-term observatory records."
resource: "https://www.usgs.gov/data/usgs-benchmark-glacier-mass-balance-and-project-data"
tags: [program, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Five long-term reference glaciers (Wolverine, Gulkana, South Cascade, Sperry, Lemon Creek). Per-glacier annual mass-balance data releases on USGS ScienceBase. Formats: CSV + NetCDF + GeoTIFF DEMs. retrieved_at=2026-05-06; agent=J-A-NSIDC-CRY [via J-A-NSIDC-CRY]

# Access

- Archive home: <https://www.usgs.gov/data/usgs-benchmark-glacier-mass-balance-and-project-data>
- API root (`rest`): <https://www.sciencebase.gov/catalog/items> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.sciencebase.gov/catalog/jsonapi>
- DOIs minted here start with `10.5066`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| search | GET | application/json | <https://www.sciencebase.gov/catalog/items?q={query}&format=json> | curl 'https://www.sciencebase.gov/catalog/items?q=benchmark+glacier+mass+balance&format=json&max=100' |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| https | [www.sciencebase.gov](https://www.sciencebase.gov/catalog/jsonapi) | us-east-2 | public-read | `catalog/file/get/` |

# Depositing facilities

- **GLK** Gulkana Glacier (primary)
- **LCG** Lemon Creek Glacier (primary)
- **SCG** South Cascade Glacier (primary)
- **SPG** Sperry Glacier (primary)
- **WLV** Wolverine Glacier (primary)

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Geodetic and Glaciological Mass Balance of Lemon Creek Glacier, Alaska](https://doi.org/10.5066/F7M043G7) | csv | 1953-01-01–present | n/a |
| [Sperry Glacier Mass Balance and Surface Topography, Glacier National Park](https://www.sciencebase.gov/catalog/items?q=sperry+glacier) | csv | 2005-01-01–present | n/a |
