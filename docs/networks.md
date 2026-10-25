# Networks

The controlled vocabulary for `networks` is `schema/vocab/networks.csv`
(served to the browser as `public/vocab/networks.csv`). It holds 66
networks, each keyed by a lower-case slug. Facilities join to networks
through the `network_membership` table, which can also carry a role
(`host` or `partner`). The Network filter in the side panel lists every
vocabulary entry as "ACRONYM — full name". Some polygon overlays each
draw one network's membership roll: NERR reserves, NEP programs, marine
sanctuaries, marine monuments and NPS coastal units. While a network is
selected in the filter, those overlays stay on only if they belong to that
network. The NEON sites overlay hides while any sphere, ecosystem,
life-zone, network or facility-type filter is set, because the filtered
NEON points already show the result. The scope lens, country, research
area, the ≥10y toggle and the established-year range leave it on. Turning an overlay back on
by hand keeps it on until those filters are cleared.

As of 2026-10-24 there are 579 membership rows. 57 of the 66 networks have
at least one member. 399 of the 448 facilities belong to one or more
networks. The other 49 belong to none, and you find them by sphere, type
or research area instead.

The **Facilities** column counts facility records in this catalogue as of
2026-10-24. It is not the size of the network. A network's own site list
can be longer than what the catalogue holds. A zero means only that no catalogued
facility carries that tag yet. The vocabulary has no sphere column. The
grouping below is only to make the list easier to read.

## Atmosphere

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `noaa-gml` | NOAA Global Monitoring Laboratory baseline observatory network | us-national | 6 | <https://gml.noaa.gov> |
| `nadp` | National Atmospheric Deposition Program | us-national | 18 | <https://nadp.slh.wisc.edu> |
| `nadp-ntn` | NADP National Trends Network | us-national | 4 | <https://nadp.slh.wisc.edu/networks/national-trends-network/> |
| `nadp-mdn` | NADP Mercury Deposition Network | us-national | 0 | <https://nadp.slh.wisc.edu/networks/mercury-deposition-network/> |
| `nadp-airmon` | NADP Atmospheric Integrated Research Monitoring Network | us-national | 0 | <https://nadp.slh.wisc.edu/networks/atmospheric-integrated-research-monitoring-network/> |
| `castnet` | EPA Clean Air Status and Trends Network | us-national | 6 | <https://www.epa.gov/castnet> |
| `improve` | Interagency Monitoring of Protected Visual Environments | us-national | 4 | <http://vista.cira.colostate.edu/improve/> |
| `surfrad` | NOAA Surface Radiation Budget Network | us-national | 2 | <https://gml.noaa.gov/grad/surfrad/> |
| `asos` | Automated Surface Observing System | us-national | 0 | <https://www.weather.gov/asos> |
| `arm` | DOE Atmospheric Radiation Measurement user facility | us-national | 3 | <https://www.arm.gov> |
| `ameriflux` | AmeriFlux eddy-covariance flux network | us-national | 35 | <https://ameriflux.lbl.gov> |
| `fluxnet` | Global eddy-covariance synthesis network | international | 9 | <https://fluxnet.org> |
| `aeronet` | NASA Aerosol Robotic Network | international | 5 | <https://aeronet.gsfc.nasa.gov> |
| `tccon` | Total Carbon Column Observing Network | international | 3 | <https://tccon-wiki.caltech.edu> |
| `pandora` | Pandonia Global Network for atmospheric trace gases | international | 1 | <https://www.pandonia-global-network.org> |
| `gaw` | WMO Global Atmosphere Watch | international | 5 | <https://gaw.kishou.go.jp> |

## Cryosphere

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `usgs-benchmark-glaciers` | USGS Benchmark Glacier Project | us-national | 5 | <https://www.usgs.gov/programs/climate-research-and-development-program/science/usgs-benchmark-glacier-project> |
| `snotel` | NRCS Snow Telemetry / SNOLITE network | us-national | 12 | <https://www.nrcs.usda.gov/wps/portal/wcc/home/> |
| `crrel` | US Army Cold Regions Research and Engineering Laboratory | us-national | 1 | <https://www.erdc.usace.army.mil/Locations/CRREL> |

## Terrestrial / Ecological

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `lter` | Long-Term Ecological Research Network | us-national | 51 | <https://lternet.edu> |
| `lter-site` | Long-Term Ecological Research member site | us-regional | 2 | <https://lternet.edu/site/> |
| `neon` | National Ecological Observatory Network | us-national | 82 | <https://www.neonscience.org> |
| `ltreb` | Long-term Research in Environmental Biology | us-national | 23 | <https://www.nsf.gov/funding/opportunities/long-term-research-environmental-biology-ltreb> |
| `usfs-rna-ef` | USFS Research Natural Area / Experimental Forest network | us-national | 36 | <https://www.fs.usda.gov/research/rmrs/research-natural-areas> |
| `nps-im` | NPS Inventory and Monitoring Program | us-national | 16 | <https://www.nps.gov/im/> |
| `ofs` | Organization of Biological Field Stations | us-national | 16 | <https://www.obfs.org> |
| `nrs` | University of California Natural Reserve System | us-regional | 3 | <https://ucnrs.org> |
| `ltrr` | Laboratory of Tree-Ring Research / ITRDB | us-national | 1 | <https://ltrr.arizona.edu> |

`lter-site` is a second tag on 2 facilities that also carry `lter`: Santa
Barbara Coastal LTER and the UW Trout Lake Station. It came in with the
COMPASS synthesis-networks import; the eight LTER site duplicates that import
created were merged into their LTER site rows on 2026-10-24, and the tag was
not carried over. To get every LTER record, filter on `lter`.

## Agriculture

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `ltar` | USDA-ARS Long-Term Agroecosystem Research network | us-national | 26 | <https://ltar.ars.usda.gov> |
| `ars-lt-experiments` | USDA-ARS long-term agricultural experiments | us-national | 8 | <https://www.ars.usda.gov> |
| `scan` | NRCS Soil Climate Analysis Network | us-national | 11 | <https://www.nrcs.usda.gov/wps/portal/wcc/home/aboutScan/> |
| `climate-hubs` | USDA Regional Climate Hubs | us-national | 10 | <https://www.climatehubs.usda.gov> |

## Arid

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `arid-unm` | Accelerating Resilience Innovations in Drylands | us-regional | 12 | <https://arid.unm.edu> |

`arid-unm` covers UNM's ARID Institute and its partners, and it defines the
ARID scope lens. See [ARID & New Mexico](./arid.md).

## Ocean & Estuarine

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `ioos` | U.S. Integrated Ocean Observing System | us-national | 15 | <https://ioos.us> |
| `ooi` | Ocean Observatories Initiative | us-national | 3 | <https://oceanobservatories.org> |
| `goos` | Global Ocean Observing System | international | 6 | <https://goosocean.org> |
| `iocaribe` | IOC Sub-Commission for the Caribbean and Adjacent Regions | international | 3 | <https://iocaribe.ioc-unesco.org> |
| `onc` | Ocean Networks Canada | canada-national | 0 | <https://www.oceannetworks.ca> |
| `nerrs` | National Estuarine Research Reserve System | us-national | 30 | <https://coast.noaa.gov/nerrs> |
| `nep` | National Estuary Program | us-national | 27 | <https://www.epa.gov/nep> |
| `nms` | National Marine Sanctuary System | us-national | 5 | <https://sanctuaries.noaa.gov> |
| `marine-monument` | U.S. Marine National Monument | us-national | 0 | <https://www.fws.gov/program/national-wildlife-refuge-system> |
| `nps-coastal` | National Park Service Coastal Units | us-national | 0 | <https://www.nps.gov/> |
| `sentinel-site` | NOAA Sentinel Site Program | us-national | 3 | <https://oceanservice.noaa.gov/sentinel-sites/> |
| `seagrant` | National Sea Grant College Program | us-national | 0 | <https://seagrant.noaa.gov> |
| `naml` | National Association of Marine Laboratories | us-national | 1 | <https://www.naml.org> |
| `marinegeo` | Tennenbaum Marine Observatories Network / Marine Global Earth Observatory | international | 6 | <https://marinegeo.si.edu> |

## IOOS Regional Associations

The vocabulary holds ten IOOS Regional Associations. GLOS (Great Lakes)
has no entry, and AOOS has no tagged facility yet.

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `aoos` | Alaska Ocean Observing System | us-regional | 0 | <https://aoos.org> |
| `caricoos` | Caribbean Coastal Ocean Observing System | us-regional | 2 | <https://caricoos.org> |
| `cencoos` | Central and Northern California Ocean Observing System | us-regional | 3 | <https://cencoos.org> |
| `gcoos` | Gulf of Mexico Coastal Ocean Observing System | us-regional | 2 | <https://gcoos.org> |
| `maracoos` | Mid-Atlantic Regional Association Coastal Ocean Observing System | us-regional | 1 | <https://maracoos.org> |
| `nanoos` | Northwest Association of Networked Ocean Observing Systems | us-regional | 2 | <https://nanoos.org> |
| `neracoos` | Northeastern Regional Association of Coastal Ocean Observing Systems | us-regional | 2 | <https://neracoos.org> |
| `pacioos` | Pacific Islands Ocean Observing System | us-regional | 2 | <https://pacioos.org> |
| `sccoos` | Southern California Coastal Ocean Observing System | us-regional | 2 | <https://sccoos.org> |
| `secoora` | Southeast Coastal Ocean Observing Regional Association | us-regional | 2 | <https://secoora.org> |

## Freshwater

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `nwis` | USGS National Water Information System | us-national | 12 | <https://waterdata.usgs.gov/nwis> |
| `usgs-webb` | USGS Water Energy and Biogeochemical Budgets network | us-national | 5 | <https://water.usgs.gov/webb/> |
| `usgs-hbn` | USGS Hydrologic Benchmark Network | us-national | 3 | <https://water.usgs.gov/nasqan/progdocs/factsheets/hbnfact/hbnfactsheet.html> |
| `gleon` | Global Lake Ecological Observatory Network | international | 6 | <https://gleon.org> |

## Protected-area designations and administrative units

| Slug | Full name | Level | Facilities | URL |
|---|---|---|---:|---|
| `mab-us` | UNESCO Man and the Biosphere — US Biosphere Reserves | us-national | 11 | <https://en.unesco.org/biosphere/eu-na> |
| `ramsar` | Ramsar Convention on Wetlands of International Importance | international | 2 | <https://www.ramsar.org> |
| `nwrs` | National Wildlife Refuge System | us-national | 5 | <https://www.fws.gov/program/national-wildlife-refuge-system> |
| `nwps` | National Wilderness Preservation System | us-national | 0 | <https://www.wilderness.net> |
| `epa-region` | U.S. EPA Administrative Regions | us-national | 2 | <https://www.epa.gov/aboutepa/regional-and-geographic-offices> |
