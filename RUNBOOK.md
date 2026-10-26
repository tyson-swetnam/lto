# LTO terminal runbook — close the API-enrichment gaps

This document is for a **terminal Claude Code session with full network
access**. The agent that built this branch ran in a sandbox that blocks
`pub.orcid.org`, `api.openalex.org`, `api.nsf.gov`, `api.usaspending.gov`,
and every other external science API ("Host not in allowlist" 403). All
manual / training-data work that could be done is done; what's left is
the API-enrichment work that is intentionally deferred to a workflow
or a terminal session that has unrestricted network.

## What's already done

Branch: `main` (the DuckLake store, `scripts/lto_db.py` and
`scripts/rebuild_lake_from_parquet.py`, landed there; the older
`claude/observatory-network-setup-zqxUT` branch predates them and its
setup fails at the first lake command).

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
git checkout main
git pull

python -m venv .venv && source .venv/bin/activate   # Python >= 3.11
pip install -r requirements.txt   # pins duckdb==2.0.0; includes requests + rapidfuzz
pip install scholarly             # only for Step 3's slow path

# The store of record is a local DuckLake (db/lto_catalog.sqlite +
# db/lake/, gitignored). Build it from the committed parquet:
python scripts/rebuild_lake_from_parquet.py
```

OpenAlex requires an API key on every request (the old `mailto=` /
`OPENALEX_MAILTO` "polite pool" no longer applies, and the scripts do not
send an email address). Set the key before Step 2:

```bash
export OPENALEX_API_KEY="…"
```

Every script below writes to the lake through `scripts/lto_db.py`, one
snapshot per run with a commit message naming the script. To see what a
step changed:

```bash
python - <<'PY'
import sys; sys.path.insert(0, "scripts"); import lto_db
c = lto_db.connect(read_only=True)
for r in lto_db.rows(c, "SELECT snapshot_id, snapshot_time::VARCHAR, commit_message "
                        "FROM lake.snapshots() ORDER BY 1 DESC LIMIT 10"):
    print(*r)
PY
```

`ducklake_table_changes('lake', 'main', '<table>', <from>, <to>)` lists
the rows a range of snapshots inserted, updated or deleted. Experiment on
a scratch lake by setting `LTO_LAKE_CATALOG=/tmp/x/cat.sqlite` before the
rebuild and every later command (and unset `LTO_LAKE_DATA`, or point it
inside `/tmp/x/`: the rebuild refuses to put a scratch catalog on
`db/lake/`). With a scratch catalog, `export_parquet.py` and
`export_view_caches.py` write to `/tmp/x/export/`, not `public/`; pass
`--out` / `--geojson` explicitly to publish from it.

Lake writes are serialised: each script's transaction holds a lock on
`<catalog>.lock`, so two steps run at once queue rather than conflict
(a waiting one prints `[lock] … waiting`). Readers never wait.

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
import sys; sys.path.insert(0, 'scripts'); import lto_db
c = lto_db.connect(read_only=True)
print('with openalex:', lto_db.scalar(c, 'SELECT count(*) FROM people WHERE openalex_id IS NOT NULL'))
print('publications: ', lto_db.scalar(c, 'SELECT count(*) FROM publications'))
print('authorship:   ', lto_db.scalar(c, 'SELECT count(*) FROM authorship'))
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

Google Scholar itself is never queried (it blocks automated access and
answers with CAPTCHAs). Scholar user ids come from places that link them:

```bash
# ORCID records: external identifiers and "Websites & social links" (the
# person put the link there themselves). Safe to write directly.
python scripts/enrich_people_gscholar.py --source orcid
# The person's own homepage_url: kept only when the page links exactly one
# Scholar id and names the person. Dry-run and review every hit first: a
# lab or site footer can link someone else's profile (on 2026-10-26 the NTL
# person pages all linked one id). Write reviewed hits through an
# R-PEOPLE2-BIO batch (google_scholar_id + google_scholar_source_url).
python scripts/enrich_people_gscholar.py --source homepage --dry-run
# OpenAlex author records (ids.scholar) — empty for every author we hold as
# of 2026-10-26, kept for when OpenAlex fills it again.
python scripts/enrich_people_gscholar.py --source openalex
```

Every id is stored with `people.google_scholar_source_url`. The bio and
research batches (`agents/R-PEOPLE.md`) also record a Scholar id when an
official profile page links it.

## Step 4 — Funding API enrichment

NSF Award Search returns exact obligated-amount + period for every
LTO award. USAspending.gov covers the broader federal grant + contract
universe (USDA, NOAA, DOE, EPA, USGS, NPS, FWS, NASA, USACE).

```bash
# NSF (LTER cores, NEON, OOI, LTREB, polar). Defaults FY2015–2024.
# Hits the public api.nsf.gov; no key required. ~2 minutes.
python scripts/fetch_funding_nsf.py --start-fy 2015 --end-fy 2024

# USAspending — covers everything else federal. DO NOT write a fleet-wide
# run until its output has been reviewed. Recipient searches run at award
# level and keep an award only when its Recipient Name contains the search
# string and, for a row with a description_match (every university-hosted
# lab or LTER), its Description contains the match; only an override row
# with no match (a facility that IS the recipient: WHOI, MBL, Bigelow) takes
# the recipient's portfolio. Until 2026-10-26 the fast path ignored
# description_match (a default run gave Friday Harbor all 7,439 UW grants
# of FY2015-24, Hatfield 2,804 OSU grants, ...) and the parent_org auto
# search took whole portfolios (every University of California award on
# White Mountain, every UNM award on each UNM facility). Auto mode
# (--allow-auto-recipient) now needs the facility's canonical_name in the
# award Description. Transactions are matched to a searched award by its
# generated_internal_id, an award goes to one facility, and a
# whole-recipient search skips awards naming another facility's match. A dry run on 2026-10-26 (FY2015-24, grants): 75
# facilities, would-write 3,668 rows, 2,820 new, 2,745 of them on WHOI, MBL,
# Bigelow and the Monterey Bay Aquarium. Always dry-run first and read the
# per-facility counts and the "searched:" / "other recipients:" lines:
python scripts/fetch_funding_usaspending.py --dry-run
# (--include-contracts also pulls USDA-FS / NOAA contracts.)

# NERR / NEP awards (NOAA CFDA 11.420, EPA CFDA 66.456), pinned award by
# award in data/funding_overrides/usaspending_award_whitelist.csv: these
# facilities never get a recipient or parent_org search. ~10 seconds.
# A re-run adds nothing unless USAspending has new actions on those awards.
python scripts/fetch_funding_usaspending.py --network nerrs,nep --start-fy 2008 --end-fy 2026
# then python scripts/apply_facility_fixes.py (its superseded-by-award rows
# drop the recalled amounts the awards replace)

# Foundation funding from IRS Form 990 via ProPublica Nonprofit Explorer.
# Mostly relevant for Cary, MBARI, Archbold, Patuxent, RMBL, Mountain
# Lake, etc.
python scripts/fetch_funding_990.py
```

Each script `MERGE`s into the lake's `funding_events` on a deterministic
`event_id = hash(funder||facility||award_id||fiscal_year)`, so a re-run
never duplicates a row. `fetch_funding_usaspending.py` is insert-only:
an existing event is never updated, so a year whose obligations change at
USAspending keeps its old amount until that event is removed. It writes
one row per award per fiscal year of its actions (net obligation, so a
de-obligation year can be negative), counts award type codes 02-05 plus
F001/F002 (the API's grants group; F001/F002 carry the FY2025-on awards),
and with `--dry-run` prints per facility how many rows a real run would
write and how many are new. `--facility-id` takes a comma-separated list
and `--network` limits the run to network members. Without
`--allow-auto-recipient` it queries only facilities with a recipient
override or whitelisted award ids. Any failed query (a dropped
connection, a 5xx) fails that facility: nothing is written for it, the
`[done]` line counts it under `failed=`, and the script exits 1 naming
the `--facility-id` list to re-run. A clean `new=0` therefore means every
facility was actually queried. Nothing reaches
`public/parquet/` until Step 6.

## Step 5 — Recompute derived tables

After Steps 1–4 the publication graph and funding graph have grown by
1–2 orders of magnitude. Re-derive everything that depends on them:

Run them in this order. Each rewrites its tables in the lake in one
snapshot; `export_parquet.py` (Step 6) publishes them.

```bash
# 1. Pairwise co-authorship counts across the publication graph.
python scripts/compute_collaborations.py

# 2. person_areas from publication topics (needs publication_topics,
#    which Step 2 seeds when OpenAlex returns topic tags).
python scripts/compute_person_areas.py
#    If publication_topics is still empty, use the LTO fallback instead,
#    which infers areas from facility affiliations:
# python scripts/compute_lto_person_metrics.py

# 3. MVG primary-area assignment per facility / person + the
#    research_areas_active "active areas" set used by the Network view.
python scripts/compute_primary_groups.py

# 4. Per-area metrics, funding-by-area and the coverage matrix. Must run
#    AFTER compute_primary_groups: its facility/funder funding tables and
#    area_coverage_matrix join facility_primary_groups, so running it
#    first builds them from stale groups.
python scripts/compute_area_metrics.py

# 5. Precomputed KMap/PCL layout for the Network view.
python scripts/build_mvg_layout.py
```

## Step 6 — QA + parquet export

```bash
python scripts/qa.py                  # data-quality + integrity gate; exits non-zero on failure
python scripts/lake_maintenance.py    # optional: compact files, expire snapshots > 90 days
python scripts/export_parquet.py      # every TABLES entry → public/parquet/ + facilities.geojson
python scripts/export_view_caches.py  # Browse / People / Projects JSON caches
python scripts/build_web_overlays.py  # only if upstream overlay GeoJSON moved
```

`export_parquet.py` fails, writing nothing, if any table in its `TABLES`
list is missing from the lake; run the script that produces it. Its
output is deterministic, so an unchanged table produces an unchanged file.

Common QA failures:

- *integrity: duplicate key / orphaned reference / CHECK / column drift*
  → the lake does not enforce `schema/schema.sql`'s keys at write time;
  `qa.py` does, plus the derived tables' keys and the soft references
  (`lto_db.DERIVED_CONSTRAINTS` / `SOFT_REFERENCES`). A *derived-table*
  orphan after deleting or merging people means the `compute_*` /
  `build_mvg_layout.py` step has not been re-run since.
  The message names the table, constraint and count. Find the run that
  introduced it with `lake.snapshots()` and `ducklake_table_changes`, fix
  the loader input, and re-run the loader (or restore the table from an
  earlier snapshot).

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
git add public/parquet/ public/facilities.geojson public/cache/ data/seed/
git switch -c data/enrichment-$(date +%Y%m%d)
git commit -m "data refresh: ORCID + OpenAlex + NSF + USAspending enrichment"
git push -u origin HEAD
```

Then open a PR against `main`; merging it triggers the GitHub Pages
deploy.

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

Check that `OPENALEX_API_KEY` is set in the shell running the script
(every OpenAlex call needs it), then retry with a smaller `--limit`.
Keyed clients get OpenAlex's documented rate limits; there is no
email-based polite pool any more.

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
rows. The script is a single SQL self-join inside DuckDB; to shrink the
edge set, keep only repeat co-authors:

```bash
python scripts/compute_collaborations.py --min-co-pubs 2
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
