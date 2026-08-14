---
type: Data Archive
title: "KNB — Knowledge Network for Biocomplexity"
description: "NCEAS (UC Santa Barbara) / DataONE — repository holding long-term observatory records."
resource: "https://knb.ecoinformatics.org/"
tags: [repository, dataone, cc0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

International ecology/biocomplexity repository run by NCEAS; the original DataONE Member Node ('urn:node:KNB'). Metacat backend, EML metadata, mixed payloads. DOIs 10.5063/<6-7 char checksum>. CC0 default. Used as overflow / non-LTER ecology archive complementary to EDI. retrieved_at=2026-05-06; agent=J-A-ESS-DIVE-DOE [via J-A-ESS-DIVE-DOE]

# Access

- Archive home: <https://knb.ecoinformatics.org/>
- API root (`dataone`): <https://knb.ecoinformatics.org/knb/d1/mn/v2/> — see the [dataone guide](./access-dataone.md)
- API documentation: <https://knb.ecoinformatics.org/api>
- DOIs minted here start with `10.5063`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/octet-stream | <https://knb.ecoinformatics.org/knb/d1/mn/v2/object/{pid}> | curl -L 'https://knb.ecoinformatics.org/knb/d1/mn/v2/object/doi%3A10.5063%2FF1XW4H1F' |
| landing | GET | text/html | <https://knb.ecoinformatics.org/view/{pid}> | https://knb.ecoinformatics.org/view/doi:10.5063/F1XW4H1F |
| search | GET | application/xml | <https://knb.ecoinformatics.org/knb/d1/mn/v2/query/solr/?q={query}&fl=identifier,title,origin,pubDate&rows=100> | curl 'https://knb.ecoinformatics.org/knb/d1/mn/v2/query/solr/?q=title%3Aforest&rows=20&fl=identifier,title' |
