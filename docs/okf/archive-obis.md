---
type: Data Archive
title: "Ocean Biodiversity Information System"
description: "IOC-UNESCO / IODE — aggregator holding long-term observatory records."
resource: "https://obis.org/"
tags: [aggregator, rest, cc0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Global aggregator of marine species occurrence records (Darwin Core), >120M records from >4000 datasets. CC0 default. JSON REST API supports area/taxon/depth/time queries; bulk Darwin Core Archive ZIPs per dataset. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://obis.org/>
- API root (`rest`): <https://api.obis.org/v3> — see the [rest guide](./access-rest.md)
- API documentation: <https://api.obis.org/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| metadata | GET | application/json | <https://api.obis.org/v3/dataset/{dataset_id}> | curl https://api.obis.org/v3/dataset/5422689c-d83d-44e8-87f4-a4b0a5117181 |
| search | GET | application/json | <https://api.obis.org/v3/occurrence> | curl 'https://api.obis.org/v3/occurrence?scientificname=Dermochelys%20coriacea&size=10' |

# Depositing facilities

- **HIMB** Hawaiʻi Institute of Marine Biology (contributor)
- **Mote** Mote Marine Laboratory and Aquarium (contributor)
- **SERC** Smithsonian Environmental Research Center (contributor)
