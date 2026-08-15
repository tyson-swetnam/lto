---
type: Data Archive
title: "MARACOOS ERDDAP"
description: "Mid-Atlantic Regional Association Coastal Ocean Observing System — erddap holding long-term observatory records."
resource: "https://erddap.maracoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Mid-Atlantic Bight RA ERDDAP; Rutgers gliders, HF radar, NY-NJ-DE-MD-VA shelf data. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://erddap.maracoos.org/erddap/>
- API root (`erddap`): <https://erddap.maracoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://erddap.maracoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://erddap.maracoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time%3E={start}&time%3C={end}> | curl 'https://erddap.maracoos.org/erddap/tabledap/allDatasets.csv?datasetID,title' |
| data-download | GET | application/x-netcdf | <https://erddap.maracoos.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -g -O 'https://erddap.maracoos.org/erddap/griddap/MODIS_AQUA_1_day.nc?sst[(2022-09-01):(2022-09-01)][(35):(35.2)][(-75):(-74.8)]' |

# Depositing facilities

- **MARACOOS** Mid-Atlantic Regional Association Coastal Ocean Observing System (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Mid-Atlantic Bight HF Radar 6km Hourly Surface Currents](https://erddap.maracoos.org/erddap/) | netcdf | 2007-01-01–present | n/a |
