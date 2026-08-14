---
type: Data Archive
title: "USACE FRF Coastal Field Data Collection (CFDC) / FRF Data Portal"
description: "US Army Corps of Engineers / ERDC-CHL Field Research Facility — data-portal holding long-term observatory records."
resource: "https://frfdataportal.erdc.dren.mil/"
tags: [data-portal, thredds, public-domain-us]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

FRF (Duck, NC) waves, currents, met, bathymetry, lidar, beach profiles since 1977. Served via THREDDS catalog at chldata.erdc.dren.mil/thredds/ and the FRF Data Portal frontend. retrieved_at=2026-05-06; agent=K-USACE-NRL-NASA [via K-USACE-NRL-NASA]

# Access

- Archive home: <https://frfdataportal.erdc.dren.mil/>
- API root (`thredds`): <https://frfdataportal.erdc.dren.mil/> — see the [thredds guide](./access-thredds.md)
- API documentation: <https://chldata.erdc.dren.mil/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| catalog | GET | application/xml | <https://chldata.erdc.dren.mil/thredds/catalog/frf/{collection}/catalog.xml> | curl 'https://chldata.erdc.dren.mil/thredds/catalog/frf/oceanography/waves/8m-array/catalog.xml' |
| data-download | GET | application/x-netcdf | <https://chldata.erdc.dren.mil/thredds/dodsC/frf/{collection}/{file}.nc> | curl 'https://chldata.erdc.dren.mil/thredds/dodsC/frf/oceanography/waves/8m-array/2024/FRF-ocean_waves_8m-array_202401.nc.dap.nc4' |

# Depositing facilities

- **FRF** USACE Field Research Facility (primary)

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [FRF 8m Array Directional Wave Spectra (Duck, NC)](https://chldata.erdc.dren.mil/thredds/catalog/frf/oceanography/waves/8m-array/catalog.html) | netcdf | 1986-01-01–present | n/a |
| [FRF Geomorphology — Surveyed Beach Profiles and Bathymetry (Duck, NC)](https://chldata.erdc.dren.mil/thredds/catalog/frf/geomorphology/elevationTransects/survey/catalog.html) | netcdf | 1981-01-01–present | n/a |
