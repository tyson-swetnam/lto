---
type: Data Archive
title: "GCOOS ERDDAP"
description: "Gulf of Mexico Coastal Ocean Observing System — erddap holding long-term observatory records."
resource: "http://erddap.gcoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
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
| data-download | GET | text/csv | <http://erddap.gcoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time>={start}&time<={end}> | curl 'https://erddap.gcoos.org/erddap/tabledap/wmo_42395.csv?time,latitude,longitude,sea_surface_temperature&time%3E=2024-01-01&time%3C=2024-01-02' |

# Depositing facilities

- **GCOOS** Gulf of Mexico Coastal Ocean Observing System (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Gulf of Mexico Hypoxia Watch Bottom Dissolved Oxygen Time-Series](http://erddap.gcoos.org/erddap/tabledap/) | csv | 2009-01-01–present | n/a |
