---
type: Data Archive
title: "NASA Ocean Biology Distributed Active Archive Center (OB.DAAC) / OceanColor Web"
description: "NASA / GSFC Ocean Biology Processing Group — data-portal holding long-term observatory records."
resource: "https://oceancolor.gsfc.nasa.gov/"
tags: [data-portal, rest, nasa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

OBPG produces ocean-color L1/L2/L3 products from CZCS, OCTS, SeaWiFS, MODIS Aqua/Terra, MERIS, VIIRS (SNPP, NOAA-20/21), HICO, OLCI, PACE/OCI. Distributed via OB.DAAC. Bulk via getfile.py + Earthdata-Login bearer tokens; AWS mirror in nasa-pace-prod / oceandata.sci.gsfc S3. retrieved_at=2026-05-06; agent=K-USACE-NRL-NASA [via K-USACE-NRL-NASA]

# Access

- Archive home: <https://oceancolor.gsfc.nasa.gov/>
- API root (`rest`): <https://oceandata.sci.gsfc.nasa.gov/> — see the [rest guide](./access-rest.md)
- API documentation: <https://oceancolor.gsfc.nasa.gov/data/download_methods/>
- DOIs minted here start with `10.5067`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/x-netcdf | <https://oceandata.sci.gsfc.nasa.gov/ob/getfile/{filename}> | wget --user={EDL_USER} --password={EDL_PASS} 'https://oceandata.sci.gsfc.nasa.gov/ob/getfile/AQUA_MODIS.20240101.L3m.DAY.CHL.chlor_a.4km.nc' |
| search | GET | text/plain | <https://oceandata.sci.gsfc.nasa.gov/api/file_search/?sensor={sensor}&dtype={level}&sdate={start}&edate={end}&search={pattern}> | curl -b ~/.urs_cookies -c ~/.urs_cookies -L -n 'https://oceandata.sci.gsfc.nasa.gov/api/file_search/?sensor=aqua&dtype=L3m&sdate=2024-01-01&edate=2024-01-31&search=*CHL*' |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [nasa-obpg-prod](https://oceancolor.gsfc.nasa.gov/data/download_methods/) | us-west-2 | public-anon-egress | `MODISA/L3m/CHL/` |
| s3 | [nasa-pace-prod](https://oceancolor.gsfc.nasa.gov/data/pace/) | us-west-2 | public-anon-egress | `PACE_OCI/L2/OC/` |

# Depositing facilities

- **GSFC-OBPG** NASA Goddard Space Flight Center — Ocean Biology Processing Group (primary)

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [MODIS-Aqua Level-3 Mapped Chlorophyll a Concentration (R2022.0)](https://doi.org/10.5067/AQUA/MODIS/L3M/CHL/2022) | netcdf | 2002-07-04–present | n/a |
| [VIIRS-SNPP Level-3 Mapped Ocean Color (R2022.0)](https://doi.org/10.5067/SNPP/VIIRS/L3M/CHL/2022) | netcdf | 2012-01-02–present | n/a |
