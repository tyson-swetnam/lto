---
type: Access Method
title: DataONE / EDI
description: Resolving and downloading packages from DataONE member nodes, including the Environmental Data Initiative.
tags: [dataone, edi, pasta, eml, doi]
generated: { by: "claude-opus-5/lto-okf", at: 2026-08-14T03:58:00Z }
status: stable
---

DataONE federates repositories ("member nodes") behind one REST API;
the Environmental Data Initiative (EDI) — home of most LTER data — is
both a member node and its own PASTA API.

# DataONE (federation-wide)

```bash
# Search across all member nodes (Solr syntax)
curl 'https://cn.dataone.org/cn/v2/query/solr/?q=title:jornada+AND+formatType:METADATA&fl=identifier,title,datasource&wt=json'
# Resolve any identifier (DOI or PID) to download locations
curl -L 'https://cn.dataone.org/cn/v2/resolve/<PID>'
# Fetch the object itself from a member node
curl -L 'https://cn.dataone.org/cn/v2/object/<PID>' -o data.bin
```

# EDI / PASTA (LTER packages)

Package identity is `scope/identifier/revision`, e.g.
`knb-lter-jrn/210548103/76`:

```bash
# Newest revision number
curl 'https://pasta.lternet.edu/package/eml/knb-lter-jrn/210548103'
# EML metadata document
curl 'https://pasta.lternet.edu/package/metadata/eml/knb-lter-jrn/210548103/76'
# List data entities, then download one
curl 'https://pasta.lternet.edu/package/data/eml/knb-lter-jrn/210548103/76'
curl -L -o entity.csv 'https://pasta.lternet.edu/package/data/eml/knb-lter-jrn/210548103/76/<entityId>'
```

```python
# The EDI-maintained client wraps all of the above
# pip install ediutilities  — or use requests as below
import requests
pkg = "knb-lter-jrn/210548103"
rev = requests.get(f"https://pasta.lternet.edu/package/eml/{pkg}").text.split()[-1]
entities = requests.get(
    f"https://pasta.lternet.edu/package/data/eml/{pkg}/{rev}").text.splitlines()
```

DOIs minted by EDI resolve through DataONE, so `doi.org` links on the
[Data tab](../index.md) land on a package page whose "Download" links
are the PASTA URLs above.
