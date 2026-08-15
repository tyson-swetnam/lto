---
type: Data Archive
title: "NERACOOS ERDDAP"
description: "Northeastern Regional Association of Coastal Ocean Observing Systems — erddap holding long-term observatory records."
resource: "https://data.neracoos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Gulf of Maine + NE shelf RA ERDDAP; UMaine/UNH/WHOI moorings (A01-N01, etc.), models, gliders. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://data.neracoos.org/erddap/>
- API root (`erddap`): <https://data.neracoos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://data.neracoos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://data.neracoos.org/erddap/tabledap/{datasetID}.csv?{vars}&time%3E={start}&time%3C={end}> | curl 'https://data.neracoos.org/erddap/tabledap/A01_ocean_001m.csv?time,latitude,longitude,temperature&time%3E=2024-01-01&time%3C=2024-01-02' |

# Depositing facilities

- **NERACOOS** Northeastern Regional Association of Coastal Ocean Observing Systems (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Gulf of Maine Mooring Buoy Real-Time Time-Series (NERACOOS A01-N01 Buoy Array)](http://www.neracoos.org/erddap/tabledap/) | csv | 2001-01-01–present | n/a |
