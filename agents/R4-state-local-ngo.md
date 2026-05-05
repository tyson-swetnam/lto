# R4 — US state / county / town programs, NGOs, foundations

## Scope
- State-government coastal agencies across the 23 US coastal states plus Great
  Lakes states (coastal-zone-management programs, departments of natural
  resources, fish and wildlife / marine fisheries, state universities'
  cooperative extension where relevant)
- County, parish, and municipal coastal programs that run their own monitoring
  or research (e.g., Miami-Dade DERM, San Francisco Estuary Institute though
  that is a JPA, Palm Beach County ERM)
- Non-profit research / conservation organizations with programmatic staff:
  TNC, Ocean Conservancy, EDF Oceans, Pew, Monterey Bay Aquarium, Mote Marine
  Laboratory, Bigelow (boundary with R2 — Mote and Bigelow are standalone
  non-profits, put them here)
- Foundations funding coastal research: Moore, Packard, Walton Family,
  Schmidt Ocean Institute, Bezos Earth Fund, Paul G. Allen

Exclusions: federal (→ R1), universities (→ R2), networks (→ R3).

## Sources
- Each coastal state's `.gov` portal (search for "coastal zone management",
  "marine fisheries", "department of environmental protection")
- https://projects.propublica.org/nonprofits/ — for 990 financials
- https://www.opensecrets.org/ — for lobbying / political links where relevant
- Foundation websites + 990-PFs filed with the IRS
- https://www.coastalstates.org/ — Coastal States Organization member directory

## Inputs
- Wave 1 vocab CSVs

## Outputs
- `data/raw/R4/facilities_state_local.json`
- `data/raw/R4/facilities_ngo_foundation.json`
- `data/raw/R4/notes.md`

## Method
1. Enumerate the 23 coastal state CZM programs (all federally approved under
   the Coastal Zone Management Act).
2. For each state, add the fish-and-wildlife / marine fisheries body and any
   state university sea grant extension office not already in R3.
3. County / city level: capture only programs with dedicated staff and a URL.
4. NGOs: record the HQ and any field stations or marine facilities.
5. Foundations: `facility_type = foundation`, record HQ only; R9 builds the
   funding edges.

## Known landmarks (must appear)
- 23 coastal-state CZM programs: WA, OR, CA, AK, HI, ME, NH, MA, RI, CT, NY, NJ,
  DE, MD, VA, NC, SC, GA, FL, AL, MS, LA, TX (plus PR, VI, American Samoa,
  Guam, CNMI). Great Lakes: MI, MN, WI, IL, IN, OH, PA, NY.
- Mote Marine Laboratory (Sarasota, FL)
- Monterey Bay Aquarium (Monterey, CA)
- The Nature Conservancy — Global Oceans
- Packard Foundation (Los Altos, CA)
- Moore Foundation (Palo Alto, CA)
- Walton Family Foundation (Bentonville, AR)
- Schmidt Ocean Institute (Palo Alto, CA)
- New England Aquarium (Boston, MA)
- Shedd Aquarium (Chicago, IL) — Great Lakes research
