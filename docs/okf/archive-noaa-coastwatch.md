---
type: Data Archive
title: "NOAA CoastWatch / OceanWatch"
description: "NOAA / NESDIS / STAR — repository holding long-term observatory records."
resource: "https://coastwatch.noaa.gov/"
tags: [repository, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Satellite-derived ocean products (SST, ocean color, altimetry, winds, sea ice). Distributed via regional CoastWatch nodes and a public ERDDAP. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://coastwatch.noaa.gov/>
- API root (`erddap`): <https://coastwatch.noaa.gov/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://coastwatch.noaa.gov/cwn/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://coastwatch.noaa.gov/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'https://coastwatch.noaa.gov/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sst&time>=2024-01-01&time<=2024-02-01' |
| data-download | GET | application/x-netcdf | <https://coastwatch.noaa.gov/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'https://coastwatch.noaa.gov/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(20):(50)][(-130):(-65)]' |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [noaa-cdr-sea-surface-temp-pathfinder-pds](https://registry.opendata.aws/noaa-cdr-pathfinder/) | us-east-1 | public-anon-egress | `—` |

# Depositing facilities

- **PMEL** Pacific Marine Environmental Laboratory (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [NOAA Geo-Polar Blended 5km Sea Surface Temperature Analysis](https://coastwatch.noaa.gov/erddap/griddap/) | netcdf | 2002-09-01–present | n/a |
