---
type: Access Method
title: CKAN & OAI-PMH portals
description: Querying CKAN-backed data portals and OAI-PMH metadata providers in the catalogue.
tags: [ckan, oai-pmh, portal, metadata]
generated: { by: "claude-opus-5/lto-okf", at: 2026-08-14T03:58:00Z }
status: stable
---

# CKAN portals

CKAN sites (e.g. agency data portals) share one API under `/api/3/`:

```bash
# Full-text search over datasets
curl '<base>/api/3/action/package_search?q=streamflow&rows=20'
# Everything about one dataset, including its downloadable resources
curl '<base>/api/3/action/package_show?id=<dataset-name>'
# → result.resources[].url are the direct download links
```

```python
import requests
r = requests.get("<base>/api/3/action/package_search",
                 params={"q": "long-term ecological", "rows": 50}, timeout=60)
for pkg in r.json()["result"]["results"]:
    for res in pkg["resources"]:
        print(pkg["name"], res["format"], res["url"])
```

Facet counts (`facet.field=["organization","res_format"]`) make CKAN
portals easy to inventory before downloading anything.

> **This catalogue currently has no live CKAN portal.** Both archives
> that used one (Ag Data Commons, and LTAR through it) migrated to
> Figshare in the `data.nal.usda.gov` shutdown — their pages now
> document the Figshare v2 API (`POST
> https://api.figshare.com/v2/articles/search`). The grammar above is
> kept because it is correct for any CKAN you meet elsewhere (verified
> against a live external CKAN), and archives do move.

# OAI-PMH providers

OAI-PMH serves *metadata records*, not data files — use it to harvest
an archive's inventory, then follow identifiers to the data:

```bash
# The OAI base path depends on the repository software. DSpace 7+
# (e.g. WHOAS) serves it under /server/ — the old /oai and /oai/request
# forms return the Angular UI with a 404:
curl '<base>/server/oai/request?verb=Identify'
curl '<base>/server/oai/request?verb=ListMetadataFormats'
curl '<base>/server/oai/request?verb=ListRecords&metadataPrefix=oai_dc&from=2024-01-01'
# Continue with the resumptionToken from each response:
curl '<base>/server/oai/request?verb=ListRecords&resumptionToken=<token>'
```

Verified against WHOAS (darchive.mblwhoilibrary.org): `Identify` names
the repository, `ListRecords` pages 100 records with a
`resumptionToken` carrying `completeListSize`.

Records usually carry a DOI or landing-page URL in `dc:identifier`;
resolve those like any [DOI link](./access-dataone.md).
