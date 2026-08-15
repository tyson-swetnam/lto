---
type: Data Archive
title: "SCCOOS ERDDAP"
description: "Southern California Coastal Ocean Observing System — erddap holding long-term observatory records."
resource: "http://erddap.sccoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Southern California RA ERDDAP; SCCOOS automated shore stations, HF radar, HABs. Hosted by Scripps. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://erddap.sccoos.org/erddap/>
- API root (`erddap`): <http://erddap.sccoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://erddap.sccoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <http://erddap.sccoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://erddap.sccoos.org/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sea_water_temperature&time>=2024-01-01&time<=2024-02-01' |
| data-download | GET | application/x-netcdf | <http://erddap.sccoos.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'http://erddap.sccoos.org/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(32):(35)][(-120):(-117)]' |

# Depositing facilities

- **SCCOOS** Southern California Coastal Ocean Observing System (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [SCCOOS Automated Shore Station Temperature, Salinity, Chlorophyll](http://erddap.sccoos.org/erddap/tabledap/) | csv | 2005-01-01–present | n/a |
