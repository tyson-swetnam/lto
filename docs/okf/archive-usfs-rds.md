---
type: Data Archive
title: "USFS Research Data Archive"
description: "USDA Forest Service / Rocky Mountain Research Station — repository holding long-term observatory records."
resource: "https://www.fs.usda.gov/rds/archive/"
tags: [repository, rest, public-domain-us]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

USFS RDS issues citable DOIs of form 10.2737/RDS-YYYY-NNNN for forest-research datasets including Experimental Forest and Range (EFR) network releases. CSV + GeoTIFF + shapefile distributions; persistent landing pages at https://www.fs.usda.gov/rds/archive/Catalog/<RDS-id>. retrieved_at=2026-05-06; agent=J-A-USDA [via J-A-USDA]

# Access

- Archive home: <https://www.fs.usda.gov/rds/archive/>
- API root (`rest`): <https://www.fs.usda.gov/rds/archive/api/> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.fs.usda.gov/rds/archive/webdocs/help/RDA_data_documentation.shtml>
- DOIs minted here start with `10.2737`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| doi-resolution | GET | text/html | <https://doi.org/10.2737/{RDS-id}> | curl -L https://doi.org/10.2737/RDS-2017-0023 |
| landing-page | GET | text/html | <https://www.fs.usda.gov/rds/archive/Catalog/{RDS-id}> | curl https://www.fs.usda.gov/rds/archive/Catalog/RDS-2017-0023 |
| metadata | GET | application/json | <https://www.fs.usda.gov/rds/archive/api/{RDS-id}> | curl 'https://www.fs.usda.gov/rds/archive/api/RDS-2017-0023' |
| search | GET | text/html | <https://www.fs.usda.gov/rds/archive/Catalog?searchTerm={query}> | curl 'https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Hubbard+Brook' |

# Depositing facilities

- **BAR** Bartlett Experimental Forest (primary)
- **BEN** Bent Creek Experimental Forest (primary)
- **CAL** Calhoun Experimental Forest (primary)
- **CSP** Caspar Creek Experimental Watershed (primary)
- **CWT** Coweeta Hydrologic Laboratory (primary)
- **FER** Fernow Experimental Forest (primary)
- **FEF** Fraser Experimental Forest Snow Research Site (primary)
- **GLEES** Glacier Lakes Ecosystem Experiments Site (primary)
- **AND** H.J. Andrews Experimental Forest (primary)
- **KREW-EW** Kings River Experimental Watersheds (primary)
- **LUQ** Luquillo Experimental Forest (primary)
- **LBJ-NG** Lyndon B. Johnson National Grassland (primary)
- **MAN** Manitou Experimental Forest (primary)
- **MAR** Marcell Experimental Forest (primary)
- **PEF** Penobscot Experimental Forest (primary)
- **PRI** Priest River Experimental Forest (primary)
- **SAG** Sagehen Creek Experimental Forest (primary)
- **SDM** San Dimas Experimental Forest (primary)
- **SJER-ER** San Joaquin Experimental Range (primary)
- **SAN** Santee Experimental Forest (primary)
- **TALL-NF** Talladega National Forest (primary)
- **TEAK-EF** Teakettle Experimental Forest (primary)
- **WREF-EF** Wind River Experimental Forest (primary)
- **WREF** Wind River Experimental Forest NEON Site (primary)
- **HOW** Howland Forest Research Site (secondary)

# Data products

28 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Bartlett Experimental Forest permanent forest inventory plots, 1931-present](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Bartlett) | csv | 1931-01-01–present | n/a |
| [Bent Creek Experimental Forest hardwood silviculture and oak regeneration plots](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Bent+Creek) | csv | 1955-01-01–present | n/a |
| [Bonanza Creek Experimental Forest forest dynamics permanent-plot data](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Bonanza+Creek) | csv | 1989-01-01–present | n/a |
| [Calhoun Long-Term Soil Ecosystem Experiment soil cores](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Calhoun) | csv | 1962-01-01–present | n/a |
| [Caspar Creek Experimental Watersheds streamflow and sediment data](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Caspar+Creek) | csv | 1962-01-01–present | n/a |
| [Coweeta Hydrologic Laboratory Climate and Streamflow Data](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Coweeta) | csv | 1934-01-01–present | n/a |
| [Crossett Experimental Forest Good Farm and Methods of Cutting compartments, 1937-present](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Crossett) | csv | 1937-01-01–present | n/a |
| [Discharge in gaged mountain streams in the H.J. Andrews Experimental Forest](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Andrews+streamflow) | csv | 1949-01-01–present | n/a |
| [Fernow Experimental Forest streamflow + chemistry watershed data](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Fernow) | csv | 1951-01-01–present | n/a |
| [Fraser Experimental Forest watershed streamflow, snow, and climate data](https://www.fs.usda.gov/rds/archive/Catalog?searchTerm=Fraser+Experimental) | csv | 1937-01-01–present | n/a |
