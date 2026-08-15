---
type: Data Archive
title: "OBIS-USA"
description: "USGS / NMFS / Smithsonian (US OBIS node) — repository holding long-term observatory records."
resource: "https://obis.org/node/b7c47783-a020-4173-b390-7b57c4fa1426"
tags: [repository, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

US node of Ocean Biodiversity Information System; aggregates DwC-A occurrence datasets including NMFS bottom-trawl, SEAMAP, and reef monitoring. retrieved_at=2026-05-06; agent=K-NMFS [via K-NMFS]

# Access

- Archive home: <https://obis.org/node/b7c47783-a020-4173-b390-7b57c4fa1426>
- API root (`rest`): <https://api.obis.org/v3/> — see the [rest guide](./access-rest.md)
- API documentation: <https://api.obis.org/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-access | GET | application/json | <https://api.obis.org/v3/occurrence?nodeid=b7c47783-a020-4173-b390-7b57c4fa1426&size={n}> | curl 'https://api.obis.org/v3/occurrence?nodeid=b7c47783-a020-4173-b390-7b57c4fa1426&size=5' |
| metadata | GET | application/json | <https://api.obis.org/v3/dataset?nodeid=b7c47783-a020-4173-b390-7b57c4fa1426> | curl 'https://api.obis.org/v3/dataset?nodeid=b7c47783-a020-4173-b390-7b57c4fa1426' |
