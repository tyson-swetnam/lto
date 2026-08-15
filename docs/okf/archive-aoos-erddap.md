---
type: Data Archive
title: "AOOS ERDDAP"
description: "Alaska Ocean Observing System — erddap holding long-term observatory records."
resource: "http://erddap.aoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Alaska Region ERDDAP run by Axiom Data Science for AOOS; gliders, moorings, HF radar, models, satellite. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://erddap.aoos.org/erddap/>
- API root (`erddap`): <http://erddap.aoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://erddap.aoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/x-netcdf | <http://erddap.aoos.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -g -o out.nc 'http://erddap.aoos.org/erddap/griddap/CBHAR_WRF_SFC_1979_2009.nc?T2[(2009-01-01T00:00:00Z):1:(2009-01-01T01:00:00Z)][0:1:2][0:1:2]' |
| data-download | GET | text/csv | <http://erddap.aoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://erddap.aoos.org/erddap/tabledap/46060-west-orca-bay-36nm-south-s.csv?time%2Clatitude%2Clongitude%2Csea_surface_temperature&time%3E=2024-01-01T00%3A00%3A00Z&time%3C=2024-01-02T00%3A00%3A00Z' |

# Depositing facilities

- **AOOS** Alaska Ocean Observing System (primary)
- **NERR** Kachemak Bay NERR (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [AOOS Glider Aggregated Profile Time-Series](http://erddap.aoos.org/erddap/tabledap/) | csv | 2010-01-01–present | n/a |
