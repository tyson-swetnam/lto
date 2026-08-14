---
type: Data Archive
title: "NOAA InPort Metadata Catalog"
description: "NOAA / National Marine Fisheries Service — data-portal holding long-term observatory records."
resource: "https://www.fisheries.noaa.gov/inport/"
tags: [data-portal, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Agency-wide ISO-19115 metadata catalog covering NMFS science centers, regional offices, and OST. Items, organizations, and people endpoints under /api/v1. retrieved_at=2026-05-06; agent=K-NMFS [via K-NMFS]

# Access

- Archive home: <https://www.fisheries.noaa.gov/inport/>
- API root (`rest`): <https://www.fisheries.noaa.gov/inport/api/v1> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.fisheries.noaa.gov/inport/help/api>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| metadata | GET | application/json | <https://www.fisheries.noaa.gov/inport/api/v1/item/{catalog_item_id}> | curl https://www.fisheries.noaa.gov/inport/api/v1/item/22561 |
| metadata | GET | application/json | <https://www.fisheries.noaa.gov/inport/api/v1/organization/{organization_id}> | curl https://www.fisheries.noaa.gov/inport/api/v1/organization/9 |
| search | GET | application/json | <https://www.fisheries.noaa.gov/inport/api/v1/item?keyword={term}&page={n}> | curl 'https://www.fisheries.noaa.gov/inport/api/v1/item?keyword=bottom+trawl&page=1' |

# Depositing facilities

- **AFSC** Alaska Fisheries Science Center (primary)
- **NEFSC** Northeast Fisheries Science Center (primary)
- **NWFSC** Northwest Fisheries Science Center (primary)
- **PIFSC** Pacific Islands Fisheries Science Center (primary)
- **SEFSC** Southeast Fisheries Science Center (primary)

# Data products

5 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Eastern Bering Sea Continental Shelf Bottom Trawl Survey](https://www.fisheries.noaa.gov/inport/item/10277) | csv | 1982-01-01–present | n/a |
| [Hawaii Pelagic Longline Observer Program](https://www.fisheries.noaa.gov/inport/item/9286) | csv | 1994-01-01–present | n/a |
| [NEFSC Bottom Trawl Survey](https://www.fisheries.noaa.gov/inport/item/22561) | csv | 1963-01-01–present | n/a |
| [SEAMAP Gulf of Mexico Groundfish Survey](https://www.fisheries.noaa.gov/inport/item/22432) | csv | 1982-01-01–present | n/a |
| [West Coast Groundfish Bottom Trawl Survey](https://www.fisheries.noaa.gov/inport/item/18418) | csv | 2003-01-01–present | n/a |
