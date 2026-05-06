# LTO terminal runbook — close the API-enrichment gaps

This document is for a **terminal Claude Code session with full network
access**. The agent that built this branch ran in a sandbox that blocks
`pub.orcid.org`, `api.openalex.org`, `api.nsf.gov`, `api.usaspending.gov`,
and every other external science API ("Host not in allowlist" 403). All
manual / training-data work that could be done is done; what's left is
the API-enrichment work that is intentionally deferred to a workflow
or a terminal session that has unrestricted network.

## What's already done

Branch: `claude/observatory-network-setup-zqxUT` (commit `09e0012` or
later). Run `git log --oneline main..HEAD` for the full history.

| | Count |
|---|---:|
| facilities | 465 |
| people | 360 |
| facility_personnel affiliations | 363 |
| funding_events | 889 (250 with `amount_usd`, $3.06B total) |
| publications | 416 (213 with DOI) |
| authorship rows | 361 |
| people credited with ≥1 publication | **184 / 360 (51%)** |
| people with verified ORCID | **93 / 360 (26%)** |
| people with OpenAlex / Google Scholar ID | 0 / 360 |

## What this runbook will produce

After running through the steps below you should land on something
like:

| | Target |
|---|---:|
| people with verified ORCID | 280–320 / 360 |
| people with OpenAlex ID | 300+ |
| publications | 5,000–15,000 (full per-author histories from OpenAlex) |
| authorship rows | 30,000+ |
| funding_events with exact amounts | 3,000+ |
| total funding | $5–15B aggregate |
| h-indexes / citation totals | Realistic per-person totals (h=20+ for senior researchers) |

## Setup

```bash
git clone https://github.com/tyson-swetnam/lto.git
cd lto
git checkout claude/observatory-network-setup-zqxUT
git pull

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install requests rapidfuzz scholarly  # extras the enrich scripts need

# DuckDB on-disk format isn't portable across versions; rebuild from
# committed parquet so any local DuckDB version works.
python scripts/rebuild_db_from_parquet.py
```

Set a polite-pool email so OpenAlex doesn't rate-limit you:

```bash
export OPENALEX_MAILTO="your.email@example.org"
```

## Step 1 — ORCID backfill (fast, non-destructive)

ORCID's public API needs no key. The script's strict resolver requires:

1. Family name match (case + diacritic-insensitive).
2. Given-name first-token match (handles "Sarah" vs "Sarah J.").
3. At least one `employments[].organisation` fuzzy-matches one of the
   person's known facilities at `--min-conf` ≥ 0.45.

Any mismatch leaves `orcid` NULL — wrong ORCID is worse than missing.

```bash
# Preview first.
python scripts/enrich_people_orcid.py --batch 25 --dry-run

# Apply. ~1.5–2 minutes for the full 267-person backlog at 50 reqs/min.
python scripts/enrich_people_orcid.py --batch 50

# Optionally re-verify the 93 manually-supplied ORCIDs against the API
# to catch any agent hallucinations.
python scripts/enrich_people_orcid.py --reverify
```

A decision log is written to `data/seed/orcid_resolution_log.csv` —
inspect rows where status is `accept` vs `no-employment-match`.

## Step 2 — OpenAlex enrichment (the big one)

OpenAlex has full publication histories for every researcher with an
ORCID. After Step 1 you should have ~280 ORCIDs; this step uses them
to attach OpenAlex author IDs and pull each person's publication list.

```bash
# Backfill OpenAlex author IDs by ORCID lookup (~30 seconds).
python scripts/enrich_people_openalex.py --max-pubs 200

# Inspect coverage.
python -c "
import duckdb
c = duckdb.connect('db/cod_kmap.duckdb', read_only=True)
print('with openalex:', c.execute('SELECT count(*) FROM people WHERE openalex_id IS NOT NULL').fetchone()[0])
print('publications: ', c.execute('SELECT count(*) FROM publications').fetchone()[0])
print('authorship:   ', c.execute('SELECT count(*) FROM authorship').fetchone()[0])
"
```

`--max-pubs 200` is sensible for a first pass. Bump to 500 or 1000
later if you want fuller histories for senior researchers (Likens et
al. easily exceed 500).

For people who don't have an ORCID (so the OpenAlex lookup-by-ORCID
won't work), seed via name + institution:

```bash
python scripts/seed_people_from_openalex.py --top-authors 10
```

This runs through every facility and asks OpenAlex for the top-N
authors at that institution, then matches them by name to the people
table. Useful for capturing co-authors who aren't yet in `people`.

## Step 3 — Google Scholar (optional, slow)

Google Scholar rate-limits aggressively (~1 req every 30s if you're
polite, with frequent CAPTCHAs). Skip unless you specifically need
Scholar IDs for the people page links.

```bash
# Routes via the `scholarly` library when --source scholarly; otherwise
# uses OpenAlex / ORCID metadata to find Scholar IDs (much faster).
python scripts/enrich_people_gscholar.py --source openalex --batch 50
python scripts/enrich_people_gscholar.py --source scholarly --batch 20  # slow path
```

## Step 4 — Funding API enrichment

NSF Award Search returns exact obligated-amount + period for every
LTO award. USAspending.gov covers the broader federal grant + contract
universe (USDA, NOAA, DOE, EPA, USGS, NPS, FWS, NASA, USACE).

```bash
# NSF (LTER cores, NEON, OOI, LTREB, polar). Defaults FY2015–2024.
# Hits the public api.nsf.gov; no key required. ~2 minutes.
python scripts/fetch_funding_nsf.py --start-fy 2015 --end-fy 2024

# USAspending — covers everything else federal. Slower (~10 minutes for
# a full fleet pass at the default rate). Use --include-contracts only
# if you want to capture USDA-FS / NOAA contracted research separately
# from grants.
python scripts/fetch_funding_usaspending.py --include-contracts

# Foundation funding from IRS Form 990 via ProPublica Nonprofit Explorer.
# Mostly relevant for Cary, MBARI, Archbold, Patuxent, RMBL, Mountain
# Lake, etc.
python scripts/fetch_funding_990.py
```

Each script writes to `funding_events` and to a per-funder table in
`db/parquet/`; existing rows are updated rather than duplicated
(`event_id = sha1(funder||facility||award_id||fiscal_year)`).

## Step 5 — Recompute derived tables

After Steps 1–4 the publication graph and funding graph have grown by
1–2 orders of magnitude. Re-derive everything that depends on them:

```bash
# Pairwise co-authorship counts across the publication graph.
python scripts/compute_collaborations.py

# Per-(person, area) metrics + h-index from the LTO computation
# that bypasses publication_topics. Run this if Step 2 added pubs but
# OpenAlex topics aren't loaded.
python scripts/compute_lto_person_metrics.py

# OR, if Step 2 also seeded publication_topics (it does, when OpenAlex
# returns concept tags), use the original cod-kmap pipeline instead:
# python scripts/compute_area_metrics.py

# MVG primary-area assignment per facility / person + the
# research_areas_active "active areas" set used by the Network view.
python scripts/compute_primary_groups.py
```

## Step 6 — QA + parquet export

```bash
python scripts/qa.py                  # data-quality gate; exits non-zero on failure
python scripts/export_parquet.py      # 25 parquet tables → db/parquet/ + public/parquet/
python scripts/build_web_overlays.py  # only if upstream overlay GeoJSON moved
```

Common QA failures:

- *facilities without coordinates* → run
  `python scripts/ingest.py` (without `--skip-geocode`) to pull lat/lng
  from `hq.address` via OpenStreetMap Nominatim.
- *vocab drift between schema/vocab and public/vocab* →
  `cp schema/vocab/*.csv public/vocab/`.
- *unknown research_area slug* → check the agent's source URL; either
  add a row to `schema/vocab/research_areas.csv` or fix the offender.

## Step 7 — Commit + push

```bash
git status
git add public/parquet/ public/facilities.geojson db/parquet/ data/seed/
git commit -m "data refresh: ORCID + OpenAlex + NSF + USAspending enrichment"
git push origin claude/observatory-network-setup-zqxUT
```

Then either merge `claude/observatory-network-setup-zqxUT` into `main`
to trigger the GitHub Pages deploy, or rebase the existing PR.

## Step 8 — Verify

```bash
# Local server.
python -m http.server 5173
open http://localhost:5173/
```

Tabs to spot-check:

- **Map** — every primary sphere should be coloured; the legend
  toggle (color by sphere ↔ facility-type) should work.
- **Browse** — text search + sphere / ecosystem-type / life-zone
  facets + ≥10y threshold filter.
- **Network** — the MVG diagram should render polygons sized by the
  `research_areas_active.n_facilities` you just recomputed.
- **People** — pubs / cites / h-index columns should now have real
  numbers for ~300+ of 360 people; sort by composite, by pubs, by
  citations, by h-index.
- **SQL** — try the canned query "Person research areas (by
  publication topics)".
- **Stats** — the area-coverage matrix should show polygons coloured
  by funding density, with the funder-vs-area heatmap rendered.
- **Docs** — the eight LTO docs pages should render without 404.

## Troubleshooting

### OpenAlex returns 429 Too Many Requests

Set `OPENALEX_MAILTO` and retry. The polite pool is much faster.

### ORCID `--reverify` is removing some manually-supplied ORCIDs

Expected. The strict resolver only keeps an ORCID when an
`employments[]` entry matches a known facility at conf ≥ 0.45. Some of
the agent-supplied ORCIDs were guesses; they get nulled and the
employment-based search reattaches the correct one (or leaves NULL).

### NSF Award Search returns "no awards" for a known LTER

The Award Search API matches on **awardee**, not on PI institution.
Pass `--facility-id <id>` to drive a fallback search by `canonical_name`
+ `acronym`. If still no hit, the award is probably under a sub-awardee
relationship — leave it for `fetch_funding_usaspending.py` which sees
the prime-recipient layer.

### `compute_collaborations.py` seg-faults / OOMs

The full authorship graph after OpenAlex enrichment can be ~30k–100k
rows. Bump Python's recursion limit and use `--max-people 500` if the
script offers it. Otherwise just run the batched form:

```bash
python scripts/compute_collaborations.py --batch 200
```

### Parquets are huge after enrichment

Expected — `publications.parquet` will go from ~20KB to ~10–30MB if
you pulled full author histories. The deploy workflow handles them
fine via DuckDB-Wasm HTTP-range reads. If you want to constrain size,
re-run `enrich_people_openalex.py --max-pubs 50` to cap at the most
recent / most cited.

### Sandbox-only fallback

If you find yourself back in a network-restricted environment and need
to extend coverage, the pattern that works is the parallel-sub-agent
fan-out used in `agents/H-FUND-PUB.md` and `agents/R-PEOPLE.md`:
training-data-knowledge agents writing single-Write JSON files into
`data/raw/<AGENT>/{publications,funding_events,people}.json`, then
loaded via `scripts/load_lto_{people,funding,publications}.py`. Each
loader is idempotent on a deterministic ID hash so re-runs upsert
rather than duplicate.

## Reference

- Wave model + agent architecture: `agents/README.md`
- People-side schema: `agents/R-PEOPLE.md`
- Funding + publications schema: `agents/H-FUND-PUB.md`
- Six-sphere data model: `docs/data-model.md`
- Pipeline architecture: `docs/methods.md`
- Loop pattern: `docs/loops.md`
