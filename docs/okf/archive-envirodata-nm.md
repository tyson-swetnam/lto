---
type: Data Archive
title: "EnviroData-NM — New Mexico Environmental Data Portal"
description: "Natural Heritage New Mexico, Museum of Southwestern Biology, University of New Mexico — data-portal holding long-term observatory records."
resource: "https://envirodata-nm.unm.edu/explore/"
tags: [data-portal, ogc-wms-wfs, envirodata-nm-terms]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-10-25T04:20:50Z }
status: stable
---

Housed and maintained by Natural Heritage New Mexico under the 2021 Environmental Database Act (HB51); contributing agencies include NM Game & Fish, NM Environment Department, State Land Office, NM Department of Health and EMNRD. This catalogue holds metadata and links only: the portal's terms (https://envirodata-nm.unm.edu/terms) do not permit redistributing the data, so every record points at the portal's own download or OGC endpoint. [via J-ENVIRODATA]

# Access

- Archive home: <https://envirodata-nm.unm.edu/explore/>
- API root (`ogc-wms-wfs`): <https://envirodata-nm.unm.edu/ogc/>
- API documentation: <https://envirodata-nm.unm.edu/ogc/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| browse | GET | image/png | <https://envirodata-nm.unm.edu/ogc/wms/{layer}> | curl -s 'https://envirodata-nm.unm.edu/ogc/wms/air_facilities_major_title_v?service=WMS&request=GetCapabilities' |
| download | GET | geojson | <https://envirodata-nm.unm.edu/data/download/layer/{id}> | curl -sO 'https://envirodata-nm.unm.edu/data/download/layer/37?format=geojson' |
| metadata | GET | json | <https://envirodata-nm.unm.edu/explore/api/layers> | curl -s https://envirodata-nm.unm.edu/explore/api/layers |
| metadata | GET | json | <https://envirodata-nm.unm.edu/ogc/layers> | curl -s https://envirodata-nm.unm.edu/ogc/layers |
| metadata | GET | xml | <https://envirodata-nm.unm.edu/ogc/wfs/{layer}> | curl -s 'https://envirodata-nm.unm.edu/ogc/wfs/air_facilities_major_title_v?service=WFS&version=1.1.0&request=GetCapabilities' |
| search | GET | json | <https://envirodata-nm.unm.edu/ogc/attributes/{layer}> | curl -s 'https://envirodata-nm.unm.edu/ogc/attributes/air_facilities_major_title_v?limit=5&offset=0' |

# Depositing facilities

- **MSB** Museum of Southwestern Biology (primary)
- **ARID** Accelerating Resilience Innovations in Drylands (ARID Institute) (supporting)

# Data products

139 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Active Ground Water Systems](https://envirodata-nm.unm.edu/data/download/layer/220?format=geojson) | geojson | — | n/a |
| [Active Mines](https://envirodata-nm.unm.edu/data/download/layer/21?format=geojson) | geojson | — | n/a |
| [Active NPDES Permits](https://envirodata-nm.unm.edu/data/download/layer/31?format=geojson) | geojson | — | n/a |
| [Active Oil and Gas Wells](https://envirodata-nm.unm.edu/ogc/wms/activeoilandgaswells_active_oil_and_gas_wells?service=WMS&request=GetCapabilities) | ogc-wms | — | n/a |
| [Active State Trust Land Leases](https://envirodata-nm.unm.edu/ogc/wms/active_state_trust_land_leases_slo_stlstatuscombined_own?service=WMS&request=GetCapabilities) | ogc-wms | — | n/a |
| [Active Surface Water Systems](https://envirodata-nm.unm.edu/data/download/layer/219?format=geojson) | geojson | — | n/a |
| [Adult Asthma](https://envirodata-nm.unm.edu/data/download/layer/308?format=geojson) | geojson | — | n/a |
| [Agricultural Leases](https://envirodata-nm.unm.edu/ogc/wms/slo_active_leases_t_agricultural_leases?service=WMS&request=GetCapabilities) | ogc-wms | — | n/a |
| [All Oil and Gas Wells](https://envirodata-nm.unm.edu/ogc/wms/wellspublicmap_wells_large_scale?service=WMS&request=GetCapabilities) | ogc-wms | — | n/a |
| [Aquifer Sensitivity](https://envirodata-nm.unm.edu/data/download/layer/22?format=geojson) | geojson | — | n/a |
