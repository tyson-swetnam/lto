---
type: Data Archive
title: "Environmental Data Initiative Repository"
description: "Environmental Data Initiative (EDI) / NSF — repository holding long-term observatory records."
resource: "https://portal.edirepository.org/"
tags: [repository, rest, edi-data-policy]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

PASTA REST API; EML 2.2 metadata; per-LTER 'scope' namespace pattern knb-lter-<acronym>. Hosted by University of Wisconsin-Madison and University of New Mexico. retrieved_at=2026-05-05; agent=J-A-EDI [via J-A-EDI]

# Access

- Archive home: <https://portal.edirepository.org/>
- API root (`rest`): <https://pasta.lternet.edu/package/> — see the [rest guide](./access-rest.md)
- API documentation: <https://pastaplus-core.readthedocs.io/>
- DOIs minted here start with `10.6073`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://pasta.lternet.edu/package/data/eml/{scope}/{identifier}/{revision}/{entityId}> | curl -O https://pasta.lternet.edu/package/data/eml/knb-lter-hbr/2/20/abcdef0123456789abcdef0123456789 |
| doi-resolution | GET | text/plain | <https://pasta.lternet.edu/package/doi/eml/{scope}/{identifier}/{revision}> | curl https://pasta.lternet.edu/package/doi/eml/knb-lter-hbr/2/20 |
| listing | GET | text/plain | <https://pasta.lternet.edu/package/eml/{scope}> | curl https://pasta.lternet.edu/package/eml/knb-lter-hbr |
| metadata | GET | application/xml | <https://pasta.lternet.edu/package/eml/{scope}/{identifier}/{revision}> | curl https://pasta.lternet.edu/package/eml/knb-lter-hbr/2/20 |
| search | GET | application/xml | <https://pasta.lternet.edu/package/search/eml?q={query}&fl=packageid,title,doi,pubdate&rows=100> | curl 'https://pasta.lternet.edu/package/search/eml?q=scope:knb-lter-hbr&fl=packageid,title,doi&rows=50' |

# Depositing facilities

- **ARC** Arctic LTER (Toolik Field Station) (primary)
- **BES** Baltimore Ecosystem Study LTER (primary)
- **BLE** Beaufort Lagoon Ecosystems LTER (primary)
- **BEN** Bent Creek Experimental Forest (primary)
- **BLAN-EF** Blandy Experimental Farm / State Arboretum of Virginia (primary)
- **BNZ-CPCRW** Bonanza Creek LTER Caribou-Poker Creeks Permafrost Sites (primary)
- **CCE** California Current Ecosystem LTER (primary)
- **CDR** Cedar Creek Ecosystem Science Reserve LTER (primary)
- **CAP** Central Arizona-Phoenix LTER (primary)
- **CWT** Coweeta Hydrologic Laboratory (primary)
- **FCE** Florida Coastal Everglades LTER (primary)
- **GCE** Georgia Coastal Ecosystems LTER (primary)
- **AND** H.J. Andrews Experimental Forest (primary)
- **HFR** Harvard Forest LTER (primary)
- **JIE-CTR** Jones Center at Ichauway (primary)
- **JRN** Jornada Basin LTER (primary)
- **KBS** Kellogg Biological Station LTAR (primary)
- **KNZ** Konza Prairie Biological Station LTER (primary)
- **LUQ** Luquillo Experimental Forest (primary)
- **MCM** McMurdo Dry Valleys LTER (primary)
- **MSP** Minneapolis-St Paul Urban LTER (primary)
- **MGCF** Mojave Global Change Facility (LTREB) (primary)
- **MCR** Moorea Coral Reef LTER (primary)
- **MLBS-BS** Mountain Lake Biological Station (primary)
- **NWT-CRY** Niwot Ridge LTER Cryosphere Instrumentation (primary)
- **LTER** North Temperate Lakes LTER (primary)
- **NES** Northeast U.S. Shelf LTER (primary)
- **LTER** Northern Gulf of Alaska LTER (primary)
- **OSBS-BS** Ordway-Swisher Biological Station (primary)
- **PAL** Palmer Station LTER (primary)
- **PIE** Plum Island Ecosystems LTER (primary)
- **SBC** Santa Barbara Coastal LTER (primary)
- **SEV** Sevilleta LTER (primary)
- **SYCA-LTER** Sycamore Creek Long-Term Stream-Ecology Site (ASU) (primary)
- **TFS** Toolik Field Station (primary)
- **KUFS-FS** University of Kansas Field Station (primary)
- **VCR** Virginia Coast Reserve LTER (primary)
- **IUTAH-GAMUT-RB** iUTAH GAMUT Red Butte Creek Watershed Observatory (primary)
- **CLSA-LTER-LIKE** Cottonwood Lake Study Area (secondary)
- **EAST-RIVER** East River Watershed Long-Term Critical Zone Observatory (LTREB) (secondary)
- **IMN** Imnavait Creek Tussock-Tundra Watershed (secondary)
- **KREW-EW** Kings River Experimental Watersheds (secondary)
- **SCBI-NZP** Smithsonian Conservation Biology Institute (secondary)
- **WREF-EF** Wind River Experimental Forest (secondary)
- **YNP-LT** Yellowstone National Park — Long-Term Ecological Monitoring (secondary)

# Data products

84 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [Arctic LTER: Toolik Lake Long-Term Limnology and Inlet Stream Records](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-arc.10220) | csv | 1975-01-01–present | n/a |
| [Arctic LTER: Tussock Tundra Long-Term Experiment, Aboveground Biomass and Nutrients](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-arc.20003) | csv | 1981-01-01–present | n/a |
| [BES LTER: Long-Term Forest Plot Tree Census, Baltimore Urban Forest](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-bes.598) | csv | 1998-01-01–present | n/a |
| [BES LTER: Stream Water Chemistry, Baltimore Watershed Network](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-bes.1057) | csv | 1998-01-01–present | n/a |
| [BLE LTER: Lagoon Water-Column Nutrients and Dissolved Organic Matter](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-ble.18) | csv | 2018-01-01–present | n/a |
| [BLE LTER: Time-Series Lagoon Hydrography, Beaufort Sea Coastal Stations](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-ble.10) | csv | 2018-01-01–present | n/a |
| [Bonanza Creek LTER: Boreal Climate Records, Caribou-Poker Creeks and Bonanza Creek Stations](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-bnz.412) | csv | 1988-01-01–present | n/a |
| [Bonanza Creek LTER: Long-Term Tree-Ring Series, Boreal Floodplain and Upland Stands](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-bnz.501) | csv | 1900-01-01–present | n/a |
| [CAP LTER: Long-Term Bird Surveys, Phoenix Metro Point Counts](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-cap.46) | csv | 2000-01-01–present | n/a |
| [CAP LTER: Phoenix Area Social Survey - Long-Term Household Environmental Attitudes](https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-cap.628) | csv | 2001-01-01–present | n/a |
