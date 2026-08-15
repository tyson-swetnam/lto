---
type: Data Archive
title: "NOAA National Data Buoy Center"
description: "NOAA / NWS — repository holding long-term observatory records."
resource: "https://www.ndbc.noaa.gov/"
tags: [repository, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Realtime + historical moored buoy and C-MAN station observations (wind, waves, SST, met). CSV via /data/realtime2/ and /data/historical/. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://www.ndbc.noaa.gov/>
- API root (`rest`): <https://www.ndbc.noaa.gov/data/> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.ndbc.noaa.gov/rsa.shtml>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/plain | <https://www.ndbc.noaa.gov/data/realtime2/{station}.txt> | curl https://www.ndbc.noaa.gov/data/realtime2/41008.txt |
| data-download | GET | application/gzip | <https://www.ndbc.noaa.gov/data/historical/stdmet/{station}h{year}.txt.gz> | curl -O https://www.ndbc.noaa.gov/data/historical/stdmet/41008h2023.txt.gz |

# Depositing facilities

- **NDBC** National Data Buoy Center (primary)

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [NDBC Historical Standard Meteorological (annual)](https://www.ndbc.noaa.gov/data/historical/stdmet/) | csv | 1970-01-01–present | n/a |
| [NDBC Standard Meteorological Real-Time Observations (all stations)](https://www.ndbc.noaa.gov/data/realtime2/) | csv | — | n/a |
