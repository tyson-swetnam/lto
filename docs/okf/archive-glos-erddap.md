---
type: Data Archive
title: "GLOS ERDDAP"
description: "Great Lakes Observing System — erddap holding long-term observatory records."
resource: "https://seagull-erddap.glos.org/erddap/"
tags: [erddap, erddap, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Great Lakes RA ERDDAP; Seagull buoys, lake ice, lake-circulation models. retrieved_at=2026-05-06; agent=J-A-NCEI-ERDDAP [via J-A-NCEI-ERDDAP]

# Access

- Archive home: <https://seagull-erddap.glos.org/erddap/>
- API root (`erddap`): <https://seagull-erddap.glos.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://seagull-erddap.glos.org/erddap/index.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://seagull-erddap.glos.org/erddap/tabledap/{datasetID}.csv?{vars}&time%3E={start}&time%3C={end}> | curl 'https://seagull-erddap.glos.org/erddap/tabledap/obs_71_latest.csv' |

# Depositing facilities

- **GLERL** NOAA Great Lakes Environmental Research Laboratory (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [GLERL Real-time Coastal Forecasting System (GLCFS) Lake Erie Currents](https://seagull-erddap.glos.org/erddap/) | netcdf | — | n/a |
