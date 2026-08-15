---
type: Data Archive
title: "ORNL DAAC — Oak Ridge National Laboratory Distributed Active Archive Center for Biogeochemical Dynamics"
description: "Oak Ridge National Laboratory / NASA Earth Science Data and Information System (ESDIS) — repository holding long-term observatory records."
resource: "https://daac.ornl.gov/"
tags: [repository, rest, nasa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

NASA DAAC for terrestrial ecology and biogeochemistry. Holds ABoVE, CMS, GEDI L4, MODIS-derived products, FLUXNET site files, soil moisture, vegetation indices. DOIs 10.3334/ORNLDAAC/<numeric_id>. CSV + NetCDF + GeoTIFF. Some products require NASA Earthdata Login; bulk objects on s3://ornldaac-cumulus-prod-public-data (us-west-2). Discovery via NASA CMR + native dataset DOI landing pages. retrieved_at=2026-05-06; agent=J-A-ESS-DIVE-DOE [via J-A-ESS-DIVE-DOE]

# Access

- Archive home: <https://daac.ornl.gov/>
- API root (`rest`): <https://cmr.earthdata.nasa.gov/search/> — see the [rest guide](./access-rest.md)
- API documentation: <https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html>
- DOIs minted here start with `10.3334`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/octet-stream | <https://daac.ornl.gov/daacdata/{program}/{dataset_short_name}/data/{file}> | https://daac.ornl.gov/daacdata/above/ABoVE_Boreal_Biomass_Map/data/ABoVE_Boreal_Biomass_Map.tif |
| landing | GET | text/html | <https://daac.ornl.gov/cgi-bin/dsviewer.pl?ds_id={dataset_id}> | https://daac.ornl.gov/cgi-bin/dsviewer.pl?ds_id=2056 |
| listing | GET | application/json | <https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id={id}&page_size=2000> | curl 'https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id=C2769857263-ORNL_CLOUD&page_size=200' |
| search | GET | application/json | <https://cmr.earthdata.nasa.gov/search/collections.json?provider=ORNL_CLOUD&keyword={query}&page_size=100> | curl 'https://cmr.earthdata.nasa.gov/search/collections.json?provider=ORNL_CLOUD&keyword=ABoVE&page_size=50' |

# Depositing facilities

- **ORNL-NERP** Oak Ridge National Environmental Research Park (primary)
- **WBW-LTHS** Walker Branch Watershed Long-Term Hydrologic Station (primary)

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Oak Ridge FACE (Free-Air CO2 Enrichment) sweetgum experiment archived data](https://daac.ornl.gov/) | csv | 1998-01-01–2009-12-31 | n/a |
| [Walker Branch Watershed Project archived data (precipitation chemistry, throughfall, streamflow)](https://daac.ornl.gov/cgi-bin/dataset_lister.pl?p=42) | csv | 1969-01-01–2007-12-31 | n/a |
