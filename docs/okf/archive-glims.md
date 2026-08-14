---
type: Data Archive
title: "Global Land Ice Measurements from Space"
description: "GLIMS / NSIDC — repository holding long-term observatory records."
resource: "https://www.glims.org/"
tags: [repository, wms, cc-by-4.0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Global glacier outlines + Randolph Glacier Inventory (RGI) ancillary database. Shapefile + GeoJSON. CC-BY-4.0 (most contributors). Hosted at NSIDC. retrieved_at=2026-05-06; agent=J-A-NSIDC-CRY [via J-A-NSIDC-CRY]

# Access

- Archive home: <https://www.glims.org/>
- API root (`wms`): <https://www.glims.org/glimsview/> — see the [wms guide](./access-rest.md)
- API documentation: <https://www.glims.org/MapsAndDocs/>
- DOIs minted here start with `10.7265`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| wms | GET | image/png | <https://www.glims.org/glimsview/wms> | curl 'https://www.glims.org/glimsview/wms?service=WMS&request=GetMap&layers=glaciers&bbox=-180,-90,180,90&width=512&height=256&srs=EPSG:4326&format=image/png' |

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Randolph Glacier Inventory, Version 7.0](https://doi.org/10.5067/F6JMOVY5NAVZ) | shapefile | 2000-01-01–2010-12-31 | n/a |
