---
type: Data Archive
title: "OBIS-USA"
description: "USGS / NMFS / Smithsonian (US OBIS node) — repository holding long-term observatory records."
resource: "https://obis.org/node/3162d234-71b6-4196-b7c6-bf09ab50d1bf"
tags: [repository, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

US node of Ocean Biodiversity Information System; aggregates DwC-A occurrence datasets including NMFS bottom-trawl, SEAMAP, and reef monitoring. retrieved_at=2026-05-06; agent=K-NMFS [via K-NMFS]

# Access

- Archive home: <https://obis.org/node/3162d234-71b6-4196-b7c6-bf09ab50d1bf>
- API root (`rest`): <https://api.obis.org/v3/> — see the [rest guide](./access-rest.md)
- API documentation: <https://api.obis.org/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-access | GET | application/json | <https://api.obis.org/v3/occurrence?nodeid=3162d234-71b6-4196-b7c6-bf09ab50d1bf&size={n}> | curl 'https://api.obis.org/v3/occurrence?nodeid=3162d234-71b6-4196-b7c6-bf09ab50d1bf&size=100' |
| metadata | GET | application/json | <https://api.obis.org/v3/dataset?nodeid=3162d234-71b6-4196-b7c6-bf09ab50d1bf> | curl 'https://api.obis.org/v3/dataset?nodeid=3162d234-71b6-4196-b7c6-bf09ab50d1bf' |
