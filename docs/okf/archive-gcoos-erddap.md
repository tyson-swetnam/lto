---
type: Data Archive
title: "GCOOS ERDDAP"
description: "Gulf of Mexico Coastal Ocean Observing System — erddap holding long-term observatory records."
resource: "http://erddap.gcoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Gulf of Mexico RA ERDDAP; gliders, moored buoys, HABs, HF radar. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://erddap.gcoos.org/erddap/>
- API root (`erddap`): <http://erddap.gcoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://erddap.gcoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <http://erddap.gcoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://erddap.gcoos.org/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sea_water_temperature&time>=2024-01-01&time<=2024-02-01' |
| data-download | GET | application/x-netcdf | <http://erddap.gcoos.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'http://erddap.gcoos.org/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(18):(31)][(-98):(-80)]' |

# Depositing facilities

- **GCOOS** Gulf of Mexico Coastal Ocean Observing System (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Gulf of Mexico Hypoxia Watch Bottom Dissolved Oxygen Time-Series](http://erddap.gcoos.org/erddap/tabledap/) | csv | 2009-01-01–present | n/a |
