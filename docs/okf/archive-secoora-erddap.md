---
type: Data Archive
title: "SECOORA ERDDAP"
description: "Southeast Coastal Ocean Observing Regional Association — erddap holding long-term observatory records."
resource: "http://erddap.secoora.org/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

SE U.S. RA ERDDAP; NC/SC/GA/FL coastal observations, gliders, HF radar, model output. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://erddap.secoora.org/>
- API root (`erddap`): <http://erddap.secoora.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://erddap.secoora.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <http://erddap.secoora.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://erddap.secoora.org/erddap/tabledap/<datasetID>.csv?time,latitude,longitude,sea_water_temperature&time>=2024-01-01&time<=2024-02-01' |
| data-download | GET | application/x-netcdf | <http://erddap.secoora.org/erddap/griddap/{datasetID}.nc?{var}[({t0}):({t1})][({lat0}):({lat1})][({lon0}):({lon1})]> | curl -O 'http://erddap.secoora.org/erddap/griddap/<datasetID>.nc?<var>[(2024-01-01):(2024-01-07)][(24):(36)][(-82):(-75)]' |

# Depositing facilities

- **SECOORA** Southeast Coastal Ocean Observing Regional Association (primary)
- Florida Keys Marine Sanctuary (secondary)
- Gray's Reef Marine Sanctuary (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [SECOORA Aggregated Glider Time-Series](http://erddap.secoora.org/erddap/tabledap/) | csv | 2008-01-01–present | n/a |
