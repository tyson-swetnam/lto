---
type: Data Archive
title: "USGS ScienceBase Catalog"
description: "U.S. Geological Survey, Core Science Systems — repository holding long-term observatory records."
resource: "https://www.sciencebase.gov/catalog/"
tags: [repository, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Cross-USGS data and metadata catalog; mints 10.5066/* DOIs for Data Releases. Items addressable by 24-hex-character 'item id'. Formats: JSON metadata, mixed payloads (CSV, NetCDF, GeoTIFF, shapefiles, etc.). retrieved_at=2026-05-06; agent=J-A-USGS [via J-A-USGS]

# Access

- Archive home: <https://www.sciencebase.gov/catalog/>
- API root (`rest`): <https://www.sciencebase.gov/catalog/items> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.sciencebase.gov/catalog/jsonapi>
- DOIs minted here start with `10.5066`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| metadata | GET | application/json | <https://www.sciencebase.gov/catalog/item/{itemId}?format=json> | curl 'https://www.sciencebase.gov/catalog/item/5fb7c8c5d34e30b9123abc12?format=json' |
| search | GET | application/json | <https://www.sciencebase.gov/catalog/items?q={query}&format=json&max=100> | curl 'https://www.sciencebase.gov/catalog/items?q=wolverine+glacier&format=json&max=10' |

# Depositing facilities

- **BRW-PF** Barrow Permafrost Observatory (Utqiagvik) (primary)
- **CLSA-LTER-LIKE** Cottonwood Lake Study Area (primary)
- **GLK** Gulkana Glacier (primary)
- **HAKALAU** Hakalau Forest National Wildlife Refuge (primary)
- **USFWS-NPWRC** Northern Prairie Wildlife Research Center (primary)
- **PCMSC** Pacific Coastal and Marine Science Center (primary)
- **SCG** South Cascade Glacier (primary)
- **SPG** Sperry Glacier (primary)
- **SPCMSC** St. Petersburg Coastal and Marine Science Center (primary)
- **USGS-CRS-MOAB** USGS Canyonlands Research Station (Moab) (primary)
- **GAL-PF** USGS Galbraith Lake Permafrost Borehole (primary)
- **GLSC** USGS Great Lakes Science Center (primary)
- **WEBB-SLR** USGS WEBB Sleepers River Research Watershed (primary)
- **WLV** Wolverine Glacier (primary)
- **WHCMSC** Woods Hole Coastal and Marine Science Center (primary)
- **LCG** Lemon Creek Glacier (secondary)
- **PWRC-BBL** Patuxent Research Refuge / Bird Banding Lab (secondary)
- **WEBB-LVW** USGS WEBB Loch Vale Watershed (secondary)

# Data products

5 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Hawaii Forest Bird Survey — point-count data, Hawaii Island](https://www.sciencebase.gov/catalog/?q=hawaii+forest+bird+survey) | csv | 1976-01-01–present | n/a |
| [USGS Benchmark Glacier Project — Gulkana Glacier mass balance and meteorological observations](https://www.sciencebase.gov/catalog/?q=gulkana+glacier+benchmark) | csv | 1966-01-01–present | n/a |
| [USGS Benchmark Glacier Project — South Cascade Glacier mass balance](https://www.sciencebase.gov/catalog/?q=south+cascade+glacier+benchmark) | csv | 1958-01-01–present | n/a |
| [USGS Benchmark Glacier Project — Sperry Glacier mass balance](https://www.sciencebase.gov/catalog/?q=sperry+glacier) | csv | 2005-01-01–present | n/a |
| [USGS Benchmark Glacier Project — Wolverine Glacier mass balance and meteorological observations](https://www.sciencebase.gov/catalog/?q=wolverine+glacier+benchmark) | csv | 1966-01-01–present | n/a |
