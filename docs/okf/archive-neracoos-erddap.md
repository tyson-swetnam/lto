---
type: Data Archive
title: "NERACOOS ERDDAP"
description: "Northeastern Regional Association of Coastal Ocean Observing Systems — erddap holding long-term observatory records."
resource: "http://www.neracoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Gulf of Maine + NE shelf RA ERDDAP; UMaine/UNH/WHOI moorings (A01-N01, etc.), models, gliders. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://www.neracoos.org/erddap/>
- API root (`erddap`): <http://www.neracoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://www.neracoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/x-netcdf | <http://www.neracoos.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'http://www.neracoos.org/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(40):(45)][(-71):(-65)]' |
| data-download | GET | text/csv | <http://www.neracoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://www.neracoos.org/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sea_water_temperature&time>=2024-01-01&time<=2024-02-01' |

# Depositing facilities

- **NERACOOS** Northeastern Regional Association of Coastal Ocean Observing Systems (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Gulf of Maine Mooring Buoy Real-Time Time-Series (NERACOOS A01-N01 Buoy Array)](http://www.neracoos.org/erddap/tabledap/) | csv | 2001-01-01–present | n/a |
