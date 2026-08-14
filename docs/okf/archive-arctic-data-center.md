---
type: Data Archive
title: "NSF Arctic Data Center"
description: "NSF Office of Polar Programs / NCEAS (UC Santa Barbara) — repository holding long-term observatory records."
resource: "https://arcticdata.io/"
tags: [repository, dataone, cc0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Designated NSF Arctic Sciences Section data repository (NSF policy 16-055). Also hosts NSF Antarctic deposits (cross-link with USAP). DataONE Member Node 'urn:node:ARCTIC' running Metacat. EML 2.x metadata; payloads = CSV, NetCDF, GeoTIFF. CC0 default license. retrieved_at=2026-05-06; agent=J-A-ESS-DIVE-DOE [via J-A-ESS-DIVE-DOE]

# Access

- Archive home: <https://arcticdata.io/>
- API root (`dataone`): <https://arcticdata.io/metacat/d1/mn/v2/> — see the [dataone guide](./access-dataone.md)
- API documentation: <https://arcticdata.io/submit/>
- DOIs minted here start with `10.18739`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | varies | <https://arcticdata.io/metacat/d1/mn/v2/object/{pid}> | curl -O https://arcticdata.io/metacat/d1/mn/v2/object/doi%3A10.18739%2FA2QV3C53P |
| landing | GET | text/html | <https://arcticdata.io/catalog/view/{pid}> | https://arcticdata.io/catalog/view/doi:10.18739/A2VM42X1V |
| search | GET | application/xml | <https://arcticdata.io/metacat/d1/mn/v2/query/solr/?q={query}&fl=identifier,title,origin,pubDate,beginDate,endDate&rows=100> | curl 'https://arcticdata.io/metacat/d1/mn/v2/query/solr/?q=keywords%3Apermafrost&rows=20&fl=identifier,title,pubDate' |

# Depositing facilities

- **IMN** Imnavait Creek Tussock-Tundra Watershed (primary)
- **ATQ** Atqasuk CALM and AmeriFlux Site (secondary)
- **TFS** Toolik Field Station (secondary)
