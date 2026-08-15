---
type: Data Archive
title: "NEON Data Portal"
description: "Battelle / National Ecological Observatory Network (NSF) — repository holding long-term observatory records."
resource: "https://data.neonscience.org/"
tags: [repository, rest, neon-data-policy]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

NEON publishes ~180 standardized data products (DPID format DP[1-4].YYYYY.NNN) across 81 field sites in 20 domains. Bulk downloads via REST API; AOP rasters in s3://neon-aop-products. Annual RELEASE-YYYY tags issued for citable, versioned data. [via J-A-NEON]

# Access

- Archive home: <https://data.neonscience.org/>
- API root (`rest`): <https://data.neonscience.org/api/v0/> — see the [rest guide](./access-rest.md)
- API documentation: <https://data.neonscience.org/data-api>
- DOIs minted here start with `10.48443`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| catalog | GET | application/json | <https://data.neonscience.org/api/v0/products> | curl https://data.neonscience.org/api/v0/products |
| catalog | GET | application/json | <https://data.neonscience.org/api/v0/products/{productCode}> | curl https://data.neonscience.org/api/v0/products/DP1.10003.001 |
| catalog | GET | application/json | <https://data.neonscience.org/api/v0/releases> | curl https://data.neonscience.org/api/v0/releases |
| catalog | GET | application/json | <https://data.neonscience.org/api/v0/sites> | curl https://data.neonscience.org/api/v0/sites |
| data | GET | application/json | <https://data.neonscience.org/api/v0/data/{productCode}/{siteCode}/{year-month}> | curl https://data.neonscience.org/api/v0/data/DP1.10003.001/HARV/2019-06 |
| data | GET | application/json | <https://data.neonscience.org/api/v0/data/query> | curl 'https://data.neonscience.org/api/v0/data/query?productCode=DP1.10003.001&siteCode=HARV&startDateMonth=2019-01&endDateMonth=2019-12&package=basic&release=RELEASE-2024' |
| human-ui | GET | text/html | <https://data.neonscience.org/data-products/explore?siteCodes={siteCode}> | https://data.neonscience.org/data-products/explore?siteCodes=HARV |
| metadata | GET | application/json | <https://data.neonscience.org/api/v0/sites/{siteCode}> | curl https://data.neonscience.org/api/v0/sites/HARV |
| metadata | GET | application/json | <https://data.neonscience.org/api/v0/locations/{namedLocation}> | curl https://data.neonscience.org/api/v0/locations/HARV_001.basePlot.bgc |
| vocabulary | GET | application/json | <https://data.neonscience.org/api/v0/taxonomy> | curl 'https://data.neonscience.org/api/v0/taxonomy?taxonTypeCode=BIRD' |
| vocabulary | GET | application/json | <https://data.neonscience.org/api/v0/samples/supportedClasses> | curl 'https://data.neonscience.org/api/v0/samples/supportedClasses' |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [neon-aop-products](https://www.neonscience.org/data-collection/airborne-remote-sensing) | us-west-2 | public-read | `2019/FullSite/D14/2019_JORN_3/L3/DiscreteLidar/CanopyHeightModelGtif/` |
| s3 | [neon-prod-pub-1](https://data.neonscience.org/data-products/explore) | us-west-2 | public-read | `—` |

# Depositing facilities

- **ABBY** Abby Road NEON Site (primary)
- **ARIK** Arikaree River NEON Site (primary)
- **BAR** Bartlett Experimental Forest (primary)
- **BLDE** Blacktail Deer Creek NEON Site (primary)
- **BLAN** Blandy Experimental Farm NEON Site (primary)
- **BLUE** Blue River NEON Site (primary)
- **GUAN-SF** Bosque Estatal de Guánica (Guánica State Forest) (primary)
- **CARI** Caribou Creek NEON Site (primary)
- **BONA** Caribou-Poker Creeks Research Watershed (Bonanza Creek) NEON Site (primary)
- **CPER** Central Plains Experimental Range NEON Site (primary)
- **COMO** Como Creek NEON Site (primary)
- **CRAM** Crampton Lake NEON Site (primary)
- **DCFS** Dakota Coteau Field Site NEON Site (primary)
- **DELA** Dead Lake NEON Site (primary)
- **DEJU** Delta Junction NEON Site (primary)
- **DSNY-TNC** Disney Wilderness Preserve (primary)
- **DSNY** Disney Wilderness Preserve NEON Site (primary)
- **FLNT** Flint River NEON Site (primary)
- **GRSM** Great Smoky Mountains National Park — Twin Creeks NEON Site (primary)
- **GUAN** Guánica Forest NEON Site (primary)
- **HARV** Harvard Forest & Quabbin Watershed NEON Site (primary)
- **HEAL** Healy NEON Site (primary)
- **JERC** Jones Center at Ichauway NEON Site (primary)
- **JORN** Jornada Experimental Range NEON Site (primary)
- **KING** Kings Creek NEON Site (primary)
- **KONA** Konza Prairie Biological Station — Agricultural NEON Site (primary)
- **LAJA** Lajas Experimental Station NEON Site (primary)
- **BARC** Lake Barco NEON Site (primary)
- **SUGG** Lake Suggs NEON Site (primary)
- **LECO** LeConte Creek NEON Site (primary)
- **LENO** Lenoir Landing NEON Site (primary)
- **LEWI** Lewis Run NEON Site (primary)
- **LIRO** Little Rock Lake NEON Site (primary)
- **HOPB** Lower Hop Brook NEON Site (primary)
- **TEAK** Lower Teakettle NEON Site (primary)
- **TOMB** Lower Tombigbee River NEON Site (primary)
- **CLBJ** Lyndon B. Johnson National Grassland NEON Site (primary)
- **MART** Martha Creek NEON Site (primary)
- **KLEMME-RRS** Marvin Klemme Range Research Station (primary)
- **OAES** Marvin Klemme Range Research Station NEON Site (primary)
- **MAYF** Mayfield Creek NEON Site (primary)
- **MCDI** McDiffett Creek NEON Site (primary)
- **MCRA** McRae Creek NEON Site (primary)
- **MOAB** Moab NEON Site (primary)
- **MLBS** Mountain Lake Biological Station NEON Site (primary)
- **NIWO** Niwot Ridge NEON Site (primary)
- **STER** North Sterling NEON Site (primary)
- **NOGP** Northern Great Plains Research Laboratory NEON Site (primary)
- **ORNL** Oak Ridge NEON Site (primary)
- **OKSR** Oksrukuyik Creek NEON Site (primary)
- **ONAQ** Onaqui NEON Site (primary)
- **OSBS** Ordway-Swisher Biological Station NEON Site (primary)
- **POSE** Posey Creek NEON Site (primary)
- **PRLA** Prairie Lake NEON Site (primary)
- **PRPO** Prairie Pothole NEON Site (primary)
- **PRIN** Pringle Creek NEON Site (primary)
- **PUUM** Pu'u Maka'ala Natural Area Reserve NEON Site (primary)
- **REDB** Red Butte Creek NEON Site (primary)
- **RMNP** Rocky Mountain National Park — CASTNET NEON Site (primary)
- **CUPE** Río Cupeyes NEON Site (primary)
- **GUIL** Río Guilarte NEON Site (primary)
- **SJER** San Joaquin Experimental Range NEON Site (primary)
- **SRER** Santa Rita Experimental Range NEON Site (primary)
- **SCBI-NZP** Smithsonian Conservation Biology Institute (primary)
- **SCBI** Smithsonian Conservation Biology Institute NEON Site (primary)
- **SERC** Smithsonian Environmental Research Center (primary)
- **SOAP** Soaproot Saddle NEON Site (primary)
- **STEI** Steigerwaldt-Chequamegon NEON Site (primary)
- **SYCA** Sycamore Creek NEON Site (primary)
- **TALL** Talladega National Forest NEON Site (primary)
- **TECR** Teakettle Creek NEON Site (primary)
- **TOOL** Toolik Field Station NEON Site (primary)
- **TOOK** Toolik Lake NEON Site (primary)
- **TREE** Treehaven NEON Site (primary)
- **UKFS** University of Kansas Field Station NEON Site (primary)
- **UNDE** University of Notre Dame Environmental Research Center NEON Site (primary)
- **BIGC** Upper Big Creek NEON Site (primary)
- **BARR** Utqiaġvik (Barrow Environmental Observatory) NEON Site (primary)
- **WALK** Walker Branch NEON Site (primary)
- **WLOU** West St Louis Creek NEON Site (primary)
- **WREF** Wind River Experimental Forest NEON Site (primary)
- **WOOD** Woodworth NEON Site (primary)
- **YELL** Yellowstone National Park — Northern Range NEON Site (primary)
- **BLAN-EF** Blandy Experimental Farm / State Arboretum of Virginia (secondary)
- **GRSM-NP** Great Smoky Mountains National Park (Twin Creeks Science and Education Center) (secondary)
- **JIE-CTR** Jones Center at Ichauway (secondary)
- **LBJ-NG** Lyndon B. Johnson National Grassland (secondary)
- **MLBS-BS** Mountain Lake Biological Station (secondary)
- **USFWS-NPWRC** Northern Prairie Wildlife Research Center (secondary)
- **ORNL-NERP** Oak Ridge National Environmental Research Park (secondary)
- **OSBS-BS** Ordway-Swisher Biological Station (secondary)
- **SJER-ER** San Joaquin Experimental Range (secondary)
- **SYCA-LTER** Sycamore Creek Long-Term Stream-Ecology Site (ASU) (secondary)
- **TALL-NF** Talladega National Forest (secondary)
- **TEAK-EF** Teakettle Experimental Forest (secondary)
- **USGS-CRS-MOAB** USGS Canyonlands Research Station (Moab) (secondary)
- **KUFS-FS** University of Kansas Field Station (secondary)
- **WREF-EF** Wind River Experimental Forest (secondary)

# Data products

146 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [2D wind speed and direction](https://data.neonscience.org/data-products/DP1.00001.001) | csv | 2014-01-01–present | n/a |
| [ABBY eddy-covariance bundle (DP4.00200.001)](https://data.neonscience.org/data-products/explore?siteCodes=ABBY&products=DP4.00200.001) | hdf5 | 2017-01-01–present | n/a |
| [ARIK stream sensor data (DP1.20053.001)](https://data.neonscience.org/data-products/explore?siteCodes=ARIK&products=DP1.20053.001) | csv | 2017-01-01–present | n/a |
| [Air pressure](https://data.neonscience.org/data-products/DP1.00004.001) | csv | 2014-01-01–present | n/a |
| [Aquatic plant, bryophyte, lichen, and macroalgae clip harvest](https://data.neonscience.org/data-products/DP1.20066.001) | csv | 2015-01-01–present | n/a |
| [BARC stream sensor data (DP1.20053.001)](https://data.neonscience.org/data-products/explore?siteCodes=BARC&products=DP1.20053.001) | csv | 2017-01-01–present | n/a |
| [BARR eddy-covariance bundle (DP4.00200.001)](https://data.neonscience.org/data-products/explore?siteCodes=BARR&products=DP4.00200.001) | hdf5 | 2017-01-01–present | n/a |
| [BART eddy-covariance bundle (DP4.00200.001)](https://data.neonscience.org/data-products/explore?siteCodes=BART&products=DP4.00200.001) | hdf5 | 2017-01-01–present | n/a |
| [BIGC stream sensor data (DP1.20053.001)](https://data.neonscience.org/data-products/explore?siteCodes=BIGC&products=DP1.20053.001) | csv | 2018-01-01–present | n/a |
| [BLAN eddy-covariance bundle (DP4.00200.001)](https://data.neonscience.org/data-products/explore?siteCodes=BLAN&products=DP4.00200.001) | hdf5 | 2018-01-01–present | n/a |
