---
type: Data Archive
title: "Ocean Observatories Initiative Data Explorer"
description: "NSF / Consortium for Ocean Leadership / WHOI / OSU / UW — observatory-network holding long-term observatory records."
resource: "https://dataexplorer.oceanobservatories.org/"
tags: [observatory-network, erddap, cc-by-4.0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

OOI Data Explorer (Axiom-hosted) is the canonical browse / download UI; ERDDAP and THREDDS (https://opendap.oceanobservatories.org/thredds/) serve NetCDF + CSV. Five arrays: Coastal Endurance, Coastal Pioneer (NES + MAB), Global Irminger Sea, Global Argentine Basin, Global Station Papa. Datastream IDs follow <RD-NAME>-<INST>-<DEPLOY> pattern. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://dataexplorer.oceanobservatories.org/>
- API root (`erddap`): <https://erddap.dataexplorer.oceanobservatories.org/erddap/> — see the [erddap guide](./access-erddap.md)
- API documentation: <https://oceanobservatories.org/data/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://erddap.dataexplorer.oceanobservatories.org/erddap/tabledap/{datasetID}.csv> | curl 'https://erddap.dataexplorer.oceanobservatories.org/erddap/tabledap/CE02SHSM-RID27-04-DOSTAD000.csv?time,sea_water_temperature,sea_water_practical_salinity' |
| listing | GET | text/html | <https://opendap.oceanobservatories.org/thredds/catalog/ooigoldcopy/public/catalog.html> | curl https://opendap.oceanobservatories.org/thredds/catalog/ooigoldcopy/public/catalog.xml |
| search | GET | application/json | <https://erddap.dataexplorer.oceanobservatories.org/erddap/info/index.json?page=1&itemsPerPage=1000> | curl 'https://erddap.dataexplorer.oceanobservatories.org/erddap/info/index.json?page=1&itemsPerPage=1000' |

# Depositing facilities

- **OOI** Ocean Observatories Initiative (primary)
- **AOOS** Alaska Ocean Observing System (secondary)
- **NERACOOS** Northeastern Regional Association of Coastal Ocean Observing Systems (secondary)
- **NANOOS** Northwest Association of Networked Ocean Observing Systems (secondary)
