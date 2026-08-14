---
type: Data Archive
title: "Global Biodiversity Information Facility"
description: "GBIF Secretariat (Copenhagen) — aggregator holding long-term observatory records."
resource: "https://www.gbif.org/"
tags: [aggregator, rest, cc-by-4.0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Intergovernmental biodiversity data network. Occurrence + checklist + sampling-event datasets in Darwin Core Archive. Licenses are dataset-specific: CC0, CC-BY-4.0, or CC-BY-NC-4.0. Download DOIs minted under 10.15468/dl.<id>. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://www.gbif.org/>
- API root (`rest`): <https://api.gbif.org/v1/> — see the [rest guide](./access-rest.md)
- API documentation: <https://techdocs.gbif.org/en/openapi/>
- DOIs minted here start with `10.15468`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | POST | application/json | <https://api.gbif.org/v1/occurrence/download/request> | curl -u user:pass -H 'Content-Type:application/json' -d @predicate.json https://api.gbif.org/v1/occurrence/download/request |
| metadata | GET | application/json | <https://api.gbif.org/v1/dataset/{uuid}> | curl https://api.gbif.org/v1/dataset/8a17a44a-0c54-4c6d-86cf-2b2a8d8a5b9b |
| search | GET | application/json | <https://api.gbif.org/v1/occurrence/search> | curl 'https://api.gbif.org/v1/occurrence/search?taxonKey=2476674&limit=20' |

# Depositing facilities

- **SERC** Smithsonian Environmental Research Center (contributor)
