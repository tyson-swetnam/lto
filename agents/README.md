# cod-kmap subagent specifications

This directory holds one markdown spec per subagent in the cod-kmap pipeline.
Every research agent (R*) emits JSON records using the shared schema below.
Database and frontend agents consume those records through the contracts defined
in `schema/schema.sql`.

## Pipeline overview

```
Wave 1  D1 schema  +  D3 vocabulary          (contracts)
Wave 2  R1..R8 research agents               (raw JSON per agent)
Wave 3  R9 funding-flow cross-cut
Wave 4  D2 ingest → db/cod_kmap.duckdb
Wave 5  F1..F4 frontend + deploy
Wave 6  verification + iteration
```

## Shared facility JSON record

Every research agent writes `data/raw/<AGENT_ID>/facilities_<slug>.json`
as an array of records matching this schema:

```json
{
  "record_id": "R1-0001",
  "canonical_name": "Pacific Marine Environmental Laboratory",
  "acronym": "PMEL",
  "parent_org": "NOAA Office of Oceanic and Atmospheric Research",
  "facility_type": "federal",
  "country": "US",
  "region": "Pacific Northwest",
  "hq": {
    "address": "7600 Sand Point Way NE, Seattle, WA 98115, USA",
    "lat": 47.6833,
    "lng": -122.2583
  },
  "locations": [
    {
      "label": "PMEL Seattle HQ",
      "address": "7600 Sand Point Way NE, Seattle, WA 98115, USA",
      "lat": 47.6833,
      "lng": -122.2583,
      "role": "headquarters"
    },
    {
      "label": "PMEL Newport Field Station",
      "address": "2115 SE OSU Drive, Newport, OR 97365, USA",
      "lat": 44.6236,
      "lng": -124.0436,
      "role": "field-station"
    }
  ],
  "research_areas": ["physical-oceanography", "ocean-acidification", "tsunamis"],
  "networks": ["IOOS", "GOOS"],
  "funders": [
    { "name": "NOAA", "relation": "parent-agency" },
    { "name": "NSF",  "relation": "grant", "years": [2019, 2022] }
  ],
  "url": "https://www.pmel.noaa.gov/",
  "contact": "info@pmel.noaa.gov",
  "established": 1973,
  "provenance": {
    "source_url": "https://www.pmel.noaa.gov/about",
    "retrieved_at": "2026-04-18",
    "confidence": "high",
    "agent": "R1"
  }
}
```

## Field conventions

- **record_id** — `<AGENT_ID>-<4-digit-seq>`, stable across runs where possible.
- **facility_type** — must be a value from `schema/vocab/facility_types.csv`.
- **country** — ISO 3166-1 alpha-2 (US, CA, MX, CO, BR, CU, JM, DO, HT, BS, PR, VI, …).
  Note: PR and VI are US territories; still record as `PR` / `VI` for geographic
  clarity and set `parent_org` / `funders` accordingly.
- **hq.lat/lng** — decimal degrees, WGS84. Required for non-virtual organizations.
  Leave null and let D2 geocode from `hq.address` if you cannot find coordinates.
- **locations** — list of 1..N sites. First entry should mirror `hq` when
  applicable. Use `role` ∈ {headquarters, field-station, observatory, vessel,
  mooring-array, buoy, lab, office, virtual}.
- **research_areas** — slugs mapped to `schema/vocab/research_areas.csv`
  (GCMD-aligned). Use the closest existing term; do not invent new slugs without
  coordinating with D3.
- **networks** — acronyms (IOOS, OOI, LTER, NERRS, GOOS, CARICOOS, …).
- **funders** — `relation` ∈ {parent-agency, grant, endowment, contract,
  cooperative-agreement, state-appropriation, private-donor, membership-fee}.
  Dollar amounts are optional; R9 will enrich this later.
- **provenance.confidence** — {high, medium, low}. Use high for primary-source
  agency pages; medium for third-party aggregators; low for inferred data.

## Agent spec template

Each subagent markdown file has this structure:

```
# <Agent ID> — <Short Name>

## Scope
What this agent covers and explicit exclusions.

## Sources
Ordered list of authoritative URLs / APIs, each with its usage notes.

## Inputs
Any artifacts from earlier waves this agent depends on.

## Outputs
Paths of files this agent writes and a brief description.

## Method
Bullet plan describing how to collect, validate, and emit data.

## Known landmarks
A handful of facilities that MUST appear in the output (for QA).
```

## Rules for every R-agent

1. Prefer primary sources (agency / institution pages) over aggregators.
2. Always fill `provenance` — no record without a citable URL.
3. Capture both HQ and satellite/field-station locations when they exist.
4. Deduplicate within your own output before writing; D2 handles cross-agent dedup.
5. If you cannot determine coordinates, leave lat/lng null and set `hq.address`
   as precisely as possible — D2's geocoder will fill the gap.
6. Flag uncertain records with `provenance.confidence = "low"` rather than
   omitting them; D2's QA pass will surface these for human review.
