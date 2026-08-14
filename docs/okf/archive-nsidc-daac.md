---
type: Data Archive
title: "NSIDC Distributed Active Archive Center"
description: "National Snow and Ice Data Center / NASA Earthdata / CIRES, University of Colorado Boulder — repository holding long-term observatory records."
resource: "https://nsidc.org/data"
tags: [repository, rest, nasa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

NASA DAAC for snow, ice, cryosphere, and climate. Hosts MODIS, SMAP, ICESat/ICESat-2, IceBridge, SnowEx, sea-ice indices. Data formats: HDF5, NetCDF-4, GeoTIFF, CSV. Access via Earthdata Login (most products) or anonymous (Sea Ice Index, MASIE). Native S3 access from us-west-2 via NASA Earthdata Cloud (Cumulus). retrieved_at=2026-05-06; agent=J-A-NSIDC-CRY [via J-A-NSIDC-CRY]

# Access

- Archive home: <https://nsidc.org/data>
- API root (`rest`): <https://nsidc.org/api/> — see the [rest guide](./access-rest.md)
- API documentation: <https://nsidc.org/data/user-resources/help-center/programmatic-data-access-guide>
- DOIs minted here start with `10.5067`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/x-hdf5 | <https://n5eil01u.ecs.nsidc.org/{dataset_path}/> | curl -b ~/.urs_cookies -c ~/.urs_cookies https://n5eil01u.ecs.nsidc.org/SAN/SMAP/SPL3SMP.008/2024.01.01/SMAP_L3_SM_P_20240101_R18290_001.h5 |
| data-download | GET | application/zip | <https://n5eil02u.ecs.nsidc.org/egi/request> | curl -b ~/.urs_cookies -c ~/.urs_cookies 'https://n5eil02u.ecs.nsidc.org/egi/request?short_name=ATL06&version=006&time=2020-01-01,2020-01-31&bbox=-148,69,-145,71' |
| metadata | GET | application/json | <https://nsidc.org/api/dataset-metadata/v1/dataset/{dataset_id}> | curl https://nsidc.org/api/dataset-metadata/v1/dataset/NSIDC-0051 |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [nsidc-cumulus-prod-protected](https://nsidc.org/data/user-resources/help-center/nasa-earthdata-cloud-data-access-guide) | us-west-2 | registered-users | `MEASURES/NSIDC-0478.002/` |
| s3 | [nsidc-cumulus-prod-public](https://nsidc.org/data/user-resources/help-center/nasa-earthdata-cloud-data-access-guide) | us-west-2 | public-anon-egress | `ATLAS/ATL06.006/` |

# Depositing facilities

- **LSB** Cape Lisburne Coast Guard / NSIDC Sea-Ice Observatory (primary)
- **NSIDC-BRW** NSIDC Utqiagvik (Barrow) Sea-Ice Mass Balance Site (primary)

# Data products

8 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [ATLAS/ICESat-2 L3A Land Ice Height, Version 6](https://doi.org/10.5067/ATLAS/ATL06.006) | hdf5 | 2018-10-13–present | n/a |
| [ATLAS/ICESat-2 L3A Sea Ice Height, Version 6](https://doi.org/10.5067/ATLAS/ATL07.006) | hdf5 | 2018-10-14–present | n/a |
| [Bootstrap Sea Ice Concentrations from Nimbus-7 SMMR and DMSP SSM/I-SSMIS, Version 3](https://doi.org/10.5067/7Q8HCCWS4I0R) | netcdf | 1978-10-26–present | n/a |
| [MEaSUREs Greenland Ice Sheet Velocity Map from InSAR Data, Version 2](https://doi.org/10.5067/OC7B04ZM9G6Q) | netcdf | 2000-09-09–2018-12-31 | n/a |
| [MODIS/Terra Snow Cover Daily L3 Global 500m SIN Grid, Version 61](https://doi.org/10.5067/MODIS/MOD10A1.061) | hdf5 | 2000-02-24–present | n/a |
| [SMAP L3 Radiometer Global Daily 36 km EASE-Grid Soil Moisture, Version 8](https://doi.org/10.5067/4DQ54OUIJ9DL) | hdf5 | 2015-03-31–present | n/a |
| [Sea Ice Concentrations from Nimbus-7 SMMR and DMSP SSM/I-SSMIS Passive Microwave Data, Version 2](https://doi.org/10.5067/MPYG15WAA4WX) | netcdf | 1978-10-25–present | n/a |
| [Seasonal Ice Mass-Balance Buoys: Adapting Tools to Capture Snow on Sea Ice](https://nsidc.org/data/g10014) | csv | 2000-01-01–present | n/a |
