---
type: Data Archive
title: "Long-Term Agroecosystem Research (LTAR) Network Data"
description: "USDA Agricultural Research Service — network holding long-term observatory records."
resource: "https://ltar.ars.usda.gov/data/"
tags: [network, ckan, usda-ars]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

LTAR Network of 18 sites; each site publishes datasets to Ag Data Commons under a per-site collection. Common Experiment (CE) and Long-Term Agroecosystem Research Network ESIP THREDDS provide multi-site harmonized products. retrieved_at=2026-05-06; agent=J-A-USDA [via J-A-USDA]

# Access

- Archive home: <https://ltar.ars.usda.gov/data/>
- API root (`ckan`): <https://api.figshare.com/v2> — see the [ckan guide](./access-ckan.md)
- API documentation: <https://ltar.ars.usda.gov/data/>
- DOIs minted here start with `10.15482`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| landing-page | GET | text/html | <https://ltar.ars.usda.gov/data/> | curl https://ltar.ars.usda.gov/data/ |
| search | POST | application/json | <https://api.figshare.com/v2/articles/search> | curl -H 'Content-Type: application/json' -d '{"search_for":"Walnut Gulch","limit":3}' https://api.figshare.com/v2/articles/search |

# Depositing facilities

- **ARCH-UF** Archbold-University of Florida Subtropical Agroecosystem LTAR (primary)
- **CMRB** Central Mississippi River Basin LTAR (primary)
- **CPER** Central Plains Experimental Range LTAR (primary)
- **ECB** Eastern Corn Belt LTAR (primary)
- **GB** Great Basin LTAR (primary)
- **GACP** Gulf Atlantic Coastal Plain LTAR (primary)
- **JER** Jornada Experimental Range LTAR (primary)
- **KBS** Kellogg Biological Station LTAR (primary)
- **LCB** Lower Chesapeake Bay LTAR (primary)
- **LMRB** Lower Mississippi River Basin LTAR (primary)
- **NP** Northern Plains LTAR (primary)
- **PRHPA** Platte River-High Plains Aquifer LTAR (primary)
- **CAF** R.J. Cook Agronomy Farm LTAR (primary)
- **RCEW** Reynolds Creek Experimental Watershed LTAR (primary)
- **SP** Southern Plains LTAR (primary)
- **TXG** Texas Gulf LTAR (primary)
- **UCB** Upper Chesapeake Bay LTAR (primary)
- **UMRB** Upper Mississippi River Basin LTAR (primary)
- **WGEW** Walnut Gulch Experimental Watershed LTAR (primary)
- **Mead-NEB** Mead UNL Carbon Sequestration / NEB Eddy-Flux Site (secondary)

# Data products

26 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Archbold-UF Subtropical Agroecosystem LTAR Common Experiment - Buck Island Ranch grazinglands, water quality, livestock](https://ltar.ars.usda.gov/sites/archbold-university-of-florida-subtropical-agroecosystem/) | csv | 2014-01-01–present | n/a |
| [Central Mississippi River Basin LTAR Common Experiment - Cropping systems, runoff, soil erosion](https://ltar.ars.usda.gov/sites/central-mississippi-river-basin/) | csv | 2014-01-01–present | n/a |
| [Central Plains Experimental Range LTAR Common Experiment - Grazing, vegetation, livestock, soil](https://ltar.ars.usda.gov/sites/central-plains-experimental-range/) | csv | 2014-01-01–present | n/a |
| [Central Plains Experimental Range Long-Term Grazing Treatments Vegetation and Cattle Performance](https://agdatacommons.nal.usda.gov/search?q=Central+Plains+grazing) | csv | 1939-01-01–present | n/a |
| [Cook Agronomy Farm Long-term Soil Properties and Crop Yield Database](https://agdatacommons.nal.usda.gov/search?q=Cook+Agronomy+Farm) | csv | 1998-01-01–present | n/a |
| [Eastern Corn Belt LTAR Common Experiment - Cropping systems, water quality, GHG fluxes](https://ltar.ars.usda.gov/sites/eastern-corn-belt/) | csv | 2014-01-01–present | n/a |
| [Great Basin LTAR Common Experiment - Sagebrush-steppe meteorology, vegetation, livestock](https://ltar.ars.usda.gov/sites/great-basin/) | csv | 2014-01-01–present | n/a |
| [Gulf Atlantic Coastal Plain LTAR Common Experiment - Cropping systems, soil, water quality](https://ltar.ars.usda.gov/sites/gulf-atlantic-coastal-plain/) | csv | 2014-01-01–present | n/a |
| [Jornada Experimental Range NPP Quadrat Data, 1989-present](https://agdatacommons.nal.usda.gov/search?q=Jornada+NPP) | csv | 1989-01-01–present | n/a |
| [Jornada LTAR Common Experiment - Long-term meteorology, vegetation, soil, livestock](https://ltar.ars.usda.gov/sites/jornada/) | csv | 2014-01-01–present | n/a |
