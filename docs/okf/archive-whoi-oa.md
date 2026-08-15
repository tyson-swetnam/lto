---
type: Data Archive
title: "WHOI Open Access Server"
description: "Woods Hole Oceanographic Institution Library — repository holding long-term observatory records."
resource: "https://darchive.mblwhoilibrary.org/"
tags: [repository, oai-pmh, unknown]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

WHOI institutional repository (handle prefix 1912) — theses, technical reports, datasets, preprints. Hosted via the MBL/WHOI Library DSpace. Licenses vary per item. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://darchive.mblwhoilibrary.org/>
- API root (`oai-pmh`): <https://darchive.mblwhoilibrary.org/> — see the [oai-pmh guide](./access-ckan.md)
- API documentation: <https://darchive.mblwhoilibrary.org/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/html | <https://hdl.handle.net/1912/{handle_id}> | curl -L https://hdl.handle.net/1912/20957 |
| listing | GET | application/xml | <https://darchive.mblwhoilibrary.org/server/oai/request?verb=ListRecords&metadataPrefix=oai_dc> | curl 'https://darchive.mblwhoilibrary.org/server/oai/request?verb=ListRecords&metadataPrefix=oai_dc&set=col_1912_531' |

# Depositing facilities

- **WHOI** Woods Hole Oceanographic Institution (primary)
- **MBL** Marine Biological Laboratory (host)
