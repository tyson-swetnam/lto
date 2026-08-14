---
type: Data Archive
title: "MARACOOS ERDDAP"
description: "Mid-Atlantic Regional Association Coastal Ocean Observing System — erddap holding long-term observatory records."
resource: "http://maracoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Mid-Atlantic Bight RA ERDDAP; Rutgers gliders, HF radar, NY-NJ-DE-MD-VA shelf data. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://maracoos.org/erddap/>
- API root (`erddap`): <http://maracoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://maracoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <http://maracoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://maracoos.org/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sea_water_temperature&time>=2024-01-01&time<=2024-02-01' |
| data-download | GET | application/x-netcdf | <http://maracoos.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'http://maracoos.org/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(35):(42)][(-76):(-69)]' |

# Depositing facilities

- **MARACOOS** Mid-Atlantic Regional Association Coastal Ocean Observing System (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Mid-Atlantic Bight HF Radar 6km Hourly Surface Currents](http://maracoos.org/erddap/griddap/) | netcdf | 2007-01-01–present | n/a |
