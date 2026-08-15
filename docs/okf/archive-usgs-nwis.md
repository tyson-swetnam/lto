---
type: Data Archive
title: "USGS National Water Information System"
description: "U.S. Geological Survey, Water Mission Area — repository holding long-term observatory records."
resource: "https://waterdata.usgs.gov/"
tags: [repository, rest, usgs-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

National Water Information System; serves discharge, stage, water-quality, groundwater levels, site metadata for ~1.9 million sites. Formats: RDB (tab-delimited), WaterML 1.1/2.0, JSON, CSV. Streamgage IDs are 8-15 digit USGS site numbers. retrieved_at=2026-05-06; agent=J-A-USGS [via J-A-USGS]

# Access

- Archive home: <https://waterdata.usgs.gov/>
- API root (`rest`): <https://waterservices.usgs.gov/> — see the [rest guide](./access-rest.md)
- API documentation: <https://waterservices.usgs.gov/docs/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/tab-separated-values | <https://waterservices.usgs.gov/nwis/dv/?sites={site_no}&parameterCd={params}&startDT={start}&endDT={end}&format=rdb> | curl 'https://waterservices.usgs.gov/nwis/dv/?sites=09380000&parameterCd=00060&startDT=1921-10-01&format=rdb' |
| data-download | GET | application/json | <https://waterservices.usgs.gov/nwis/iv/?sites={site_no}&parameterCd={params}&startDT={start}&endDT={end}&format=json> | curl 'https://waterservices.usgs.gov/nwis/iv/?sites=01400500&parameterCd=00060,00065&period=P7D&format=json' |
| data-download | GET | text/tab-separated-values | <https://waterservices.usgs.gov/nwis/stat/?sites={site_no}&statReportType=daily&parameterCd={params}&format=rdb> | curl 'https://waterservices.usgs.gov/nwis/stat/?sites=09380000&statReportType=daily&parameterCd=00060&format=rdb' |
| data-download | GET | text/tab-separated-values | <https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items?monitoring_location_id={site_no}&f=json> | curl 'https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items?state_name=Alaska&parameter_code=72019&limit=2&f=json' |
| metadata | GET | text/tab-separated-values | <https://waterservices.usgs.gov/nwis/site/?sites={site_no}&siteOutput=expanded&format=rdb> | curl 'https://waterservices.usgs.gov/nwis/site/?sites=11447650&siteOutput=expanded&format=rdb' |

# Depositing facilities

- **LTAR-AQRC** Lower Tombigbee–Alabama River Aquatic Resources Area (primary)
- **NWIS-01400500** USGS Gauge 01400500 — Raritan River at Manville NJ (primary)
- **NWIS-06190500** USGS Gauge 06190500 — Yellowstone River at Corwin Springs MT (primary)
- **NWIS-09380000** USGS Gauge 09380000 — Colorado River at Lees Ferry AZ (primary)
- **NWIS-11447650** USGS Gauge 11447650 — Sacramento River at Freeport CA (primary)
- **NWIS-14191000** USGS Gauge 14191000 — Willamette River at Salem OR (primary)
- **DENALI-NPS-LTM** Denali National Park Long-Term Ecological Monitoring (Central Alaska Network, NPS-IM) (secondary)
- **GRSM-NP** Great Smoky Mountains National Park (Twin Creeks Science and Education Center) (secondary)
- **KREW-EW** Kings River Experimental Watersheds (secondary)
- **SYCA-LTER** Sycamore Creek Long-Term Stream-Ecology Site (ASU) (secondary)
- **USGS-CRS-MOAB** USGS Canyonlands Research Station (Moab) (secondary)
- **WEBB-SLR** USGS WEBB Sleepers River Research Watershed (secondary)
- **YNP-LT** Yellowstone National Park — Long-Term Ecological Monitoring (secondary)
- **IUTAH-GAMUT-RB** iUTAH GAMUT Red Butte Creek Watershed Observatory (secondary)

# Data products

10 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [USGS 01400500 Raritan River at Manville NJ — daily discharge](https://waterservices.usgs.gov/nwis/dv/?sites=01400500&parameterCd=00060&format=rdb) | tsv | 1903-10-01–present | n/a |
| [USGS 01400500 Raritan River at Manville NJ — instantaneous values](https://waterservices.usgs.gov/nwis/iv/?sites=01400500&parameterCd=00060,00065&format=json) | json | 2007-10-01–present | n/a |
| [USGS 06190500 Yellowstone River at Corwin Springs MT — daily discharge](https://waterservices.usgs.gov/nwis/dv/?sites=06190500&parameterCd=00060&format=rdb) | tsv | 1910-10-01–present | n/a |
| [USGS 09380000 Colorado River at Lees Ferry AZ — daily discharge](https://waterservices.usgs.gov/nwis/dv/?sites=09380000&parameterCd=00060&format=rdb) | tsv | 1921-10-01–present | n/a |
| [USGS 11447650 Sacramento River at Freeport CA — daily discharge and water quality](https://waterservices.usgs.gov/nwis/dv/?sites=11447650&parameterCd=00060,00010,80154&format=rdb) | tsv | 1948-10-01–present | n/a |
| [USGS 14191000 Willamette River at Salem OR — daily discharge](https://waterservices.usgs.gov/nwis/dv/?sites=14191000&parameterCd=00060&format=rdb) | tsv | 1909-10-01–present | n/a |
| [USGS 50075000 Río Icacos near Naguabo PR — daily discharge](https://waterservices.usgs.gov/nwis/dv/?sites=50075000&parameterCd=00060&format=rdb) | tsv | 1946-10-01–present | n/a |
| [USGS NWIS gage 06191500 — Yellowstone River at Corwin Springs, MT](https://waterdata.usgs.gov/mt/nwis/uv/?site_no=06191500) | csv | 1910-10-01–present | n/a |
| [USGS NWIS gage 09185600 — Colorado River near Cisco / Moab, UT (regional context)](https://waterdata.usgs.gov/ut/nwis/uv/) | csv | 1913-01-01–present | n/a |
| [USGS NWIS gage 09510200 — Sycamore Creek near Fort McDowell, AZ](https://waterdata.usgs.gov/az/nwis/uv/?site_no=09510200) | csv | 1960-10-01–present | n/a |
