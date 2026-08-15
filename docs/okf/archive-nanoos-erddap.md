---
type: Data Archive
title: "NANOOS ERDDAP"
description: "Northwest Association of Networked Ocean Observing Systems — erddap holding long-term observatory records."
resource: "https://data.nanoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Pacific Northwest RA ERDDAP; OR/WA shelf moorings, gliders, NVS sensor network. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://data.nanoos.org/erddap/>
- API root (`erddap`): <https://data.nanoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://data.nanoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://data.nanoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'https://data.nanoos.org/erddap/tabledap/backyardbuoys_quileute_center.csv?time,latitude,longitude&time%3E=2024-09-01&time%3C=2024-09-02' |
| data-download | GET | application/x-netcdf | <https://data.nanoos.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -g -o out.nc 'https://data.nanoos.org/erddap/griddap/orca_hydro_pointwells.nc?sea_water_temperature%5B(2024-01-01):(2024-01-03)%5D%5B(0):(10)%5D' |

# Depositing facilities

- **NANOOS** Northwest Association of Networked Ocean Observing Systems (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [NANOOS NVS Sensor-Network Aggregated Time-Series (Puget Sound + WA/OR Shelf)](https://data.nanoos.org/erddap/tabledap/) | csv | 2008-01-01–present | n/a |
