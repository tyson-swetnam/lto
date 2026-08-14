---
type: Data Archive
title: "Rolling Deck to Repository (R2R)"
description: "Lamont-Doherty Earth Observatory / NSF UNOLS — repository holding long-term observatory records."
resource: "https://www.rvdata.us/"
tags: [repository, rest, cc-by-4.0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Catalog of NSF UNOLS oceanographic research-cruise underway data (nav, met, ADCP, multibeam, gravity). Per-cruise DOI 10.7284/<id>; data forwarded to NCEI for long-term archive. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://www.rvdata.us/>
- API root (`rest`): <https://service.rvdata.us/api/> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.rvdata.us/about/web-services>
- DOIs minted here start with `10.7284`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| metadata | GET | application/json | <https://service.rvdata.us/api/cruise/{cruise_id}> | curl https://service.rvdata.us/api/cruise/AT26-19 |
