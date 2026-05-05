# R1 — US Federal coastal research facilities

## Scope
All US federal-government-operated facilities that conduct or host coastal,
ocean, estuarine, or Great Lakes observation / research. Includes HQ offices
that direct coastal programs even when not themselves on the coast.

Agencies in scope:
- NOAA — line offices (NOS, NMFS, OAR, NESDIS, NWS where coastal), labs
  (PMEL, AOML, GLERL, NCCOS), field offices, NDBC
- USGS — Coastal / Marine Hazards & Resources (WHCMSC, SPCMSC, PCMSC) and
  Great Lakes Science Center
- EPA — ORD labs (Atlantic Ecology Division, Gulf Ecology Division, etc.)
- USFWS — National Wildlife Refuges on the coast, Fisheries and Ecological
  Services field offices
- NPS — National Seashores, coastal National Parks & Monuments, I&M networks
- USACE — ERDC-CHL, Field Research Facility (Duck, NC), coastal districts
- US Navy / NRL — NRL ocean sciences, NAVOCEANO at Stennis
- NASA — centers running coastal/ocean missions (Goddard, Ames, JPL, Langley,
  Wallops, Stennis)
- NSF OCE — facilities it owns or operates directly (small set)
- BOEM / BSEE, NOAA Fisheries Regional Offices, Smithsonian SERC

Exclusions: state/local agencies (→ R4), universities (→ R2), consortia (→ R3).

## Sources
- https://www.noaa.gov/organization
- https://www.usgs.gov/centers
- https://www.epa.gov/aboutepa/research-labs
- https://www.fws.gov/program/fisheries-aquatic-conservation
- https://www.nps.gov/aboutus/upload/cc_nps_units.pdf
- https://www.erdc.usace.army.mil/Locations/
- https://www.nrl.navy.mil/Our-Work/Areas-of-Research/Ocean-Atmospheric-Science-and-Technology/
- https://www.nasa.gov/centers
- https://www.usaspending.gov/
- https://www.research.gov/

## Inputs
- `schema/vocab/facility_types.csv` (Wave 1 D3)
- `schema/vocab/research_areas.csv` (Wave 1 D3)

## Outputs
- `data/raw/R1/facilities_federal_us.json`
- `data/raw/R1/notes.md` — source-by-source collection notes

## Method
1. Walk each agency's official org/centers page and enumerate operating units.
2. For each unit, capture HQ + all known field sites.
3. Map research areas to `research_areas.csv` slugs.
4. Record parent agency as a funder with relation `parent-agency`.
5. Cross-reference against USAspending.gov only to confirm existence — actual
   funding-flow edges are R9's job.
6. Deduplicate within the file, sort by `canonical_name`, write JSON.

## Known landmarks (must appear)
- NOAA PMEL (Seattle, WA)
- NOAA AOML (Miami, FL)
- NOAA GLERL (Ann Arbor, MI)
- NOAA NCCOS (Silver Spring, MD) + NCCOS Beaufort Lab
- USGS WHCMSC (Woods Hole, MA)
- USGS SPCMSC (St. Petersburg, FL)
- USGS PCMSC (Santa Cruz, CA)
- EPA Atlantic Coastal Environmental Sciences Division (Narragansett, RI)
- EPA Gulf Ecosystem Measurement and Modeling Division (Gulf Breeze, FL)
- USACE Field Research Facility (Duck, NC)
- ERDC Coastal and Hydraulics Laboratory (Vicksburg, MS)
- NRL Stennis Space Center ocean sciences
- NASA Wallops Flight Facility (Wallops Island, VA)
- Smithsonian Environmental Research Center (Edgewater, MD)
