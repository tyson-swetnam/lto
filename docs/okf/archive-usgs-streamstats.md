---
type: Data Archive
title: "USGS StreamStats"
description: "U.S. Geological Survey, Water Mission Area — service holding long-term observatory records."
resource: "https://streamstats.usgs.gov/"
tags: [service, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Web service for delineating drainage basins and computing flow statistics at user-supplied points; state-level regression equations. retrieved_at=2026-05-06; agent=J-A-USGS [via J-A-USGS]

# Access

- Archive home: <https://streamstats.usgs.gov/>
- API root (`rest`): <https://streamstats.usgs.gov/ss-delineate/> — see the [rest guide](./access-rest.md)
- API documentation: <https://streamstats.usgs.gov/ss-delineate/docs>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/geo+json | <https://streamstats.usgs.gov/ss-delineate/v1/delineate/features/{state}?lat={lat}&lon={lon}> | curl 'https://streamstats.usgs.gov/ss-delineate/v1/delineate/features/NY?lat=43.939&lon=-74.524' |
