---
type: Data Archive
title: "USDA Ag Data Commons"
description: "USDA Agricultural Research Service / National Agricultural Library — repository holding long-term observatory records."
resource: "https://data.nal.usda.gov/"
tags: [repository, ckan, usda-ars]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

CKAN-based federal repository for USDA-funded research data. DOIs minted under 10.15482/USDA.ADC/<numeric-id>. Hosts ARS, NIFA, NRCS, FS, and ERS datasets including LTAR per-site collections. retrieved_at=2026-05-06; agent=J-A-USDA [via J-A-USDA]

# Access

- Archive home: <https://data.nal.usda.gov/>
- API root (`ckan`): <https://data.nal.usda.gov/api/3/> — see the [ckan guide](./access-ckan.md)
- API documentation: <https://data.nal.usda.gov/about-ag-data-commons-api>
- DOIs minted here start with `10.15482`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| listing | GET | application/json | <https://data.nal.usda.gov/api/3/action/organization_list> | curl 'https://data.nal.usda.gov/api/3/action/organization_list?all_fields=true&limit=200' |
| listing | GET | application/json | <https://data.nal.usda.gov/api/3/action/group_list> | curl 'https://data.nal.usda.gov/api/3/action/group_list?all_fields=true' |
| metadata | GET | application/json | <https://data.nal.usda.gov/api/3/action/package_show?id={dataset-id}> | curl 'https://data.nal.usda.gov/api/3/action/package_show?id=walnut-gulch-experimental-watershed' |
| search | GET | application/json | <https://data.nal.usda.gov/api/3/action/package_search?q={query}&rows={rows}> | curl 'https://data.nal.usda.gov/api/3/action/package_search?q=walnut+gulch&rows=20' |

# Depositing facilities

- **EOARC** Eastern Oregon Agricultural Research Center (primary)
- **FKLRRL** Fort Keogh Livestock and Range Research Laboratory (primary)
- **JER** Jornada Experimental Range LTAR (primary)
- **USSES** U.S. Sheep Experiment Station (primary)
- **USDA-ARS-EL-RENO** USDA-ARS Grazinglands Research Laboratory (El Reno) (primary)
- **USDA-ARS-AK** USDA-ARS Subarctic Agricultural Research Unit (Fairbanks) (primary)
- **KLEMME-RRS** Marvin Klemme Range Research Station (secondary)
