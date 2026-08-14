---
type: Data Archive
title: "USDA NASS Quick Stats"
description: "USDA National Agricultural Statistics Service — repository holding long-term observatory records."
resource: "https://quickstats.nass.usda.gov/"
tags: [repository, rest, usda-ars]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

REST API gating county/state/national agricultural statistics from Census of Ag (every 5 yr) plus annual surveys. Free api_key required (signup at https://quickstats.nass.usda.gov/api/). CSV / JSON / XML response formats; max 50,000 rows per query. retrieved_at=2026-05-06; agent=J-A-USDA [via J-A-USDA]

# Access

- Archive home: <https://quickstats.nass.usda.gov/>
- API root (`rest`): <https://quickstats.nass.usda.gov/api/> — see the [rest guide](./access-rest.md)
- API documentation: <https://quickstats.nass.usda.gov/api>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://quickstats.nass.usda.gov/api/api_GET/?key={api-key}&{filters}&format=CSV> | curl 'https://quickstats.nass.usda.gov/api/api_GET/?key=YOUR_KEY&commodity_desc=CORN&year=2022&format=CSV' |
| metadata | GET | application/json | <https://quickstats.nass.usda.gov/api/get_param_values/?key={api-key}&param={param}> | curl 'https://quickstats.nass.usda.gov/api/get_param_values/?key=YOUR_KEY&param=commodity_desc' |
| metadata | GET | application/json | <https://quickstats.nass.usda.gov/api/get_counts/?key={api-key}&{filters}> | curl 'https://quickstats.nass.usda.gov/api/get_counts/?key=YOUR_KEY&commodity_desc=CORN&year=2022' |

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [USDA Census of Agriculture county-level commodity statistics](https://quickstats.nass.usda.gov/) | csv | 1997-01-01–present | n/a |
| [USDA NASS Cropland Data Layer (CDL) annual classified raster](https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php) | geotiff | 1997-01-01–present | n/a |
