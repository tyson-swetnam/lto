---
type: Data Archive
title: "Water Quality Portal"
description: "USGS / EPA / NWQMC — repository holding long-term observatory records."
resource: "https://www.waterqualitydata.us/"
tags: [repository, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Joint USGS NWIS + EPA STORET + USDA STEWARDS surface-water-quality service; WQX 3.0 schema. CSV, TSV, XML, GeoJSON output; per-station, per-result, per-activity endpoints. retrieved_at=2026-05-06; agent=J-A-USGS [via J-A-USGS]

# Access

- Archive home: <https://www.waterqualitydata.us/>
- API root (`rest`): <https://www.waterqualitydata.us/data/> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.waterqualitydata.us/webservices_documentation/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://www.waterqualitydata.us/data/Result/search?siteid=USGS-{site_no}&mimeType=csv&zip=no> | curl 'https://www.waterqualitydata.us/data/Result/search?siteid=USGS-01400500&mimeType=csv&zip=no' |
| search | GET | text/csv | <https://www.waterqualitydata.us/data/Station/search?bBox={west},{south},{east},{north}&mimeType=csv> | curl 'https://www.waterqualitydata.us/data/Station/search?bBox=-72.1,44.4,-72.0,44.5&mimeType=csv' |

# Depositing facilities

- **NWIS-01400500** USGS Gauge 01400500 — Raritan River at Manville NJ (secondary)
- **NWIS-11447650** USGS Gauge 11447650 — Sacramento River at Freeport CA (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Water Quality Portal — surface- and ground-water results (WQX 3.0)](https://www.waterqualitydata.us/data/Result/search?mimeType=csv&zip=yes) | csv | 1899-01-01–present | n/a |
