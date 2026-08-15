---
type: Data Archive
title: "U.S. IOOS Data Management and Cyberinfrastructure (DMAC) ERDDAP"
description: "NOAA / U.S. IOOS Program Office — erddap holding long-term observatory records."
resource: "https://erddap.ioos.us/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Cross-RA federation ERDDAP harvested by IOOS Catalog. Aggregates RA-hosted datasets via tabledap/griddap. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://erddap.ioos.us/erddap/>
- API root (`erddap`): <https://erddap.ioos.us/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://erddap.ioos.us/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/x-netcdf | <https://coastwatch.pfeg.noaa.gov/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -g -O 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.nc?analysed_sst[(2024-01-01T09:00:00Z):1:(2024-01-02T09:00:00Z)][(32):(33)][(-120):(-119)]' |
| data-download | GET | text/csv | <https://gliders.ioos.us/erddap/tabledap/{datasetID}.csv?{vars}&time%3E={start}&time%3C={end}> | curl 'https://gliders.ioos.us/erddap/tabledap/ru32-20190102T1317.csv?time,latitude,longitude,depth,temperature&time%3E=2019-01-02&time%3C=2019-01-04' |
| listing | GET | application/json | <https://erddap.ioos.us/erddap/info/index.json?page=1&itemsPerPage=10000> | curl 'https://erddap.ioos.us/erddap/info/index.json?page=1&itemsPerPage=10000' |

# Depositing facilities

- **IOOS** U.S. Integrated Ocean Observing System Program Office (primary)
- **CARICOOS** Caribbean Coastal Ocean Observing System (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [IOOS National Glider Data Assembly Center (DAC) Aggregated Trajectories](https://erddap.ioos.us/erddap/tabledap/) | csv | 2005-01-01–present | n/a |
