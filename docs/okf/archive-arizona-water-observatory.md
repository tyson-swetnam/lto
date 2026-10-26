---
type: Data Archive
title: "Arizona Water Observatory (AWO)"
description: "Arizona State University, with the Internet of Water (Center for Geospatial Solutions, Lincoln Institute of Land Policy) — aggregator holding long-term observatory records."
resource: "https://arizonawaterobservatory.asu.edu/"
tags: [aggregator, ogc-api, unknown]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-10-26T01:52:50Z }
status: stable
---

The Arizona Water Observatory (AWO) provides water quality and water supply information for Arizona's water resources. A pygeoapi deployment serving OGC API Features, Environmental Data Retrieval (EDR), Maps and Processes; most collections front another agency's service (NOAA, USGS, USDA, USBR, USACE, NASA, Arizona Department of Water Resources), named in each record's notes. Source code: https://github.com/cgs-earth/ArizonaWaterObservatory. The API document declares the MIT License, which covers the software; each upstream dataset keeps its own terms, so the records here carry license 'unknown'. This catalogue holds metadata and links only. [via J-AZWATER]

# Access

- Archive home: <https://arizonawaterobservatory.asu.edu/>
- API root (`ogc-api`): <https://arizonawaterobservatory-api.rtd.asu.edu>
- API documentation: <https://arizonawaterobservatory-api.rtd.asu.edu/openapi?f=html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| download | GET | json | <https://arizonawaterobservatory-api.rtd.asu.edu/collections/{collectionId}/cube> | curl -s 'https://arizonawaterobservatory-api.rtd.asu.edu/collections/National_Water_Model_Channel_Routing_Output/cube?f=json&bbox=-112.5,33.2,-111.5,33.8&datetime=2023-01-01/2023-01-31' |
| download | GET | geojson | <https://arizonawaterobservatory-api.rtd.asu.edu/collections/{collectionId}/items> | curl -s 'https://arizonawaterobservatory-api.rtd.asu.edu/collections/National_Water_Model_Channel_Routing_Output/items?f=json&limit=10' |
| metadata | GET | json | <https://arizonawaterobservatory-api.rtd.asu.edu/collections> | curl -s 'https://arizonawaterobservatory-api.rtd.asu.edu/collections?f=json' |
| metadata | GET | json | <https://arizonawaterobservatory-api.rtd.asu.edu/collections/{collectionId}/queryables> | curl -s 'https://arizonawaterobservatory-api.rtd.asu.edu/collections/National_Water_Model_Channel_Routing_Output/queryables?f=json' |
| metadata | GET | json | <https://arizonawaterobservatory-api.rtd.asu.edu/openapi> | curl -s 'https://arizonawaterobservatory-api.rtd.asu.edu/openapi?f=json' |
| metadata | GET | json | <https://arizonawaterobservatory-api.rtd.asu.edu/processes> | curl -s 'https://arizonawaterobservatory-api.rtd.asu.edu/processes?f=json' |
| search | GET | geojson | <https://arizonawaterobservatory-api.rtd.asu.edu/collections/{collectionId}/locations> | curl -s 'https://arizonawaterobservatory-api.rtd.asu.edu/collections/National_Water_Model_Channel_Routing_Output/locations?f=json' |

# Data products

26 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Arizona Department of Water Resources Active Management Areas](https://arizonawaterobservatory-api.rtd.asu.edu/collections/Active_Management_Areas_2025?f=html) | geojson | — | n/a |
| [Arizona Department of Water Resources Groundwater Basins](https://arizonawaterobservatory-api.rtd.asu.edu/collections/Arizona_Groundwater_Basins?f=html) | geojson | — | n/a |
| [Arizona Department of Water Resources Groundwater Site Inventory](https://arizonawaterobservatory-api.rtd.asu.edu/collections/ArizonaWaterWells?f=html) | geojson | 1902-03-31–2025-09-09 | n/a |
| [Arizona Department of Water Resources Irrigation Districts](https://arizonawaterobservatory-api.rtd.asu.edu/collections/ArizonaIrrigationDistricts?f=html) | geojson | — | n/a |
| [Central Arizona Project (CAP) Diversion Canal](https://arizonawaterobservatory-api.rtd.asu.edu/collections/CentralArizonaProjectCanal?f=html) | geojson | — | n/a |
| [GRACE/FO-derived GWS change by Arizona Groundwater Basin from 2003-2023](https://arizonawaterobservatory-api.rtd.asu.edu/collections/ASU_Groundwater_Basins_Aggregated_Grace?f=html) | geojson | 2003-10-01–2023-09-01 | n/a |
| [GRACE/FO-derived Lower Colorado Basin Groundwater Storage Levels Changes](https://arizonawaterobservatory-api.rtd.asu.edu/collections/ASU_LCRB_GRACE?f=html) | geojson | 2003-10-01–2023-09-01 | n/a |
| [NASA Soil Moisture Active Passive L4 Global 3-hourly 9 km EASE-Grid Surface and Root Zone Soil Moisture Geophysical Data, Version 8 (SPL4SMGP)](https://arizonawaterobservatory-api.rtd.asu.edu/collections/SMAP_SPL4SMGP?f=html) | json | — | n/a |
| [NOAA National Water Model Channel Routing Output](https://arizonawaterobservatory-api.rtd.asu.edu/collections/National_Water_Model_Channel_Routing_Output?f=html) | json | 1979-02-01–2023-02-01 | n/a |
| [NOAA National Water Model Groundwater Output](https://arizonawaterobservatory-api.rtd.asu.edu/collections/National_Water_Model_Groundwater_Output?f=html) | json | 1979-02-01–2023-02-01 | n/a |
