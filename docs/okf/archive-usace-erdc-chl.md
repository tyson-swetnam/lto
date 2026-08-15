---
type: Data Archive
title: "USACE ERDC Coastal and Hydraulics Laboratory Data Server"
description: "US Army Corps of Engineers / Engineer Research and Development Center — lab-archive holding long-term observatory records."
resource: "https://chl.erdc.dren.mil/"
tags: [lab-archive, thredds, public-domain-us]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

ERDC-CHL hosts the Coastal Inlets Research Program (CIRP), Regional Sediment Management (RSM), USACE National Coastal Mapping Program (JALBTCX) and the Coastal Hazards System (CHS) probabilistic storm response database. retrieved_at=2026-05-06; agent=K-USACE-NRL-NASA [via K-USACE-NRL-NASA]

# Access

- Archive home: <https://chl.erdc.dren.mil/>
- API root (`thredds`): <https://chldata.erdc.dren.mil/thredds/catalog.html> — see the [thredds guide](./access-thredds.md)
- API documentation: <https://chl.erdc.dren.mil/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/json | <https://chs.erdc.dren.mil/api/{study}/{station}/{return_period}> | curl 'https://chs.erdc.dren.mil/' (interactive viewer; programmatic API documented inside CHS portal) |

# Depositing facilities

- **ERDC-CHL** USACE ERDC Coastal and Hydraulics Laboratory (primary)
- **FRF** USACE Field Research Facility (secondary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Coastal Hazards System (CHS) Probabilistic Coastal Storm Hazards Database](https://chs.erdc.dren.mil/) | netcdf | 2015-01-01–present | n/a |
