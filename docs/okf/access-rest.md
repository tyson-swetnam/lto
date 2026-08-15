---
type: Access Method
title: REST APIs
description: Conventions and worked examples for the REST-flavored archive APIs (NWIS, NEON, AmeriFlux-style).
tags: [rest, json, api]
generated: { by: "claude-opus-5/lto-okf", at: 2026-08-14T03:58:00Z }
status: stable
---

Thirty-nine archives in this catalogue expose a REST API. Each archive's
[concept doc](./index.md) lists its documented calls with an example;
the patterns below cover the big federal services most facilities
resolve to.

# USGS NWIS (water data)

```bash
# Daily values, one gage, one parameter (00060 = discharge), JSON
curl 'https://waterservices.usgs.gov/nwis/dv/?format=json&sites=09380000&parameterCd=00060&startDT=2024-01-01&endDT=2024-12-31'
# Instantaneous values use /nwis/iv/; site metadata /nwis/site/
```

RDB (tab-separated) output: `format=rdb` — every line starting with `#`
is a comment, and the comment block's length varies by site and query
(28 lines in the example above). Skip all `#` lines: the first
non-comment line is the column names, the second is the column
format/type line (e.g. `5s	15s	20d	14n	10s`), and data follows.

# NEON Data API

```bash
# Products → sites → data files, three hops:
curl 'https://data.neonscience.org/api/v0/products/DP1.00098.001'
curl 'https://data.neonscience.org/api/v0/sites/JORN'
# The /data/ tier is TOKEN-GATED (verified 2026-08-14: anonymous calls
# return 403 "Access Denied" for every product/site/month). Get a free
# API token from your NEON user account and send it:
curl -H 'X-API-Token: <token>' 'https://data.neonscience.org/api/v0/data/DP1.00098.001/JORN/2024-06'
# → response.data.files[].url are presigned download links
```

# General conventions

- Prefer `Accept: application/json` headers over format query params
  when an API supports both; the concept docs note which form each
  archive documents.
- Page politely: most services cap page size (NWIS by period, NEON by
  month). Loop months/years rather than requesting decade spans.
- Every documented call in this bundle carries a copy-able example on
  the [Data tab](../index.md) and in the archive's concept doc — start
  from the example, then generalize.

```python
import requests
r = requests.get("https://waterservices.usgs.gov/nwis/dv/",
                 params=dict(format="json", sites="09380000",
                             parameterCd="00060", startDT="2024-01-01",
                             endDT="2024-12-31"), timeout=60)
series = r.json()["value"]["timeSeries"]
```
