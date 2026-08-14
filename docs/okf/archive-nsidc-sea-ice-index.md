---
type: Data Archive
title: "NSIDC Sea Ice Index (G02135)"
description: "National Snow and Ice Data Center — product-suite holding long-term observatory records."
resource: "https://nsidc.org/data/g02135/"
tags: [product-suite, https-listing, nasa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Daily and monthly Arctic & Antarctic sea-ice extent and concentration; CSV time series + GeoTIFF + PNG; updated daily. Public anonymous HTTPS download (no Earthdata Login required). DOI 10.7265/N5K072F8 (v3). retrieved_at=2026-05-06; agent=J-A-NSIDC-CRY [via J-A-NSIDC-CRY]

# Access

- Archive home: <https://nsidc.org/data/g02135/>
- API root (`https-listing`): <https://noaadata.apps.nsidc.org/NOAA/G02135/>
- API documentation: <https://nsidc.org/data/g02135/versions/3/documentation>
- DOIs minted here start with `10.7265`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://noaadata.apps.nsidc.org/NOAA/G02135/{hemisphere}/daily/data/{filename}.csv> | curl -O https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/N_seaice_extent_daily_v3.0.csv |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| https | [noaadata.apps.nsidc.org](https://nsidc.org/data/g02135/versions/3/documentation) | us-west-2 | public-read | `NOAA/G02135/north/daily/data/` |

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Sea Ice Index, Version 3](https://doi.org/10.7265/N5K072F8) | geotiff | 1978-10-26–present | n/a |
