---
type: Data Archive
title: "Biological and Chemical Oceanography Data Management Office"
description: "Woods Hole Oceanographic Institution / NSF OCE — repository holding long-term observatory records."
resource: "https://www.bco-dmo.org/"
tags: [repository, rest, cc0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

NSF-funded NSF/OCE biological + chemical oceanography data office hosted at WHOI. New DOIs minted under 10.26008/1912/<numeric-id>; legacy DOIs under 10.1575/1912/<id>. Datasets are CC0 and served as JSON/CSV via project / dataset endpoints. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://www.bco-dmo.org/>
- API root (`rest`): <https://www.bco-dmo.org/api/v1> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.bco-dmo.org/api>
- DOIs minted here start with `10.26008`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://www.bco-dmo.org/dataset/{dataset_id}/data/download> | curl -O https://www.bco-dmo.org/dataset/3358/data/download |
| listing | GET | application/json | <https://www.bco-dmo.org/api/v1/project/{project_id}> | curl https://www.bco-dmo.org/api/v1/project/2031 |
| metadata | GET | application/json | <https://www.bco-dmo.org/api/v1/dataset/{dataset_id}> | curl https://www.bco-dmo.org/api/v1/dataset/3358 |

# Depositing facilities

- **LTER** California Current LTER (primary)
- **LTER** Northeast US Margin LTER (primary)
- **LTER** Northern Gulf of Alaska LTER (primary)
- **WHOI** Woods Hole Oceanographic Institution (host)
- **LTER** Beaufort Lagoon LTER (secondary)
- **Bigelow** Bigelow Laboratory for Ocean Sciences (secondary)
- **BML** Bodega Marine Laboratory (secondary)
- **LTER** Florida Coast LTER (secondary)
- **LTER** Georgia Coast LTER (secondary)
- **URI-GSO** Graduate School of Oceanography (secondary)
- **HMSC** Hatfield Marine Science Center (secondary)
- **HIMB** Hawaiʻi Institute of Marine Biology (secondary)
- **MBARI** Monterey Bay Aquarium Research Institute (secondary)
- **LTER** Plum Island LTER (secondary)
- **RSMAES** Rosenstiel School of Marine, Atmospheric, and Earth Science (secondary)
- **SBC** Santa Barbara Coastal LTER (secondary)
- **SkIO** Skidaway Institute of Oceanography (secondary)
- **LTER** Virginia Coast LTER (secondary)
- **VIMS** Virginia Institute of Marine Science (secondary)
