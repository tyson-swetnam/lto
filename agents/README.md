# lto subagent specifications

This directory holds one markdown spec per subagent in the **lto** (U.S.
Long-Term Observatories) pipeline. Every research agent (`R-*`) emits JSON
records using the shared schema below. Database (`D*`) and frontend (`F*`)
agents consume those records through the contracts defined in
`schema/schema.sql`.

The pipeline is forked from `cod-kmap` (MIT) and extended to cover **six
spheres**: atmosphere, cryosphere, terrestrial / ecological, agriculture,
ocean & estuarine, freshwater. Inclusion gate is the Peters et al. 2013
threshold of ≥10 years of continuous record.

## Pipeline overview

```
Wave 0  Vendor cod-kmap engine                       (one-time bootstrap)
Wave A  D1 schema deltas + D3 vocab extension        (contracts)
Wave B  R-* research agents (one per sphere/network) (raw JSON per agent)
Wave C  D2 ingest → db/lto.duckdb → public/parquet/
Wave D  F1..F4 frontend + deploy
Wave E  R-SYNTH verification + coverage report
```

Wave B fan-out (single parallel batch):

| Agent | Scope |
|---|---|
| `R-ATM` | Atmosphere observatories (NOAA-GML, NADP, AmeriFlux, ARM, CASTNET, IMPROVE, SURFRAD, AERONET, Pandora, TCCON) |
| `R-CRY` | Cryosphere observatories (USGS Benchmark Glaciers, SNOTEL, CRREL, Toolik, McMurdo Dry Valleys, Palmer, Juneau Icefield) |
| `R-TER-LTER` | NSF LTER 28 sites + LTREB long-term sites |
| `R-TER-EFR` | USFS Experimental Forests & Ranges (77, per Lugo et al. 2006) |
| `R-TER-NEON` | NEON 81 sites (one record per site, all tagged `neon`) |
| `R-TER-OTHER` | MAB Biosphere Reserves, NPS-IM networks, NWRS long-record refuges, USFS RNAs, OBFS field stations, UC-NRS reserves |
| `R-AGR` | USDA-ARS LTAR (18 sites), ARS rangelands, USDA Climate Hubs, SCAN, KBS-AG, long-term ag experiments |
| `R-AQ-OCEAN-CULL` | Curate cod-kmap heritage data: keep U.S. + territory + U.S.-funded Antarctic facilities; drop non-US Latin America / South America / non-U.S. Caribbean |
| `R-AQ-FRESH` | Freshwater (USGS NWIS / WEBB / HBN, GLEON, NTL-LTER, Hubbard Brook hydrology, EPA NARS) |
| `R-XREF` | Cross-sphere mappings (Hubbard Brook = TER+ATM+FRESH, Niwot = CRY+TER, Bonanza Creek = TER+CRY, Coweeta = TER+FRESH, Jornada = TER+AGR, KBS = TER+AGR …) |
| `R-FUND` | Funding-flow enrichment (NSF, USDA, NOAA, DOE, USGS, NASA, EPA) |

## Shared facility JSON record

Every research agent writes `data/raw/<AGENT_ID>/facilities_<slug>.json`
as an array of records matching this schema:

```json
{
  "record_id": "R-TER-LTER-0001",
  "canonical_name": "Hubbard Brook Experimental Forest",
  "acronym": "HBR",
  "parent_org": "USDA Forest Service Northern Research Station",
  "facility_type": "experimental-forest-range",
  "country": "US",
  "region": "New England",
  "hq": {
    "address": "234 Mirror Lake Road, North Woodstock, NH 03262, USA",
    "lat": 43.9438,
    "lng": -71.7517
  },
  "locations": [
    {
      "label": "Hubbard Brook HQ",
      "address": "234 Mirror Lake Road, North Woodstock, NH 03262, USA",
      "lat": 43.9438,
      "lng": -71.7517,
      "role": "headquarters"
    },
    {
      "label": "Watershed 6 reference catchment",
      "lat": 43.9573,
      "lng": -71.7370,
      "role": "field-station"
    }
  ],
  "primary_sphere": "terrestrial",
  "secondary_spheres": ["atmosphere", "freshwater"],
  "ecosystem_types": ["eastern-forest"],
  "life_zones": ["cool-temperate-moist-forest"],
  "research_areas": [
    "forest-ecology", "biogeochemistry", "atmospheric-deposition",
    "watershed-management", "long-term-trends"
  ],
  "networks": ["lter", "usfs-rna-ef", "ltreb", "nadp"],
  "funders": [
    { "name": "USDA Forest Service", "relation": "parent-agency" },
    { "name": "NSF", "relation": "grant", "years": [1988, 2025] }
  ],
  "url": "https://hubbardbrook.org/",
  "data_portal_url": "https://portal.edirepository.org/nis/browseServlet?searchValue=HBR",
  "established": 1955,
  "record_length_years": 70,
  "long_term_threshold_met": true,
  "provenance": {
    "source_url": "https://hubbardbrook.org/about-us/",
    "retrieved_at": "2026-05-05",
    "confidence": "high",
    "agent": "R-TER-LTER"
  }
}
```

## Field conventions

- **record_id** — `<AGENT_ID>-<4-digit-seq>`, stable across runs where possible.
- **facility_type** — must be a value from `schema/vocab/facility_types.csv`.
- **country** — ISO 3166-1 alpha-2 (US, plus territory codes PR, VI, AS, GU, MP).
  U.S.-funded Antarctic stations (PAL, MCM) use `AQ` for the geographic country
  and set `parent_org` / `funders` to the funding agency.
- **hq.lat/lng** — decimal degrees, WGS84. Leave null if you cannot find
  coordinates and let D2 geocode from `hq.address`.
- **locations** — list of 1..N sites. First entry should mirror `hq` when
  applicable. `role` ∈ {headquarters, field-station, observatory, vessel,
  mooring-array, buoy, lab, office, virtual, flux-tower, glacier-site,
  snow-station, weather-station, streamgage}.
- **primary_sphere** — one of {atmosphere, cryosphere, terrestrial,
  agriculture, ocean-estuarine, freshwater}. Required.
- **secondary_spheres** — zero or more additional spheres a facility
  meaningfully contributes to. Use sparingly; favour primary sphere.
- **ecosystem_types** — slugs from `schema/vocab/ecosystem_types.csv`
  (EcoTrends + WWF biome).
- **life_zones** — Holdridge life-zone slugs from
  `schema/vocab/life_zones.csv` (per Lugo et al. 2006).
- **research_areas** — slugs from `schema/vocab/research_areas.csv`
  (GCMD-aligned where possible).
- **networks** — slugs from `schema/vocab/networks.csv` (lower-case acronym
  form: `lter`, `neon`, `usfs-rna-ef`, `ameriflux`, …).
- **funders** — `relation` ∈ {parent-agency, grant, endowment, contract,
  cooperative-agreement, state-appropriation, private-donor, membership-fee,
  appropriation}. Dollar amounts optional; `R-FUND` enriches later.
- **established** — year the observatory began operating.
- **record_length_years** — current length of the continuous time series in
  years. Set to NULL if you cannot determine.
- **long_term_threshold_met** — TRUE iff `record_length_years >= 10`
  (Peters et al. 2013 threshold). Records below the threshold are kept but
  filtered out by default in the UI.
- **data_portal_url** — canonical data DOI / portal landing page (EDI / NCEI
  / NWIS / agency-specific). Optional but strongly preferred.
- **provenance.confidence** — {high, medium, low}. Use high for primary-source
  agency pages; medium for third-party aggregators; low for inferred data.

## Agent spec template

Each subagent markdown file has this structure:

```
# <Agent ID> — <Short Name>

## Scope
What this agent covers and explicit exclusions. Which sphere(s).

## Sources
Ordered list of authoritative URLs / APIs, each with usage notes.

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

1. **U.S. scope.** Include facilities physically in the U.S., its territories
   (PR, VI, AS, GU, MP), and U.S.-funded Antarctic stations. Drop everything
   else.
2. **Long-term threshold.** Default inclusion is `record_length_years >= 10`
   (Peters et al. 2013). You may include shorter-record facilities if they
   are members of a long-running network (LTER, NEON, LTAR), but mark
   `long_term_threshold_met = false` honestly.
3. **Primary sources.** Prefer agency / institution pages over aggregators.
4. **Provenance always.** No record without a citable URL.
5. **Both HQ and satellite locations** when they exist.
6. **Deduplicate within your own output** before writing; D2 handles
   cross-agent dedup. If your scope overlaps another R-agent's, leave a
   note in the record's `notes` field — `R-XREF` reconciles in Wave E.
7. **Coordinate honesty.** If you cannot determine coordinates, leave
   lat/lng null and set `hq.address` precisely; D2's geocoder will fill in.
8. **Confidence honesty.** Mark uncertain records `confidence = "low"`
   rather than omitting them; D2's QA pass surfaces these for review.
