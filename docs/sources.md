# Sources

## Foundational papers

The two papers below define the long-term threshold, the EcoTrends
landmark list, and the Holdridge life-zone vocabulary used across the
database.

- **Peters, D.P.C., Loescher, H.W., SanClements, M.D., Havstad, K.M.
  2013.** *Long-Term Trends in Ecological Systems: A Basis for
  Understanding Responses to Global Change.* USDA ARS Technical
  Bulletin 1931. Source of the **≥10-year continuous-record threshold**
  behind the map's optional "≥10y" filter (off by default; 341 of 440
  facilities meet it as of 2026-10-25), and of the **EcoTrends 50** site
  list (Table 1-1) that we check landmark coverage against.

- **Lugo, A.E., Swanson, F.J., González, O.R., Adams, M.B., Palik, B.,
  Thill, R.E., Brockway, D.G., Kern, C., Woodsmith, R., Musselman, R.
  2006.** *Long-Term Research at the USDA Forest Service's Experimental
  Forests and Ranges.* *BioScience* 56(1): 39–48. Source of the paper's
  roster of **77 USFS Experimental Forests & Ranges** that the
  experimental-forest research worked from, and of the Holdridge
  life-zone tagging (`schema/vocab/life_zones.csv`).

## Data providers

Facility records are sourced primarily from the agency or institution
that operates each observatory. The largest contributors are below; the
counts are facilities in this catalogue tagged with that network as of
2026-10-25, not the program's own site totals.

- **NSF LTERnet** — <https://lternet.edu/> — LTER sites.
- **NSF DEB LTREB** — <https://www.nsf.gov/funding/opportunities/long-term-research-environmental-biology-ltreb> — sites with LTREB-funded projects (23).
- **NSF NEON / Battelle** — <https://www.neonscience.org/> — NEON (82 facilities tagged).
- **USDA-ARS LTAR** — <https://ltar.ars.usda.gov/> — LTAR sites (26) + ARS rangelands.
- **USDA Forest Service** — <https://www.fs.usda.gov/research/efr> — Experimental Forests, Ranges and RNAs (36 facilities tagged).
- **USGS Water Mission Area** — <https://www.usgs.gov/mission-areas/water-resources> — NWIS, WEBB, HBN, Benchmark Glaciers.
- **NOAA Global Monitoring Laboratory** — <https://gml.noaa.gov/> — atmospheric baseline observatories (5) and the WLEF tall tower.
- **DOE ARM** — <https://www.arm.gov/> — Atmospheric Radiation Measurement sites (3).
- **EPA** — <https://www.epa.gov/> — CASTNET (6), National Estuary Programs (27).
- **NOAA NOS / IOOS** — <https://ioos.noaa.gov/> — IOOS (15, 10 of them Regional Associations), NERRS (30), NMS (5).
- **Smithsonian MarineGEO** — <https://marinegeo.si.edu/> — coastal biodiversity sites (5).
- **NRCS** — SNOTEL snow-telemetry (12) and SCAN soil-climate (11) sites.

## New Mexico and Southwest sources

Every record in this layer is fetched or cites a fetched page. See
[ARID & New Mexico](./arid.md) for how it is built.

- **UNM ARID Institute** — <https://arid.unm.edu/> — the ARID Institute,
  its partner centers, leadership team and projects, each citing the
  page it came from.
- **EnviroData-NM** — <https://envirodata-nm.unm.edu/> — New Mexico's
  environmental data portal (139 map layers as of 2026-10-23).
  **Metadata and links only:** the portal's terms say its data are not to
  be redistributed, so no layer's features are copied.
- **Arizona Water Observatory** — <https://arizonawaterobservatory.asu.edu/>,
  API <https://arizonawaterobservatory-api.rtd.asu.edu/> — 26 OGC API
  collections, built from the API's own collection list. **Pointers
  only**; each upstream dataset keeps its own terms.

## People and publications

Key personnel (directors, lead PIs, site and reserve managers, NEON
domain managers) were re-researched on 2026-10-22 from fetched pages, and
a second, adversarial agent re-checked every draft before it was loaded.
The pages used are:

- **LTER Network** — <https://lternet.edu/> site pages and directory.
- **NEON** domain pages — <https://www.neonscience.org/>.
- **NERR reserve and NEP program pages**, each reserve's or program's
  own site.
- **Agency pages** — NPS, USGS, USDA-ARS and LTAR, USDA Climate Hubs,
  USFS Research.
- **NSF award records** — <https://api.nsf.gov/>.
- **Institutional profile pages** of the people themselves.

Each affiliation from the 2026-10-22 pass (851 rows as of 2026-10-24) keeps its
`source_url`, its retrieval date and an evidence quote of 25 words or
fewer from that page. A bio is a short paraphrase (at most 60 words) of a
named source page, not a copy. Older rows from the spring 2026 passes
(about 660) have no evidence quote, and a few have no source or date;
they remain until a fetched page confirms, replaces or retires them. The
People tab shows the source and retrieval date where the row has one.

Identifiers and publications come from two open APIs:

- **ORCID** — <https://pub.orcid.org/> — an iD is kept only if the name
  matches and either a fetched profile or an employment at the right
  institution confirms it, or, for people with no facility on file, the
  name resolves to exactly one ORCID record. A wrong ORCID is worse than a missing one, so
  unmatched people stay blank (611 of 1,329 people carry one as of
  2026-10-25).
- **OpenAlex** — <https://api.openalex.org/> — publications, citations
  and topics. People are matched only through their ORCID or a stored
  OpenAlex id, never by name search. Two passes have processed all 1,302
  people in the queue, and as of 2026-10-24 560 people carry an OpenAlex
  id. The other people cannot be matched this way because they have no
  ORCID or OpenAlex id, or an ORCID OpenAlex does not know. Every new
  attribution was reviewed.

From all of these we store identifiers, links and short paraphrases, not
copied page text.

**Mostly not from fetched sources:** funding amounts. Of the 380 funding
events with a dollar amount, 337 are labelled as recalled rather than
fetched. The other 43 are the four LTREB award series (North Inlet, GCReW,
Swan's Island, West Falmouth Harbor), fetched from the NSF Award API on
2026-10-25. Treat any funding total as provisional.

## Engine attribution

The visualisation engine and a portion of the ocean-estuarine records are
forked from [`tyson-swetnam/cod-kmap`](https://github.com/tyson-swetnam/cod-kmap)
under the MIT License. Terrestrial, atmospheric, cryospheric, agricultural,
freshwater and arid coverage is new in `lto`. See the project `LICENSE`.
