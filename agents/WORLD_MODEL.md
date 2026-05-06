# LTO World Model

> A **durable** description of what a "complete" LTO record looks like.
> Re-read this at the start of every session. It is the spec for the
> agent fan-outs in `J-DATA.md` / `R-PEOPLE.md` / `H-FUND-PUB.md` and
> the basis for `scripts/eval_progress.py`'s gap report.

## What we are building

A queryable map + database of every U.S. long-term observatory across
six spheres (atmosphere, cryosphere, terrestrial, agriculture,
ocean-estuarine, freshwater), with **first-class linkage to the actual
data** each site produces. The site is meant to answer not just "where
are the long-term observatories" but:

- *What datasets does H.J. Andrews publish, where do they live, and
  how do I download them programmatically?*
- *Which observatories report dissolved oxygen at 15-minute cadence,
  via ERDDAP, with public-read access, ≥30-year record?*
- *Who are the lead PIs, what's their h-index for this site, what
  funding stream supports them, and what software / data products
  do they maintain?*

## The full per-facility checklist

For every facility row in `facilities`, a "complete" record needs:

### 1. Identity (✅ done, Wave 0–B)

- [x] canonical_name, acronym, parent_org
- [x] country (US + territories + AQ for U.S.-funded Antarctic stations)
- [x] hq.lat / hq.lng (or address for geocoding)
- [x] established (founding year)
- [x] record_length_years + long_term_threshold_met (≥10y per Peters 2013)
- [x] primary_sphere + secondary_spheres
- [x] ecosystem_types + life_zones
- [x] research_areas[] (GCMD-aligned)
- [x] networks[] (LTER, NEON, EFR, LTAR, IOOS RA, …)
- [x] provenance (source_url, retrieved_at, confidence)

### 2. Funding (▶ in progress, Wave H)

- [x] ≥1 funder relationship recorded (parent-agency lineage)
- [▶] amount_usd populated for all federal grants (242 of 889 done)
- [ ] amount_usd populated for all state-appropriation lines
- [ ] amount_usd populated for all foundation grants (mostly via 990s)
- [ ] FY-by-FY time series for the major awards (currently single-year
      snapshots)

### 3. People (▶ in progress, Wave F + I)

- [x] Director / lead PI (≥1 row in facility_personnel for 360 facilities)
- [▶] All current senior scientists (~360 in DB; OpenAlex enrichment
      will multiply this)
- [▶] ORCID for ≥80% of senior scientists (currently 26%)
- [ ] OpenAlex author IDs (0%; CI enrichment)
- [ ] Google Scholar IDs (optional)
- [ ] Photo URL / bio (low priority)
- [ ] Active vs emeritus vs deceased status

### 4. Publications (▶ in progress, Wave H + I + ongoing)

- [▶] ≥3 flagship papers credited per major site (40 LTERs done)
- [ ] **Full per-author publication history** via OpenAlex (target:
      30+ pubs/person × 360 = 10k+ rows; currently 416 pubs / 184
      people)
- [ ] DOI populated for ≥75% of publications (currently 51%)
- [ ] cited_by_count refreshed annually (Crossref / OpenAlex)
- [ ] publication_topics linked to research_areas (currently 0 rows)
- [ ] Authorship graph rich enough for collaborations table

### 5. Data archives & products (NEW, Wave J)

This is the layer the user explicitly asked us to build. For every
facility:

- [ ] ≥1 row in `facility_archives` linking the facility to its
      authoritative data archive (EDI for LTERs, NEON Data Portal for
      NEON sites, NWIS for USGS gauges, NCEI for NOAA labs, etc.)
- [ ] `scope_url` per facility — the per-site search URL into the
      archive (e.g. `https://portal.edirepository.org/nis/browseServlet?searchValue=HBR`)
- [ ] `sample_doi` — at least one canonical DOI for that site's most-
      used dataset
- [ ] ≥1 row in `data_products` per facility (≥10 for the data-rich
      LTER / LTAR / NEON sites)
- [ ] format_slug from `data_formats.csv` (csv / netcdf / parquet /
      etc.)
- [ ] license_slug from `data_licenses.csv`
- [ ] temporal_start / temporal_end coverage

### 6. API endpoints (NEW, Wave J)

- [ ] ≥1 row in `api_endpoints` per archive describing how to
      programmatically fetch the data — REST URL template, OPeNDAP
      base URL, ERDDAP tabledap / griddap, STAC catalog root, etc.
- [ ] schema_url pointing at OpenAPI / DCAT / DataCite metadata
      where available
- [ ] example_call — a runnable curl / wget command

### 7. Cloud storage (NEW, Wave J — minimal scope per user direction)

- [ ] For facilities with public S3 / GCS / Azure buckets, ≥1 row in
      `cloud_buckets` recording: provider + bucket_name + region +
      access_mode. (No object inventories in this pass.)
- [ ] documentation_url for the bucket's public README / docs

### 8. Region & overlay context (✅ partially done)

- [x] facility_regions: which polygon overlays contain this facility
- [ ] watershed / HUC code where applicable (USGS specific)
- [ ] Köppen-Geiger climate zone

## Per-sphere expectations

These are the **prior probabilities** about which archive / format /
API combination each sphere uses. Every research agent should treat
these as defaults to verify, not as facts:

### Atmosphere
- **NOAA-GML stations**: ftp://aftp.cmdl.noaa.gov + https://gml.noaa.gov/data ;
  CSV ASCII flask records; license public-domain-us
- **NADP/NTN/AIRMoN/MDN**: https://nadp.slh.wisc.edu ; CSV per-site
  weekly/biweekly; CC0
- **AmeriFlux** (LBNL): https://ameriflux.lbl.gov ; FLUXNET2015 / BASE
  format ; ameriflux-data-policy ; DOIs at site level (10.17190/AMF/...)
- **DOE ARM**: https://adc.arm.gov ; NetCDF; registered-users
- **TCCON**: https://tccondata.org ; HDF5 + NetCDF; CC-BY 4.0
- **EPA CASTNET / IMPROVE**: CSV; EPA-public

### Cryosphere
- **NSIDC**: https://nsidc.org/data ; HDF / NetCDF / GeoTIFF;
  license-required (Earthdata Login)
- **USGS Benchmark Glaciers**: https://www.usgs.gov/programs/climate-research-and-development-program/science/usgs-benchmark-glacier-project
  ; CSV mass balance; usgs-public
- **WGMS Fluctuations of Glaciers**: https://wgms.ch/products_fog/
  ; bibliographic
- **NOAA Arctic / Antarctic**: NCEI archives; NetCDF

### Terrestrial / Ecological
- **EDI** (`10.6073` DOI prefix): https://portal.edirepository.org ;
  per-LTER scopes; CSV + EML; CC0 / CC-BY-4.0; EDI's REST API at
  `https://pasta.lternet.edu/package/`
- **NEON Data Portal**: https://data.neonscience.org ; CSV per site
  per data product; neon-data-policy ; bulk download via
  `https://data.neonscience.org/api/v0/data/<DPID>/<SITE>/<YYYY-MM>`
- **NPS-IM Datastore**: https://irma.nps.gov/DataStore/ ; mixed
- **USFS Research Data Archive (RDS)**: https://www.fs.usda.gov/rds ;
  CSV + GeoTIFF; usgs-public-style
- **DataONE**: https://search.dataone.org/ ; federation across
  EDI / KNB / NCAR / etc.

### Agriculture
- **USDA Ag Data Commons**: https://data.nal.usda.gov ; mixed; usda-ars
- **USDA-ARS LTAR**: https://ltar.ars.usda.gov ; bulk via Ag Data
  Commons + per-site CKAN
- **USDA NASS Quick Stats**: https://quickstats.nass.usda.gov ; CSV +
  REST API (api-key required)
- **NRCS SCAN / SNOTEL**: https://www.nrcs.usda.gov/wps/portal/wcc/home/
  ; CSV; usgs-public-style

### Aquatic — Ocean & Estuarine
- **BCO-DMO**: https://www.bco-dmo.org ; CSV; CC0
- **NOAA NCEI**: https://www.ncei.noaa.gov ; NetCDF + CSV
- **ERDDAP servers** (each IOOS RA + NCEI runs one): tabledap +
  griddap; CC0 / public-domain-us
- **OOI Data Explorer**: https://dataexplorer.oceanobservatories.org ;
  NetCDF + CSV; CC-BY-4.0
- **NERR CDMO**: https://cdmo.baruch.sc.edu ; CSV; nerrs-data-policy
- **MarineGEO Smithsonian**: https://marinegeo.github.io/data ; CSV +
  R packages
- **OBIS / GBIF**: occurrence records; CC-BY-4.0

### Aquatic — Freshwater
- **USGS NWIS**: https://waterdata.usgs.gov ; tabledap-like REST +
  CSV/RDB; usgs-public
- **USGS WEBB**: per-site pages on water.usgs.gov ; CSV
- **EPA WQX / Water Quality Portal**: https://www.waterqualitydata.us
  ; CSV + WaterML; epa-public
- **GLEON**: per-lake S3 buckets / FigShare / Zenodo deposits
- **NSF NEON aquatic**: same NEON Data Portal as terrestrial

## Cloud-storage prior

Buckets we know exist (knowledge-base; verify on CI):

- `s3://noaa-goes16` / `noaa-goes17` / `noaa-goes18` (NOAA GOES on AWS,
  public-anon-egress)
- `s3://noaa-nexrad-level2` (NEXRAD level-2 radar, requester-pays)
- `s3://nasa-cumulus-prod-public-protected/` (NASA Earthdata Cloud)
- `s3://nrel-pds-` family (NREL public data on AWS)
- `s3://usgs-landsat` (Landsat Collection 2, requester-pays)
- `s3://nasa-3dep-` (USGS 3DEP elevation on AWS)
- `s3://noaa-himawari-` (Japan-NOAA satellites)
- `s3://noaa-gfs-bdp-pds` (GFS forecast on AWS)
- `s3://copernicus-` (Sentinel on AWS, EU)
- `s3://ornldaac-` (ORNL DAAC, Earthdata Login)
- `s3://ldsl-public` (LDSL data on AWS)
- `s3://neon-aop-products` (NEON AOP airborne, public-read)
- `s3://earthengine-public` (Google Earth Engine archive on GCS)
- `s3://opendata.gleon.org` (GLEON, varies)
- `s3://waterdata` (USGS — ad-hoc)
- `s3://noaa-coastwatch-` (NOAA CoastWatch)

The Wave-J cloud-bucket research agent should verify each + add any
sphere-specific buckets it knows.

## Self-evaluation discipline

Every Wave-J research agent must, at the end of its run, write a one-
paragraph **self-critique** in its report describing:

1. Which facilities it was confident about, with sources from training.
2. Which facilities it could not confidently characterise (so the
   loop knows where to look next).
3. Whether the spec's "what a complete record looks like" applies
   cleanly to its sphere, or whether the spec needs amending (e.g. a
   sphere where there's no canonical archive).

`scripts/eval_progress.py` runs after every wave and re-writes
`agents/PROGRESS.md` with the gap report. The next wave's agents
should start by reading PROGRESS.md and targeting its top gaps.

## Time horizon

This is bigger than a single session. Each iteration:

1. **Read** WORLD_MODEL.md + agents/PROGRESS.md
2. **Pick** the worst-covered cells (e.g. "0% of cryosphere has
   data_products", "data_archives missing for the 32 NPS-IM networks")
3. **Fan out** N parallel research agents tightly scoped to those gaps
4. **Load** their output via the deterministic-ID idempotent loaders
5. **Recompute** the derived tables
6. **Re-export** parquet
7. **Re-run** eval_progress.py
8. **Repeat**

Stop conditions: every facility has all eight checklist items above
populated (or honestly marked `confidence = "low"` and `notes`-flagged
as un-fillable from public sources).
