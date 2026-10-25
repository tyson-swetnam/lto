# The seven spheres

`lto` files facilities under a **primary sphere** and zero or more
**secondary spheres**. Some places that several networks share appear as
several records, one for each network's installation, and each record
carries its own primary sphere. Hubbard Brook, for example, appears as
Watershed 6 (freshwater-primary, terrestrial secondary) and as its NADP
NTN deposition site (atmosphere-primary). Niwot Ridge appears as a NEON
site (terrestrial-primary, atmosphere secondary), as an LTER cryosphere
instrumentation record and a SNOTEL station (both cryosphere-primary),
and as a forest flux tower (atmosphere-primary). Other shared places are
a single record tagged with every network: Coweeta, Luquillo and
Sevilleta each appear once.

The model launched with six spheres; **Arid** was split out of Terrestrial
in August 2026 so dryland research sites — a coherent research community
with its own LTERs, NEON domains, and rangeland networks — stopped being
invisible inside Terrestrial, the sphere with the most tagged records.

As of 2026-10-25 the catalogue's 446 facilities break down like this:

| Sphere | Primary | Tagged in any role |
|---|---:|---:|
| Aquatic — Ocean & Estuarine | 142 | 149 |
| Terrestrial / Ecological | 112 | 286 |
| Aquatic — Freshwater | 62 | 125 |
| Agriculture | 59 | 66 |
| Cryosphere | 31 | 55 |
| Atmosphere | 23 | 99 |
| Arid | 11 | 31 |

Six facilities have no primary sphere. They are ARID Institute partner
programmes at UNM, such as the Utton Transboundary Resources Center and
the Southwest Environmental Finance Center, whose work is policy, finance
and health rather than a field record (see [ARID & New Mexico](./arid.md)).

By default the map colours each point by its primary sphere (the legend's
**By primary sphere** option); points with no primary sphere are slate.
Once the database has loaded, the **Sphere** filter matches any role, so
choosing Arid also shows the rangeland sites that carry arid as a
secondary sphere. Before that, the quick-loading first view matches the
primary sphere only.

## Atmosphere

Long-term observatories of atmospheric composition, deposition, radiation,
and trace gases.

- **Anchor networks**: NOAA Global Monitoring Laboratory (GML), NADP,
  AmeriFlux, DOE ARM, CASTNET, IMPROVE, SURFRAD, TCCON, AERONET, Pandora.
- **Landmark sites**: Mauna Loa Observatory (HI), Barrow Atmospheric
  Baseline Observatory (Utqiagvik, AK), American Samoa Observatory,
  ARM Southern Great Plains (OK), WLEF / Park Falls Tall Tower (WI).
- **Cross-sphere ties**: NADP NTN sites are co-located with LTER / EFR
  hosts (Hubbard Brook, H.J. Andrews, Konza), each as its own
  atmosphere-primary record. Most AmeriFlux flux towers also carry a
  terrestrial tag.

## Cryosphere

Glaciers, snow, sea-ice, and permafrost.

- **Anchor networks**: USGS Benchmark Glaciers, NRCS SNOTEL, CRREL,
  NSIDC sea-ice mass balance.
- **Landmark sites**: South Cascade Glacier (WA), Wolverine Glacier (AK),
  Gulkana Glacier (AK), Sperry Glacier (MT), McMurdo Dry Valleys (AQ),
  Toolik Field Station (AK), Juneau Icefield Research Program (AK).
- **Cross-sphere ties**: McMurdo Dry Valleys is also an LTER, with
  terrestrial and freshwater secondaries. Toolik Field Station is
  cryosphere-primary with freshwater and terrestrial secondaries. Palmer
  Station LTER (AQ) is cryosphere-primary with an ocean-estuarine
  secondary. Niwot Ridge's LTER cryosphere instrumentation and SNOTEL
  station sit alongside its terrestrial-primary NEON site record.

## Terrestrial / Ecological

Long-term ecology and forest research. It is second by primary sphere,
but it is the sphere tagged on the most records once secondary roles are
counted.

- **Anchor networks**: NSF LTER, NEON, USFS Experimental Forests & Ranges
  (EFR; Lugo et al. 2006 list 77), LTREB, NPS Inventory & Monitoring, MAB
  Biosphere Reserves, OBFS, UC-NRS. As of 2026-10-23 the catalogue holds
  82 NEON member records and 40 records typed as experimental forests
  or ranges (USFS sites plus USDA-ARS range and research units); the
  USFS EFR network itself has 36 member records.
- **Landmark sites**: Harvard Forest (MA), H.J. Andrews (OR), Coweeta
  (NC), Luquillo (PR), Konza Prairie (KS), Cedar Creek (MN).
- **Cross-sphere ties**: numerous EFRs are also LTERs, and NEON sites
  overlap LTAR and LTER hosts. Some of these stay separate records, one
  per network, so the same place can carry different primary spheres
  (Jornada's NEON site is arid-primary, its LTAR record
  agriculture-primary).

## Arid

Arid, semi-arid, and desert systems: hot and cold deserts, dryland
shrublands and grasslands.

- **Anchor networks**: the desert LTERs, NEON Desert Southwest + Great
  Basin domains, NPS Sonoran Desert I&M network, USGS Canyonlands.
- **Landmark sites**: Jornada Basin LTER (NM), Sevilleta LTER (NM),
  Santa Rita Experimental Range NEON (AZ), Onaqui NEON (UT), Great Basin
  Experimental Range (UT), Mojave Global Change Facility (NV), Big Bend
  Biosphere Reserve (TX).
- **Cross-sphere ties**: the LTAR/ARS rangeland sites (Jornada
  Experimental Range, Walnut Gulch, Reynolds Creek, Santa Rita ER) keep
  **agriculture** as their primary sphere — ARS rangelands are part of
  that sphere's charter — and carry arid as a secondary. Desert streams
  (Sycamore Creek, Red Butte Creek) stay freshwater-primary the same
  way. Central Arizona–Phoenix LTER stays terrestrial-primary (its
  identity is urban ecology) with an arid secondary.

## Agriculture

Long-term cropping, rangeland, and soil-monitoring networks.

- **Anchor networks**: USDA-ARS Long-Term Agroecosystem Research (LTAR;
  19 LTAR site records as of 2026-10-23), ARS Rangelands, USDA Climate
  Hubs, NRCS SCAN, Kellogg Biological Station, ARS long-term experiments.
- **Landmark sites**: Jornada Experimental Range LTAR (NM), Walnut Gulch
  LTAR (AZ), Reynolds Creek LTAR (ID), Kellogg Biological Station LTAR
  (MI), Central Plains Experimental Range LTAR (CO).
- **Cross-sphere ties**: several LTAR sites share a location with a NEON
  site (Jornada, Central Plains, Santa Rita). Jornada and Kellogg are
  also LTERs. Reynolds Creek's USDA-ARS record carries cryosphere
  (mountain snowpack) among its secondaries, and its SCAN station is a
  separate agriculture-primary record.

## Aquatic — Ocean & Estuarine

Coastal, ocean, and estuarine networks (largely vendored from cod-kmap and
culled to U.S. + territory + U.S.-funded Antarctic stations). By primary
sphere this is the largest sphere.

- **Anchor networks**: IOOS Regional Associations (10 of the 11 as of
  2026-10-23; GLOS is not yet catalogued), OOI, NERRS (29 reserves),
  National Marine Sanctuaries, EPA NEP, MarineGEO Smithsonian, NOAA NMFS
  science centres, NAML labs.
- **Landmark sites**: Chesapeake Bay (MD/VA), Apalachicola NERR (FL),
  Padilla Bay NERR (WA), Gray's Reef NMS (GA), Stellwagen Bank NMS (MA),
  Santa Barbara Coastal LTER (CA).
- **Cross-sphere ties**: every NERR and National Marine Sanctuary record
  carries a terrestrial secondary, as do the Gulf Coast Texas and San
  Francisco Bay MarineGEO observatories. Palmer Station
  LTER is filed under cryosphere, with ocean-estuarine as its secondary.

## Aquatic — Freshwater

Rivers, lakes, watersheds, and groundwater.

- **Anchor networks**: USGS NWIS, USGS WEBB, USGS Hydrologic Benchmark
  Network (HBN), GLEON (US sites), North Temperate Lakes LTER, Hubbard
  Brook hydrology, EPA NARS (NLA / NRSA / NWCA / NCCA).
- **Landmark sites**: Mirror Lake (NH), Hubbard Brook Watershed 6 (NH),
  Sleepers River Research Watershed (VT), Loch Vale Watershed (CO),
  Trout Lake Station (WI), Toolik Lake (AK).
- **Cross-sphere ties**: Hubbard Brook Watershed 6 is freshwater-primary
  with a terrestrial secondary, and its deposition record sits in
  Atmosphere. Sleepers River and Loch Vale pair freshwater with
  cryosphere snowmelt. NOAA GLERL is filed under freshwater only. North
  Temperate Lakes LTER is currently mis-filed under ocean-estuarine in
  the data; it belongs here.
