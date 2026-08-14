---
type: Data Archive
title: "PacIOOS ERDDAP"
description: "Pacific Islands Ocean Observing System — erddap holding long-term observatory records."
resource: "http://oos.soest.hawaii.edu/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Pacific Islands RA ERDDAP at U. Hawaii SOEST; HI/AS/GU/MP/MH/FM/PW coastal + open-ocean observations and models. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://oos.soest.hawaii.edu/erddap/>
- API root (`erddap`): <http://oos.soest.hawaii.edu/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://oos.soest.hawaii.edu/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <http://oos.soest.hawaii.edu/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://oos.soest.hawaii.edu/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sea_water_temperature&time>=2024-01-01&time<=2024-02-01' |
| data-download | GET | application/x-netcdf | <http://oos.soest.hawaii.edu/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'http://oos.soest.hawaii.edu/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(17):(24)][(-163):(-152)]' |

# Depositing facilities

- **PacIOOS** Pacific Islands Ocean Observing System (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [PacIOOS ROMS Hawaiian-Islands Regional Ocean Model 4km Daily Forecast](http://oos.soest.hawaii.edu/erddap/griddap/) | netcdf | 2009-01-01–present | n/a |
