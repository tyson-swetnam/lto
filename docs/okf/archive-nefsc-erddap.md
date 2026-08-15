---
type: Data Archive
title: "NEFSC ERDDAP"
description: "NOAA / Northeast Fisheries Science Center — erddap holding long-term observatory records."
resource: "https://comet.nefsc.noaa.gov/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

ERDDAP server hosting NEFSC oceanographic and ecosystem-monitoring time series (ECOMON, hydrographic, CTD). retrieved_at=2026-05-06; agent=K-NMFS [via K-NMFS]

# Access

- Archive home: <https://comet.nefsc.noaa.gov/erddap/>
- API root (`erddap`): <https://comet.nefsc.noaa.gov/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://comet.nefsc.noaa.gov/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-access | GET | text/csv | <https://comet.nefsc.noaa.gov/erddap/tabledap/{datasetID}.{fileType}?{query}> | curl 'https://comet.nefsc.noaa.gov/erddap/tabledap/ocdbs_v_erddap1.csv?cruise_id&distinct()' |
| metadata | GET | application/json | <https://comet.nefsc.noaa.gov/erddap/info/index.{fileType}> | curl 'https://comet.nefsc.noaa.gov/erddap/info/index.json' |
