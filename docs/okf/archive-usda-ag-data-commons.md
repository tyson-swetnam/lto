---
type: Data Archive
title: "USDA Ag Data Commons"
description: "USDA Agricultural Research Service / National Agricultural Library — repository holding long-term observatory records."
resource: "https://agdatacommons.nal.usda.gov/"
tags: [repository, ckan, usda-ars]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

CKAN-based federal repository for USDA-funded research data. DOIs minted under 10.15482/USDA.ADC/<numeric-id>. Hosts ARS, NIFA, NRCS, FS, and ERS datasets including LTAR per-site collections. retrieved_at=2026-05-06; agent=J-A-USDA [via J-A-USDA]

# Access

- Archive home: <https://agdatacommons.nal.usda.gov/>
- API root (`ckan`): <https://api.figshare.com/v2> — see the [ckan guide](./access-ckan.md)
- API documentation: <https://docs.figshare.com/>
- DOIs minted here start with `10.15482`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| metadata | GET | application/json | <https://api.figshare.com/v2/articles/{article_id}> | curl 'https://api.figshare.com/v2/articles/24663366' |
| search | POST | application/json | <https://api.figshare.com/v2/articles/search> | curl -X POST -H 'Content-Type: application/json' -d '{"search_for":"Walnut Gulch Experimental Watershed","page_size":2}' https://api.figshare.com/v2/articles/search |

# Depositing facilities

- **EOARC** Eastern Oregon Agricultural Research Center (primary)
- **FKLRRL** Fort Keogh Livestock and Range Research Laboratory (primary)
- **JER** Jornada Experimental Range LTAR (primary)
- **USSES** U.S. Sheep Experiment Station (primary)
- **USDA-ARS-EL-RENO** USDA-ARS Grazinglands Research Laboratory (El Reno) (primary)
- **USDA-ARS-AK** USDA-ARS Subarctic Agricultural Research Unit (Fairbanks) (primary)
- **KLEMME-RRS** Marvin Klemme Range Research Station (secondary)
