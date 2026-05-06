# J-DATA — Data-archive, products, endpoints, cloud-buckets contract

This is the spec for the **Wave J** research-agent fan-out. Each
agent emits one or more JSON files into
`data/raw/<AGENT_ID>/<artifact>.json`; the loaders
`scripts/load_lto_archives.py` and `scripts/load_lto_publications.py`
ingest them. Every record is idempotent on a deterministic ID hash.

## Scope (per-sphere fan-out)

| Agent | Targets |
|---|---|
| `J-A-EDI` | EDI Data Repository — every LTER, every LTREB site with an EDI scope. ~30 archives, ~150+ scope rows. |
| `J-A-DATAONE` | DataONE federation member nodes (KNB, ESS-DIVE, USGS-CIDA, ARM, ORNL-DAAC, etc.). |
| `J-A-NEON` | NEON Data Portal — DPID catalog, per-site bulk URLs, AOP S3 bucket, eddy-covariance bundle DOIs. |
| `J-A-NCEI-ERDDAP` | NOAA NCEI archives + ERDDAP servers (NCEI, NDBC, GLOS, AOOS, NANOOS, IOOS-DMAC, GCOOS). |
| `J-A-USGS` | USGS NWIS + WEBB + ScienceBase + Water Quality Portal + Streamstats + 3DEP + Landsat. |
| `J-A-USDA` | USDA Ag Data Commons + LTAR data + NASS Quick Stats + SCAN/SNOTEL + USFS RDS. |
| `J-A-AMERIFLUX-ARM` | LBNL AmeriFlux + DOE ARM Data Discovery + TCCON archives + NADP. |
| `J-A-NSIDC-CRY` | NSIDC + NOAA Arctic/Antarctic + WGMS + USGS Benchmark Glaciers + USGS-NOROCK. |
| `J-A-OCEAN-AGGS` | BCO-DMO + OOI Data Explorer + NERR CDMO + MarineGEO + OBIS + WHOI Open Access + Scripps SIO archives. |
| `J-A-ESS-DIVE-DOE` | ESS-DIVE (DOE BER) + NGEE-Arctic + NGEE-Tropics + SPRUCE + ARM mobile-facility archives. |
| `J-A-CLOUD` | Cloud-bucket inventory (AWS Open Data, NOAA Big Data, NASA Earthdata Cloud, USGS public buckets, GCS public, Azure Open Datasets). Per user direction: bucket_name + region + access_mode only (no object inventories). |

## Output format

Per agent, one folder `data/raw/<AGENT_ID>/` with up to four files:

### `archives.json`

```json
[
  {
    "archive_id": "edi",
    "name": "Environmental Data Initiative Repository",
    "organization": "EDI / NSF",
    "archive_type": "repository",
    "base_url": "https://portal.edirepository.org/",
    "api_url": "https://pasta.lternet.edu/package/",
    "api_doc_url": "https://pastaplus-core.readthedocs.io/",
    "api_type": "rest",
    "license_slug": "edi-data-policy",
    "doi_prefix": "10.6073",
    "notes": "PASTA REST API; EML metadata; per-site scope-namespace pattern"
  }
]
```

### `facility_archives.json`

```json
[
  {
    "facility_canonical_name": "Hubbard Brook Experimental Forest",
    "facility_acronym": "HBR",
    "archive_id": "edi",
    "role": "primary",
    "scope_url": "https://portal.edirepository.org/nis/browseServlet?searchValue=knb-lter-hbr",
    "scope_id": "knb-lter-hbr",
    "sample_doi": "10.6073/pasta/c4b7f5b8d8c2a4f0",
    "notes": "EDI scope 'knb-lter-hbr' contains ~200 datasets"
  }
]
```

### `data_products.json`

```json
[
  {
    "facility_canonical_name": "Hubbard Brook Experimental Forest",
    "facility_acronym": "HBR",
    "archive_id": "edi",
    "title": "Hubbard Brook Experimental Forest: Daily Streamflow by Watershed, 1956 - present",
    "doi": "10.6073/pasta/3edd49ee72f1d9e74e6f1cfb52b2a9b4",
    "identifier": "knb-lter-hbr.2.20",
    "url": "https://portal.edirepository.org/nis/mapbrowse?packageid=knb-lter-hbr.2.20",
    "format_slug": "csv",
    "license_slug": "edi-data-policy",
    "temporal_start": "1956-01-01",
    "temporal_end": "2024-12-31",
    "bbox_min_lon": -71.78, "bbox_min_lat": 43.92, "bbox_max_lon": -71.70, "bbox_max_lat": 43.97,
    "variables_text": "watershed, date, streamflow_mm",
    "citation": "Campbell, J.L. 2024. Hubbard Brook Experimental Forest…",
    "confidence": "medium",
    "notes": "Synthetic record — verify identifier against pasta API in CI"
  }
]
```

### `api_endpoints.json`

```json
[
  {
    "archive_id": "edi",
    "facility_canonical_name": null,
    "path_or_url": "https://pasta.lternet.edu/package/eml/{scope}/{identifier}/{revision}",
    "method": "GET",
    "purpose": "metadata",
    "response_format": "application/xml",
    "schema_url": "https://eml.ecoinformatics.org/",
    "example_call": "curl https://pasta.lternet.edu/package/eml/knb-lter-hbr/2/20",
    "notes": "EML 2.2 metadata; REST contract documented at PASTA+ docs"
  }
]
```

### `cloud_buckets.json`

```json
[
  {
    "archive_id": "neon-data-portal",
    "facility_canonical_name": null,
    "provider": "s3",
    "bucket_name": "neon-aop-products",
    "region": "us-west-2",
    "access_mode": "public-read",
    "documentation_url": "https://www.neonscience.org/data-collection/airborne-remote-sensing",
    "sample_prefix": "2019/FullSite/D14/2019_JORN_3/",
    "notes": "NEON AOP discrete-return / hyperspectral / waveform LiDAR products"
  }
]
```

## Hard constraints (every agent)

- **DO NOT use WebFetch.** Sandbox blocks every external API
  (`Host not in allowlist`). Use training-data knowledge.
- **NEVER hallucinate a DOI / bucket name / URL.** If unsure, leave the
  field null and set `confidence = "low"`.
- **DOIs must match `^10\.\d{4,9}/[\w./()<>:;-]+$`.** Drop any that don't.
- **Bucket names must be lower-cased and look right** for the provider
  (S3: `s3://<name>`, GCS: `gs://<name>`, Azure: `<account>.blob.core.windows.net`).
- **Sample prefixes must NOT include a trailing wildcard** (`*` etc.) —
  use a literal prefix you'd give to `aws s3 ls --recursive`.
- **Single Write per file.** No streaming Edits.
- **`facility_canonical_name`** when present must match an existing row
  in the `facilities` table (case-insensitive). The loader fuzz-matches
  on canonical_name + acronym.
- **`agent` provenance**: set in `notes` or alongside; loader adds
  `source = <agent-id>` automatically.

## Self-critique discipline

End your run with a paragraph addressing:

1. Which facilities you covered with **high** confidence (cite a
   source URL / DOI from training data).
2. Which facilities you skipped because you couldn't characterise
   their archive cleanly — feed those names back so the next loop
   can target them.
3. Whether the WORLD_MODEL spec applied to your sphere or needs
   amendment (e.g. cryosphere has no single canonical archive — should
   we add a "fragmented" archive_type?).

## Self-eval reads & writes

After every wave the parent runs:

```bash
python scripts/eval_progress.py
```

…which queries the DuckDB and rewrites `agents/PROGRESS.md` listing
per-facility checklist coverage. The next wave's agents should
**start by reading PROGRESS.md** and only target facilities still
below threshold.
