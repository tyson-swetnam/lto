---
type: Data Archive
title: "CeNCOOS ERDDAP"
description: "Central and Northern California Ocean Observing System — erddap holding long-term observatory records."
resource: "http://erddap.cencoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Central/Northern California RA ERDDAP run by Axiom; gliders, moorings, models, MBARI feeds. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <http://erddap.cencoos.org/erddap/>
- API root (`erddap`): <http://erddap.cencoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <http://erddap.cencoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <http://erddap.cencoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'http://erddap.cencoos.org/erddap/tabledap/067-san-nicolas-island-ca-46219.csv?time%2Clatitude%2Clongitude%2Csea_water_temperature&time%3E=2024-01-01T00%3A00%3A00Z&time%3C=2024-01-01T06%3A00%3A00Z' |

# Depositing facilities

- **CeNCOOS** Central and Northern California Ocean Observing System (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Central California Mooring (e.g. M1) Real-Time Met + Oceanography](http://erddap.cencoos.org/erddap/tabledap/) | csv | 2002-01-01–present | n/a |
