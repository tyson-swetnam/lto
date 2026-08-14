---
type: Data Archive
title: "USGS StreamStats"
description: "U.S. Geological Survey, Water Mission Area — service holding long-term observatory records."
resource: "https://streamstats.usgs.gov/"
tags: [service, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Web service for delineating drainage basins and computing flow statistics at user-supplied points; state-level regression equations. retrieved_at=2026-05-06; agent=J-A-USGS [via J-A-USGS]

# Access

- Archive home: <https://streamstats.usgs.gov/>
- API root (`rest`): <https://streamstats.usgs.gov/streamstatsservices/> — see the [rest guide](./access-rest.md)
- API documentation: <https://streamstats.usgs.gov/docs/streamstatsservices/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/geo+json | <https://streamstats.usgs.gov/streamstatsservices/watershed.geojson?rcode={state}&xlocation={lon}&ylocation={lat}&crs=4326&includeparameters=true> | curl 'https://streamstats.usgs.gov/streamstatsservices/watershed.geojson?rcode=NY&xlocation=-74.524&ylocation=43.939&crs=4326&includeparameters=true' |
