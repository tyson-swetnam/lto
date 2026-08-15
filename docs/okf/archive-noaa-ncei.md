---
type: Data Archive
title: "NOAA National Centers for Environmental Information"
description: "NOAA / NESDIS — repository holding long-term observatory records."
resource: "https://www.ncei.noaa.gov/"
tags: [repository, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Authoritative archive for NOAA atmosphere/ocean/cryosphere/coastal data. Holds legacy NODC/NCDC/NGDC. DOIs use 10.7289/V5* (pre-2018) and 10.25921/* (post-2018). retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://www.ncei.noaa.gov/>
- API root (`rest`): <https://www.ncei.noaa.gov/access/> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation>
- DOIs minted here start with `10.25921`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://www.ncei.noaa.gov/access/services/data/v1?dataset={dataset}&dataTypes={vars}&stations={station}&startDate={start}&endDate={end}&format=csv> | curl 'https://www.ncei.noaa.gov/access/services/data/v1?dataset=global-summary-of-the-day&stations=72509014739&startDate=2024-01-01&endDate=2024-12-31&format=csv' |
| metadata | GET | application/xml | <https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id={collection_id};view=xml;responseType=text/xml> | curl 'https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.nodc:0192984;view=xml;responseType=text/xml' |
| search | GET | application/json | <https://www.ncei.noaa.gov/access/services/search/v1/data?dataset={dataset}&bbox={N},{W},{S},{E}&startDate={start}&endDate={end}> | curl 'https://www.ncei.noaa.gov/access/services/search/v1/data?dataset=global-marine&bbox=45,-71,40,-65&startDate=2023-01-01&endDate=2023-12-31' |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [noaa-gefs-pds](https://registry.opendata.aws/noaa-gefs/) | us-east-1 | public-anon-egress | `gefs.20240101/00/atmos/` |
| s3 | [noaa-gfs-bdp-pds](https://registry.opendata.aws/noaa-gfs-bdp-pds/) | us-east-1 | public-anon-egress | `gfs.20240101/00/atmos/` |
| s3 | [noaa-ghcn-pds](https://registry.opendata.aws/noaa-ghcn/) | us-east-1 | public-anon-egress | `—` |
| s3 | [noaa-goes16](https://registry.opendata.aws/noaa-goes/) | us-east-1 | public-anon-egress | `ABI-L2-CMIPC/` |
| s3 | [noaa-goes17](https://registry.opendata.aws/noaa-goes/) | us-west-2 | public-anon-egress | `ABI-L2-CMIPC/` |
| s3 | [noaa-goes18](https://registry.opendata.aws/noaa-goes18/) | us-east-1 | public-anon-egress | `ABI-L2-CMIPC/` |
| s3 | [noaa-himawari8](https://registry.opendata.aws/noaa-himawari/) | us-east-1 | public-anon-egress | `AHI-L1b-FLDK/` |
| s3 | [noaa-hrrr-bdp-pds](https://registry.opendata.aws/noaa-hrrr-pds/) | us-east-1 | public-anon-egress | `hrrr.20240101/conus/` |
| s3 | [noaa-isd-pds](https://registry.opendata.aws/noaa-isd/) | us-east-1 | public-anon-egress | `—` |
| s3 | [noaa-jpss](https://registry.opendata.aws/noaa-jpss/) | us-east-1 | public-anon-egress | `JPSS1/VIIRS/L1B/` |
| s3 | [noaa-nexrad-level2](https://registry.opendata.aws/noaa-nexrad/) | us-east-1 | public-anon-egress | `2024/01/01/KOKX/` |
| s3 | [noaa-rtma-pds](https://registry.opendata.aws/noaa-rtma/) | us-east-1 | public-anon-egress | `rtma2p5.20240101/` |

# Depositing facilities

- **AOML** Atlantic Oceanographic and Meteorological Laboratory (primary)
- Florida Keys Marine Sanctuary (primary)
- Gray's Reef Marine Sanctuary (primary)
- Mallows Bay-Potomac River Marine Sanctuary (primary)
- Monitor Marine Sanctuary (primary)
- **GLERL** NOAA Great Lakes Environmental Research Laboratory (primary)
- **NCEI** NOAA National Centers for Environmental Information (primary)
- **PMEL** Pacific Marine Environmental Laboratory (primary)
- Stellwagen Bank Marine Sanctuary (primary)
- **NERR** ACE Basin NERR (secondary)
- **NERR** Apalachicola NERR (secondary)
- **NERR** Chesapeake Bay Maryland NERR (secondary)
- **NERR** Chesapeake Bay Virginia NERR (secondary)
- **NERR** Delaware NERR (secondary)
- **NERR** Elkhorn Slough NERR (secondary)
- **NERR** Grand Bay NERR (secondary)
- **NERR** Great Bay NERR (secondary)
- **NERR** Guana Tolomato Matanza NERR (secondary)
- **NERR** He'eia NERR (secondary)
- **NERR** Hudson River NERR (secondary)
- **NERR** Jacques Cousteau NERR (secondary)
- **NERR** Jobos Bay NERR (secondary)
- **NERR** Kachemak Bay NERR (secondary)
- **NERR** Lake Superior NERR (secondary)
- **NERR** Mission Aransas NERR (secondary)
- **NERR** Narragansett Bay NERR (secondary)
- **NERRS** National Estuarine Research Reserve System (secondary)
- **NERR** North Carolina NERR (secondary)
- **NERR** North Inlet-Winyah Bay NERR (secondary)
- **NERR** Old Woman Creek NERR (secondary)
- **NERR** Padilla Bay NERR (secondary)
- **NERR** Rookery Bay NERR (secondary)
- **NERR** San Francisco Bay NERR (secondary)
- **NERR** Sapelo Island NERR (secondary)
- **NERR** South Slough NERR (secondary)
- **NERR** Tijuana River NERR (secondary)
- **NERR** Waquoit Bay NERR (secondary)
- **NERR** Weeks Bay NERR (secondary)
- **NERR** Wells NERR (secondary)

# Data products

9 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Florida Current Cable Transport — Daily](https://www.aoml.noaa.gov/phod/floridacurrent/) | csv | 1982-04-01–present | n/a |
| [Global Drifter Program (GDP) Hourly Drifter Dataset](https://doi.org/10.25921/x46c-3620) | netcdf | 1979-02-15–present | n/a |
| [Great Lakes Surface Environmental Analysis (GLSEA) Daily Lake Surface Temperature](https://coastwatch.glerl.noaa.gov/glsea/) | netcdf | 1995-01-01–present | n/a |
| [NERRS System-Wide Monitoring Program (SWMP) Water-Quality Time-Series](https://cdmo.baruch.sc.edu/aqs/) | csv | 1995-01-01–present | n/a |
| [NOAA Coral Reef Watch Daily 5km Satellite Sea Surface Temperature Anomaly](https://doi.org/10.25921/2v6w-mx07) | netcdf | 1985-01-01–present | n/a |
| [NOAA Optimum Interpolation 1/4 Degree Daily Sea Surface Temperature (OISST) Analysis, Version 2.1](https://doi.org/10.25921/RE9P-PT57) | netcdf | 1981-09-01–present | n/a |
| [Surface Underway CO2 Data — SOCAT v2024](https://doi.org/10.25921/r7xa-bt92) | netcdf | 1957-01-01–2023-12-31 | n/a |
| [TAO/TRITON Tropical Atmosphere Ocean Project Mooring Array](https://www.pmel.noaa.gov/tao/drupal/disdel/) | netcdf | 1985-01-01–present | n/a |
| [World Ocean Database (WOD)](https://doi.org/10.7289/V5JQ0XZ4) | netcdf | 1772-01-01–present | n/a |
