# R10 — COMPASS synthesis-networks ingest

## Scope
Import the network-of-networks dataset from Myers-Pigg et al., *Advancing the
understanding of coastal disturbances with a network-of-networks approach*
(Ecosphere), released at https://github.com/COMPASS-DOE/synthesis-networks,
together with the follow-on spatial layers shipped in
`network_synth_spatial_analysis/`.

Two flavours of content are ingested:

1. **Tabular source** — `Networks_table_updated.csv` (52 networks × 15 attributes:
   funding agency, management structure, geographic scope, disturbance flag,
   CDEON/EON/LTMP/LTRN/ORC category, ecosystem flags). Preserved verbatim
   under `data/raw/synthesis-networks/` for provenance and for downstream
   analyses that need the broader context.
2. **Spatial source** — point and polygon layers in
   `network_synth_spatial_analysis/` (LTER, LTREB, MarineGEO, Sentinel Site,
   NERR, NEP, NMS, NPS coastal, Marine Monuments, EPA facilities, NEON
   domains, CA wetland potential, CCAP land cover). The point layers are
   ingested as individual facilities by `scripts/build_r10_from_spatial.py`;
   polygon layers are retained as map overlays.

Including terrestrial coastal ecosystems (LTREB salt-marsh plots, NERR
reserves, LTER coastal sites) is central to this extension — these are the
"terrestrial coastal observatories" referenced in the new observatory
design, and they were absent from R1–R8.

## Sources
- https://github.com/COMPASS-DOE/synthesis-networks (MIT)
  - `data/Networks_table_updated.csv`
  - `data/hexagons_Ecoregion_TableToExcel.xlsx`
  - `scripts/networks_figure2.Rmd`
- `network_synth_spatial_analysis/` (mirrored in-repo)
  - `Land_Cover/LTER.geojson` — 10 LTER coastal sites
  - `Land_Cover/LTREB.geojson` — 4 LTREB salt-marsh / coastal sites
  - `Land_Cover/MarineGeo.geojson` — 4 MarineGEO marine stations
  - `Land_Cover/Sentinel_Site.geojson` — 5 NOAA Sentinel Sites
  - `Coastal_NetworkSites__My_Places.geojson` — 66 compiled NERR, NEP,
    LTREB, Sentinel, and NMS points
  - `NEP_BoundariesFY19/NEP_Boundaries2019.geojson` — 28 NEP polygons with
    year designated, EPA region, area

## Inputs
- Wave 1 `schema/vocab/networks.csv` (to detect duplicates; extended in this
  wave with `lter-site`, `ltreb`, `nep`, `nms`, `marinegeo`, `sentinel-site`)
- Wave 1 `schema/vocab/research_areas.csv` (extended with
  `long-term-ecological-research`, `coastal-terrestrial-ecosystems`,
  `salt-marshes`, `tidal-wetlands`, `coastal-disturbance`)

## Outputs
- `data/raw/synthesis-networks/` — verbatim upstream tabular artifacts
- `scripts/synthesis-networks/networks_figure2.Rmd` — verbatim analysis script
- `network_synth_spatial_analysis/` — spatial layers (committed in the
  preceding commit on `main`)
- `scripts/build_r10_from_spatial.py` — converts point layers into facility
  records; idempotent
- `data/raw/R10/facilities_synthesis_networks.json` — 82 facility records
  emitted by the builder (LTER 10, LTREB 4, MarineGEO 4, Sentinel 3, NERRS
  29, NEP 27, NMS 5)

## Method
1. Preserve upstream tabular artifacts verbatim for citation integrity.
2. Parse the spatial point layers. Each feature has a `Name` and a WGS84
   `[lng, lat]` coordinate tuple (Google Earth KML provenance).
3. Classify each feature by name-pattern (LTREB / LTER / Sentinel / NERR /
   NMS / NEP) and look up per-network metadata (parent org, funders, default
   research areas).
4. Emit one facility record per site with:
   - `facility_type` — `network` for LTER/LTREB/MarineGEO;
     `federal` for NERR/Sentinel/NMS; `nonprofit` for NEP programs
   - `country` — always `US` for this dataset
   - `hq.lat`, `hq.lng` — taken directly from the geojson geometry
   - `url` — null per site (the program URL lives on the parent network
     vocab entry; setting a shared URL per site would collapse all members
     into a single row in D2's URL-based dedup)
   - `networks` — the canonical network slug
   - `funders` — single parent-agency funder (NOAA for NERR/Sentinel/NMS,
     EPA for NEP, NSF for LTER/LTREB, Smithsonian for MarineGEO)
   - `research_areas` — pulled from a per-network template
   - `provenance.confidence: "medium"` — coordinates authoritative, metadata
     sparse
5. NEP records are enriched by joining `NEP_Boundaries2019.geojson` on
   program name to populate `established` (year designated) and `region`
   (EPA region number).
6. Dedupe within R10 by `(lower(name), round(lng,4), round(lat,4))` before
   writing.

## Running
```bash
python scripts/build_r10_from_spatial.py          # rebuilds data/raw/R10/...
python scripts/ingest.py --skip-geocode           # rebuilds db/cod_kmap.duckdb
python scripts/qa.py                              # bbox, enum, FK checks
python scripts/export_parquet.py                  # rebuilds Parquet + GeoJSON
```

## Known landmarks (must appear after step 4)
- LTER — Plum Island, Georgia Coast, Florida Coast, Virginia Coast,
  Santa Barbara Coastal, California Current, Northern Gulf of Alaska,
  Beaufort Lagoon, Northeast US Margin, North Temperate Lakes
- LTREB — Swan's Island, West Falmouth Harbor, North Inlet, SERC GCREW
- MarineGEO — SERC GCREW, Indian River Lagoon, San Francisco Bay, Gulf Coast
- Sentinel Site — Chesapeake Bay, Hawaiian Islands, North Carolina
- NERR — Mission Aransas, Waquoit Bay, Sapelo Island, Rookery Bay,
  Apalachicola, Grand Bay, Weeks Bay, Tijuana River, Elkhorn Slough,
  Padilla Bay, Kachemak Bay, He'eia, Jobos Bay, plus 16 others
- NEP — Casco Bay, Buzzards Bay, Narragansett Bay, Long Island Sound,
  Chesapeake Bay, Tampa Bay, Puget Sound, plus 20 others
- NMS — Stellwagen Bank, Mallows Bay-Potomac River, Monitor, Gray's Reef,
  Florida Keys

## Out of scope
- Polygon layers in `network_synth_spatial_analysis/` (NEP boundaries,
  NERR reserves, NMS sanctuaries, NPS parks, Marine Monuments, NEON domains,
  EPA regions, CA wetland potential) — retained as citable raw artifacts and
  candidate overlays for a future F1 map-layer enhancement, but not emitted
  as facility rows.
- The hexagon × ecoregion × hazard table (`hexagons_Ecoregion_TableToExcel.xlsx`)
  — preserved for paper Figure 2 reproduction only.
- EPA Labs / Special Facilities / Regional HQs from
  `EPA_Locations/EPA_Regions__EPA_Facilities.geojson` — administrative
  offices, not coastal observatories.

## Attribution
Any derivative product that uses this dataset must cite:

> Myers-Pigg, A. N. et al. *Advancing the understanding of coastal disturbances
> with a network-of-networks approach.* Ecosphere.

and link to https://github.com/COMPASS-DOE/synthesis-networks.
