# Sources

## Foundational papers

The two papers below define the inclusion gate, the EcoTrends landmark
list, and the Holdridge life-zone vocabulary used across the database.

- **Peters, D.P.C., Loescher, H.W., SanClements, M.D., Havstad, K.M.
  2013.** *Long-Term Trends in Ecological Systems: A Basis for
  Understanding Responses to Global Change.* USDA ARS Technical
  Bulletin 1931. Source of the **≥10-year continuous-record threshold**
  used as the default UI inclusion gate, and of the **EcoTrends 50** site
  list (Table 1-1) that we check landmark coverage against.

- **Lugo, A.E., Swanson, F.J., González, O.R., Adams, M.B., Palik, B.,
  Thill, R.E., Brockway, D.G., Kern, C., Woodsmith, R., Musselman, R.
  2006.** *Long-Term Research at the USDA Forest Service's Experimental
  Forests and Ranges.* *BioScience* 56(1): 39–48. Source of the **77
  USFS Experimental Forests & Ranges** roster and the Holdridge
  life-zone tagging (`schema/vocab/life_zones.csv`).

## Data providers

Records in this database are sourced primarily from the agency or
institution that operates each observatory. The largest contributors:

- **NSF LTERnet** — <https://lternet.edu/> — LTER 28 sites + LTREB.
- **NSF NEON / Battelle** — <https://www.neonscience.org/> — NEON 81 sites.
- **USDA-ARS LTAR** — <https://ltar.ars.usda.gov/> — LTAR 18 sites + ARS rangelands.
- **USDA Forest Service** — <https://www.fs.usda.gov/research/efr> — Experimental Forests, Ranges, RNAs.
- **USGS Water Mission Area** — <https://www.usgs.gov/mission-areas/water-resources> — NWIS, WEBB, HBN, Benchmark Glaciers.
- **NOAA Global Monitoring Laboratory** — <https://gml.noaa.gov/> — atmospheric baseline observatories.
- **DOE ARM** — <https://www.arm.gov/> — Atmospheric Radiation Measurement sites.
- **EPA** — <https://www.epa.gov/> — CASTNET, NEP, NARS.
- **NOAA NOS / IOOS** — <https://ioos.noaa.gov/> — IOOS Regional Associations, NERRS, NMS.
- **Smithsonian MarineGEO** — <https://marinegeo.si.edu/> — coastal biodiversity sites.
- **NRCS** — SNOTEL and SCAN soil-climate networks.

## Engine attribution

The visualisation engine and a portion of the ocean-estuarine records are
forked from [`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap)
under the MIT License. Terrestrial, atmospheric, cryospheric, agricultural,
and freshwater coverage is new in `lto`. See the project `LICENSE`.
