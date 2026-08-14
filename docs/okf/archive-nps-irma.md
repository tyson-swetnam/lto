---
type: Data Archive
title: "NPS IRMA Datastore"
description: "U.S. National Park Service / Integrated Resource Management Applications — data-portal holding long-term observatory records."
resource: "https://irma.nps.gov/DataStore/"
tags: [data-portal, rest, public-domain-us]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

NPS IRMA (Integrated Resource Management Applications) Data Store; canonical NPS publication and dataset repository. Hosts NPS Inventory & Monitoring (NPS-IM) reports, vital signs data, GIS layers, water-quality, vegetation, wildlife, and resource briefs. Each item is a 'Reference' identified by a 7-digit numeric ReferenceId; addressable as https://irma.nps.gov/DataStore/Reference/Profile/<id>. Per-park browse via 4-letter unit code. License = public-domain-us (US Government work). retrieved_at=2026-05-06; agent=K-NPS-COASTAL [via K-NPS-COASTAL]

# Access

- Archive home: <https://irma.nps.gov/DataStore/>
- API root (`rest`): <https://irmaservices.nps.gov/datastore/v6/rest/> — see the [rest guide](./access-rest.md)
- API documentation: <https://irmaservices.nps.gov/datastore/v6/rest/help>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/octet-stream | <https://irmaservices.nps.gov/datastore/v6/rest/DownloadFile/{digital_file_id}> | curl -O 'https://irmaservices.nps.gov/datastore/v6/rest/DownloadFile/123456' |
| metadata | GET | text/html | <https://irma.nps.gov/DataStore/Reference/Profile/{reference_id}> | curl 'https://irma.nps.gov/DataStore/Reference/Profile/2270195' |
| metadata | GET | application/json | <https://irmaservices.nps.gov/datastore/v6/rest/Reference/{reference_id}> | curl 'https://irmaservices.nps.gov/datastore/v6/rest/Reference/2300000' |
| search | GET | text/html | <https://irma.nps.gov/DataStore/Search/Quick/{unit_code_or_keyword}> | curl 'https://irma.nps.gov/DataStore/Search/Quick/CACO' |
| search | GET | text/html | <https://irma.nps.gov/DataStore/Search/Quick?SearchType=Q&Query={unit_code}> | curl 'https://irma.nps.gov/DataStore/Search/Quick?SearchType=Q&Query=CACO' |
| search | GET | application/json | <https://irmaservices.nps.gov/datastore/v6/rest/AdvancedSearch/Composite> | curl 'https://irmaservices.nps.gov/datastore/v6/rest/AdvancedSearch/Composite?units=CACO&top=50' |

# Depositing facilities

- **CACO** Cape Cod National Seashore (primary)
- **CAHA** Cape Hatteras National Seashore (primary)
- **DENALI-NPS-LTM** Denali National Park Long-Term Ecological Monitoring (Central Alaska Network, NPS-IM) (primary)
- **GRSM-NP** Great Smoky Mountains National Park (Twin Creeks Science and Education Center) (primary)
- **PORE** Point Reyes National Seashore (primary)
- **YNP-LT** Yellowstone National Park — Long-Term Ecological Monitoring (primary)

# Data products

7 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Great Lakes Network — Inland Lake Water Quality Monitoring (APIS, SLBE, PIRO, INDU)](https://irma.nps.gov/DataStore/Search/Quick/GLKN%20water%20quality) | csv | 2006-01-01–present | n/a |
| [NCBN Estuarine Water Quality Monitoring — Pleasant Bay / Nauset Marsh](https://irma.nps.gov/DataStore/Search/Quick?SearchType=Q&Query=CACO+water+quality) | csv | 2003-01-01–present | n/a |
| [NCBN Salt Marsh Vegetation Monitoring — Cape Cod National Seashore](https://irma.nps.gov/DataStore/Search/Quick?SearchType=Q&Query=CACO+salt+marsh+vegetation) | csv | 2002-01-01–present | n/a |
| [Northeast Coastal & Barrier Network — Estuarine Nutrient Enrichment & Eutrophication Monitoring (CACO)](https://irma.nps.gov/DataStore/Search/Quick/CACO%20estuarine%20nutrient) | csv | 2003-01-01–present | n/a |
| [Northeast Temperate Network — Lakes & Ponds Water Quality Monitoring (Acadia)](https://irma.nps.gov/DataStore/Search/Quick/ACAD%20water%20quality) | csv | 2005-01-01–present | n/a |
| [SFAN Coastal Salmonid Monitoring — Olema, Lagunitas, Pine Gulch Creek](https://irma.nps.gov/DataStore/Search/Quick?SearchType=Q&Query=PORE+salmonid+coho) | csv | 1997-01-01–present | n/a |
| [SFAN Rocky Intertidal Community Monitoring — Point Reyes National Seashore](https://irma.nps.gov/DataStore/Search/Quick?SearchType=Q&Query=PORE+rocky+intertidal) | csv | 2005-01-01–present | n/a |
