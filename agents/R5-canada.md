# R5 — Canada coastal research facilities

## Scope
Canadian federal, provincial, university, and NGO coastal / ocean research
facilities on the Atlantic, Pacific, Arctic, and Great Lakes coasts. Canadian
scope includes the maritime provinces, Quebec, Ontario, British Columbia, and
territories with Arctic coastline (Nunavut, NWT, Yukon).

## Sources
- https://www.dfo-mpo.gc.ca/science/facilities-installations/index-eng.html
- https://www.oceannetworks.ca/observatories/
- https://www.bio.gc.ca/
- https://bamfieldmsc.com/
- https://www.huntsmanmarine.ca/
- https://ccgs.gc.ca/ — Canadian Coast Guard research vessel program
- Provincial ministry sites (BC, NS, NB, PE, NL, QC, ON)
- Canadian university marine-science departments (Dalhousie, Memorial, UBC,
  McGill coastal, Laval-Québec-Océan, Trent coastal)

## Inputs
- Wave 1 vocab CSVs

## Outputs
- `data/raw/R5/facilities_canada.json`
- `data/raw/R5/notes.md`

## Method
1. Start with DFO institutes and regional science branches.
2. Add Ocean Networks Canada and its cabled-observatory nodes (NEPTUNE, VENUS,
   Cambridge Bay).
3. Add university marine stations.
4. Record funders: NSERC, CFI, DFO, provincial agencies.
5. Use `country = "CA"`, `facility_type` per vocab.

## Known landmarks (must appear)
- Bedford Institute of Oceanography (DFO) — Dartmouth, NS
- Institute of Ocean Sciences (DFO) — Sidney, BC
- St. Andrews Biological Station (DFO) — St. Andrews, NB
- Pacific Biological Station (DFO) — Nanaimo, BC
- Freshwater Institute (DFO) — Winnipeg, MB (freshwater, include for Great
  Lakes / Hudson Bay coverage)
- Northwest Atlantic Fisheries Centre (DFO) — St. John's, NL
- Gulf Fisheries Centre (DFO) — Moncton, NB
- Maurice Lamontagne Institute (DFO) — Mont-Joli, QC
- Ocean Networks Canada HQ — Victoria, BC
- Bamfield Marine Sciences Centre — Bamfield, BC
- Huntsman Marine Science Centre — St. Andrews, NB
- Dalhousie Ocean Frontier Institute — Halifax, NS
- Marine Institute of Memorial University — St. John's, NL
- Hakai Institute — Calvert Island + Quadra Island, BC
