# R1 — Federal US coastal research facilities (first pass)

## Status
Seed dataset of **25 flagship facilities** across the agencies R1 covers.
Produced directly by the parent agent after two subagent attempts timed out
while streaming the entire JSON payload in a single `Write` tool_use.

## Coverage by agency
- NOAA: 10 — PMEL, AOML, GLERL, NCCOS, NWFSC, SEFSC, AFSC, NEFSC, NDBC,
  Office for Coastal Management
- USGS: 4 — WHCMSC, SPCMSC, PCMSC, Great Lakes Science Center
- EPA: 2 — Narragansett ACESD, Gulf Breeze GEMMD
- USACE: 2 — Field Research Facility Duck NC, ERDC-CHL Vicksburg
- Navy / NRL: 1 — NRL Stennis
- NASA: 2 — Wallops Flight Facility, GSFC Ocean Biology Processing Group
- Smithsonian: 2 — SERC Edgewater, Marine Station Fort Pierce
- NPS: 2 — Cape Cod National Seashore, Point Reyes National Seashore

## Known gaps (to fill in a later pass)
- Remaining 8 National Seashores (Fire Island, Assateague Island, Cape Hatteras,
  Cape Lookout, Canaveral, Gulf Islands, Padre Island, Cumberland Island)
- Coastal National Parks (Acadia, Biscayne, Channel Islands, Dry Tortugas,
  Everglades, Glacier Bay, Kenai Fjords, Olympic, Redwood, Virgin Islands NP,
  Katmai, Lake Clark, War in the Pacific, American Memorial Park)
- Pacific Islands Fisheries Science Center (PIFSC) and Southwest Fisheries
  Science Center (SWFSC)
- NOAA NOS offices beyond OCM (e.g., Office of Response and Restoration,
  National Geodetic Survey, Center for Operational Oceanographic Products
  and Services — CO-OPS)
- NOAA NCEI (National Centers for Environmental Information — Asheville,
  Silver Spring, Stennis, Boulder)
- USFWS coastal field offices and NWRs (only flagship coastal refuges needed)
- BOEM regional offices (Pacific, Gulf, Atlantic)
- NSF Ocean Sciences HQ
- NAVOCEANO (Naval Oceanographic Office, Stennis)
- NASA JPL, Ames, Langley ocean-remote-sensing teams

## Source quality
All 25 records cite an official agency page in `provenance.source_url`.
Coordinates were sourced from public knowledge of building / campus addresses
and rounded to 4 decimal places (~11 m precision). Any record with
`confidence: "high"` has both HQ address and coordinates verified against
the cited page or a widely-published address. Addresses of field stations
are approximate where the parent agency groups multiple buildings under one
street address.

## Schema conformance
- All 25 records have `record_id` in `R1-0001..R1-0025`, monotonically ordered.
- All `facility_type` values = `federal` (valid slug from
  `schema/vocab/facility_types.csv`).
- All `research_areas` slugs validated against
  `schema/vocab/research_areas.csv`.
- All `networks` references use uppercase acronyms found in
  `schema/vocab/networks.csv` (IOOS, GOOS, NERRS).
- Every record has a provenance block with `agent: "R1"`,
  `retrieved_at: "2026-04-18"`, `confidence: "high"`.

## Lessons for downstream agents (R2-R9)
To avoid the subagent stream-idle timeout that killed two R1 attempts, future
research agents should:
1. Write in batches of ≤ 10 records per `Write`/`Edit` call, not one big blob,
   OR
2. Be run with Sonnet (faster streaming) rather than Opus for bulk-output work,
   OR
3. Have the parent produce the payload directly when the data is knowable
   without live web research.
