---
type: Data Archive
title: "Marine Geoscience Data System"
description: "Lamont-Doherty Earth Observatory / NSF — repository holding long-term observatory records."
resource: "https://www.marine-geo.org/"
tags: [repository, rest, cc-by-4.0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Marine geoscience field data (multibeam bathymetry, seismic reflection, sediment cores, dredges) from NSF-funded research. Hosts GeoMapApp tile services + per-cruise data products. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://www.marine-geo.org/>
- API root (`rest`): <https://www.marine-geo.org/services/> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.marine-geo.org/tools/services.php>
- DOIs minted here start with `10.1594`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| search | GET | application/json | <https://www.marine-geo.org/services/MGDSDatasets> | curl 'https://www.marine-geo.org/services/MGDSDatasets?type=multibeam' |
