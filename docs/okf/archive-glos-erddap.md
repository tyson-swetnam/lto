---
type: Data Archive
title: "GLOS ERDDAP"
description: "Great Lakes Observing System — erddap holding long-term observatory records."
resource: "http://tds.glos.us/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Great Lakes RA ERDDAP; Seagull buoys, lake ice, lake-circulation models. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://tds.glos.us/erddap/>
- API root (`erddap`): <http://tds.glos.us/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://tds.glos.us/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <http://tds.glos.us/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://tds.glos.us/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sea_water_temperature&time>=2024-01-01&time<=2024-02-01' |
| data-download | GET | application/x-netcdf | <http://tds.glos.us/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'http://tds.glos.us/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(41):(49)][(-92):(-76)]' |

# Depositing facilities

- **GLERL** NOAA Great Lakes Environmental Research Laboratory (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [GLERL Real-time Coastal Forecasting System (GLCFS) Lake Erie Currents](http://tds.glos.us/erddap/) | netcdf | — | n/a |
