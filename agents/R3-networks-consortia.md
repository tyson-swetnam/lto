# R3 — Coastal / ocean research networks and consortia

## Scope
Multi-institution programs that themselves are organizations (with governance,
funding, and member facilities). Emit both the network-as-entity record and a
`network_membership.csv` edge list linking member facilities.

Networks in scope:
- IOOS regional associations (11): NERACOOS, MARACOOS, SECOORA, GCOOS,
  CARICOOS, SCCOOS, CeNCOOS, NANOOS, AOOS, PacIOOS, and the IOOS Program Office
- Ocean Observatories Initiative (OOI) + all nodes (Pioneer, Endurance, Global)
- US Long-Term Ecological Research (LTER) coastal sites: GCE, PIE, VCR, FCE,
  MCR, CCE, NGA, SBC, BES
- NOAA National Estuarine Research Reserve System (NERRS) — all 30 reserves
- Sea Grant — all 34 state programs + national office
- NEON aquatic sites with coastal / estuarine relevance
- Ocean Networks Canada (scope overlaps with R5)
- Global Ocean Observing System (GOOS)
- Arctic Council / working groups relevant to coastal
- Cooperative Institutes (NOAA CIs with coastal focus)

## Sources
- https://ioos.us/community/regional-associations/
- https://oceanobservatories.org/
- https://lternet.edu/site/
- https://coast.noaa.gov/nerrs/
- https://seagrant.noaa.gov/Our-Network/Sea-Grant-Programs
- https://www.neonscience.org/field-sites/
- https://www.oceannetworks.ca/
- https://goosocean.org/
- https://cpo.noaa.gov/Divisions-Programs/Earth-System-Science-and-Modeling/Cooperative-Institutes

## Inputs
- Wave 1 vocab CSVs
- R1 + R2 preliminary outputs (to resolve member facility IDs)

## Outputs
- `data/raw/R3/facilities_networks.json`
- `data/raw/R3/network_membership.csv` — columns: `network_record_id,
  member_canonical_name, member_record_id_hint, role, source_url`
- `data/raw/R3/notes.md`

## Method
1. Emit one facility record per network itself (with HQ location and funders).
2. Build member-edges by listing every reserve / RA / site / lab and matching
   against R1 and R2 records by name. Leave `member_record_id_hint` blank when
   uncertain; D2 ingestion will resolve via fuzzy match.

## Known landmarks (must appear)
- All 11 IOOS regional associations (headcount check).
- All 30 NERRS reserves — e.g., Waquoit Bay, Narragansett Bay, Delaware, Chesapeake
  Bay MD, Chesapeake Bay VA, North Carolina, Ashepoo-Combahee-Edisto (SC), Sapelo
  Island, Guana Tolomato Matanzas, Rookery Bay, Apalachicola, Grand Bay, Weeks
  Bay, Mission-Aransas, Tijuana River, Elkhorn Slough, San Francisco Bay, South
  Slough, Padilla Bay, Kachemak Bay, He'eia, Jobos Bay, etc.
- All 34 Sea Grant state programs.
- All OOI nodes: Coastal Pioneer (MAB), Coastal Endurance (OR/WA), Global
  Irminger Sea, Global Station Papa, Global Argentine Basin (historical),
  Global Southern Ocean (historical), Cabled Array (Axial + ES).
- LTER: GCE (Georgia Coast), FCE (Florida Everglades), VCR (Virginia Coast), PIE
  (Plum Island), CCE (California Current), MCR (Mo'orea), SBC (Santa Barbara),
  NGA (Northern Gulf of Alaska), BES (Baltimore).
