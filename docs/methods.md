# Methods

`lto` is a research-agent ETL on top of a static visualisation stack.
Source records are produced by subagents (one markdown spec per agent
under `agents/`), loaded into a DuckLake store of record, validated by a
QA gate, and exported as Parquet + GeoJSON for the browser.

The agents worked in two modes, and the data still shows both:

- **Recall (2026-04 to 2026-05).** The facility waves (B–E), the
  first people pass (Wave F), the funding and publication pass
  (`H-FUND-PUB`) and the data-archive wave (Wave J) ran in a sandbox
  without web access, so agents wrote records from model knowledge,
  each citing the source page it named.
- **Fetched (from 2026-10).** The ARID Institute layer, the
  EnviroData-NM and Arizona Water Observatory catalogues, the
  second people pass (R-PEOPLE2), and the LTREB (NSF Award API) and
  NERR / NEP (USAspending.gov) award fetches take every value from a
  page fetched in that run. Nothing in them is filled from recall; a missing value
  stays null.

## Wave model

```
Wave 0  Vendor cod-kmap engine                    (one-time bootstrap)
Wave A  D1 schema deltas + D3 vocab extension     (contracts)
Wave B  R-* facility research agents              (raw JSON per sphere)
Wave C  D2 ingest → DuckLake (db/lto_catalog.sqlite + db/lake/) → public/parquet/
Wave D  F1..F4 frontend + deploy
Wave E  R-XREF reconciliation + coverage report
Wave F  R-PEOPLE-* + R-PEOPLE-LOOP2-* people pass (from recall)
Wave J  J-DATA data archives, products, APIs, buckets (from recall)
ARID    R-ARID, J-ENVIRODATA, J-AZWATER           (fetched, 2026-10-09)
People  R-PEOPLE2 + R-PEOPLE2-BIO                 (fetched + verified, 2026-10-22)
Enrich  two ORCID-keyed OpenAlex passes           (complete, 2026-10-23)
Weekly  data refresh (Sun) + URL-health sweep (Mon), each opens a PR
```

Each agent wave (B–F, J, ARID, People) is a single parallel batch over
its sub-agents; the parent runs the next wave only after every agent in
the prior wave has emitted its JSON. Enrich and Weekly are script runs,
by hand and in CI respectively, not agent batches. The entry points are `scripts/ingest.py` (Wave C),
`scripts/load_arid.py` and `scripts/load_lto_archives.py` (ARID and the
archive catalogues), `scripts/load_people_research.py` (R-PEOPLE2), the
enrichment scripts listed under *Identifier strategy* below,
and `scripts/qa.py` as the gate before every export.

## Store of record

The pipeline writes to a [DuckLake](https://ducklake.select) on the
operator's machine, run by DuckDB 2.0: a SQLite catalog at
`db/lto_catalog.sqlite` and parquet data files under `db/lake/`. Every
script opens it through `scripts/lto_db.py`.

- **History.** Each loader, enricher or `compute_*` run commits one
  snapshot with an author and a message naming the script. Earlier
  states stay queryable (`AT (VERSION => n)`), and
  `ducklake_table_changes()` lists the rows a run inserted, updated or
  deleted: for example, who a facility's director was before the last
  personnel load. `scripts/lake_maintenance.py` compacts the lake and
  expires snapshots older than 90 days.
- **Constraints.** DuckLake does not enforce primary keys, foreign keys,
  UNIQUE or CHECK constraints. `schema/schema.sql` still declares them,
  and `scripts/qa.py` checks every one against the lake before export,
  together with NOT NULL, the derived tables' keys, the undeclared
  (soft) references and the column list of every table: 249 checks as
  of 2026-10-23 (223 declared in `schema.sql`, 17 derived keys, 9 soft
  references). A
  duplicate key or an orphaned reference therefore fails QA rather than
  the `INSERT`. Loaders upsert with `MERGE` on de-duplicated keys, run
  the same check before they commit, and take an exclusive lock for the
  length of their transaction, so two runs never interleave writes.
- **What is published.** The lake is local working state and is not
  committed. `scripts/export_parquet.py` writes every table to
  `public/parquet/` in a deterministic row order, and those committed
  files are the canonical copy: the site reads them, and a fresh clone
  (or a pull) rebuilds the lake from them
  (`scripts/rebuild_lake_from_parquet.py`, which always reads
  `public/parquet/` unless told otherwise). An export from a scratch
  lake goes next to that lake, not into `public/`.

## Sub-agent roster

| Bundle | Agents | Scope |
|---|---|---|
| Wave-B facility | 11 | One per sphere or sub-network: `R-ATM`, `R-CRY`, `R-TER-LTER`, `R-TER-EFR`, `R-TER-NEON`, `R-TER-OTHER`, `R-AGR`, `R-AQ-OCEAN-CULL`, `R-AQ-FRESH`, plus `R-XREF` and `R-FUND` |
| Wave-F people | 9 | First people pass, from recall: `R-PEOPLE-LTER`, `R-PEOPLE-NEON`, `R-PEOPLE-EFR`, `R-PEOPLE-AGR`, `R-PEOPLE-OCEAN`, `R-PEOPLE-FRESH`, `R-PEOPLE-ATM`, `R-PEOPLE-CRY`, `R-PEOPLE-OTHER` |
| Loop / repair | 2+ | `R-PEOPLE-LOOP2-EFR`, `R-PEOPLE-LOOP2-ORCID`, etc. — see [loops](./loops.md) |
| Cross-cutting | 2 | `R-XREF` (sphere reconciliation), `R-FUND` (funding flows) |
| Data archives | 11 + 2 | `J-DATA` fan-out (11 `J-A-*` agents, e.g. `J-A-EDI`, `J-A-NEON`, `J-A-USDA`), plus `J-ENVIRODATA` and `J-AZWATER` |
| ARID | 1 | `R-ARID` (UNM ARID Institute, partner centers, projects, people) — see [ARID & New Mexico](./arid.md) |
| People, fetched | 2 kinds | `R-PEOPLE2` research batches (51 files) and `R-PEOPLE2-BIO` bio batches (31 files), each checked by an adversarial verifier; spec in `agents/R-PEOPLE.md` |

## Inclusion gate

Facilities are tested against the **Peters et al. 2013 ≥10-year
continuous-record threshold**, stored as `long_term_threshold_met`
(`record_length_years >= 10`). Records below it are kept in the
database with `long_term_threshold_met = false` and are **shown** by
default: the "Show only facilities with ≥10y record" checkbox is off
until a visitor ticks it. As of 2026-10-25, 341 of 440 facilities meet
the threshold and 75 have a record shorter than 10 years. The other 24
have no record length: 13 of them are flagged `false` all the same, so
"not ≥10y" can mean "unknown", and 11 carry no flag at all. The default
view is narrowed instead by the Southwest drylands scope lens (see
[ARID & New Mexico](./arid.md)).

## Provenance

Every facility has a `provenance` row; `qa.py` fails if one is missing.
A real row:

```json
{
  "record_type": "facility",
  "source_url": "https://hubbardbrook.org/",
  "retrieved_at": "2026-05-05",
  "confidence": "high",
  "agent": "R-AQ-FRESH"
}
```

- **`source_url`** is the page the record rests on. It is meant to be
  present on every record, but QA does not yet enforce it: as of
  2026-10-25, 39 of 440 facilities have no provenance row with a
  `source_url`.
- **`retrieved_at`** is the date the agent observed the source. For the
  recall-era waves it is the run date, not a fetch date.
- **`confidence`** is one of `high` (primary agency / institution page),
  `medium` (third-party aggregator), or `low` (inferred or memory-only).
  Low-confidence records are kept and surfaced for manual review.

People rows carry their own provenance: `facility_personnel` has
`source_url`, `retrieved_at` and `confidence` columns. As of 2026-10-25,
of its 1,529 rows, 878 come from R-PEOPLE2 (851 fetched 2026-10-22, 27 on
2026-10-25) and also quote the page in `evidence`, 14 older rows were
re-cited from fetched LTAR, Jornada, ARS (Southwest Watershed Research
Center, Fort Keogh Livestock and Range Research Laboratory) and ORCID
pages through
`data/seed/facility_fixes.csv` on 2026-10-25 (with `evidence`), and 30 come
from R-ARID (fetched 2026-10-09). 587 are recall-era rows dated 2026-04-24
to 2026-05-06, 31 of them with no `source_url`, and 20 rows have no date. Every
bio, research-interests line and ORCID written by R-PEOPLE2 names its
source in a `*_source_url` column.

## Identifier strategy

For the people side:

- The ID priority is **ORCID > OpenAlex > Google Scholar > homepage URL**.
- **A wrong identifier is worse than a missing one.** Every resolver
  leaves the field null rather than guess.
- ORCID format is regex-validated (`^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$`).
- OpenAlex format is regex-validated (`^A\d+$`).
- **R-PEOPLE2** keeps an ORCID only if the verifier fetched it from
  `pub.orcid.org`, the name matches, and it appears on a fetched profile
  page or in an employment at the right institution.
- **`scripts/enrich_people_orcid.py`** searches the ORCID public API.
  The family name must match exactly and the given name agree. When the
  person has a facility on file, the ORCID employment record must also
  share a distinctive token with one of their facilities, and the
  highest-scoring candidate that passes is taken. A person with no
  facility is matched on name alone only if exactly one ORCID fits
  (logged `accept-name-only`); two or more namesakes are left null
  (`ambiguous-name-only`). Every decision is logged in
  `data/seed/orcid_resolution_log.csv`.
- **`scripts/enrich_people_openalex.py`** matches only through a stored
  OpenAlex id or the person's ORCID. Name search is disabled. It needs
  `OPENALEX_API_KEY`. It fills `research_interests` only when the field
  is empty (or holds an earlier OpenAlex-generated list) and never
  overwrites a curated value.
- **Rejected pairs stay rejected.** A `cleared-*` row in the ORCID log
  (79 as of 2026-10-24: 68 dead iDs, 11 belonging to someone else)
  blocks that (person, ORCID) pair, and `qa.py` fails if a
  cleared-as-wrong ORCID comes back. Removed (person, OpenAlex id) pairs
  are listed in `scripts/wipe_misattributed_identifiers.py`, and the
  OpenAlex script will not attach them again.
- **New attributions are reviewed.** In both OpenAlex passes,
  every new or changed attribution was checked against the OpenAlex
  author record, and disputed ones got a second, independent review. An
  id was removed when the reviewers judged it wrong or a merge of
  several people. The decisions are in
  `data/seed/openalex_attribution_review_2026-10-23.csv` (pass 1, 106
  rows: 103 attributions from that pass and 3 earlier misattributions
  found during it; 97 kept, 2 kept but disputed, 7 removed, of which 2
  had both reviewers voting "wrong") and
  `data/seed/openalex_attribution_review_2026-10-24.csv` (pass 2, 232
  rows: 225 kept, 3 kept but disputed, 4 removed, all 4 with both
  reviewers voting "wrong"). Pass 1 stopped after 378 of 1,302 people
  when the OpenAlex daily credit ran out; pass 2 processed the other 924,
  so every person in the queue has been through OpenAlex. Of those 924,
  407 resolved; 478 have neither an ORCID nor an OpenAlex id and 39 have
  an ORCID that OpenAlex does not know, so this method cannot reach them.
- The enrichment scripts are run by hand, following `RUNBOOK.md`. No CI
  workflow runs them. As of 2026-10-25, 611 of 1,329 people have an
  ORCID and 560 an OpenAlex id.

## Weekly loops

Two scheduled workflows rebuild the lake from the committed parquet,
re-export, and open a pull request with the data diff; nothing is
pushed to `main` without review.

- **Data refresh** (`.github/workflows/refresh-data.yml`, Sundays 06:00
  UTC) re-runs `load_arid.py`, `load_lto_archives.py` and
  `backfill_facility_state.py`, then `qa.py`, `export_parquet.py` and
  `export_view_caches.py`. It runs no ingest and no enrichment.
- **URL health** (`.github/workflows/url-health.yml`, Mondays 07:00
  UTC) sends an HTTP HEAD request to every stored URL
  (`scripts/check_url_health.py`), applies pattern-based fixes
  (`scripts/url_hygiene.py`), then runs QA and both exports. Results
  and decisions land in `data/seed/url_health_check.csv` and
  `data/seed/url_hygiene_log.csv`. The 2026-10-23 sweep covered 2,427
  distinct URLs (1,626 ok, 116 templates skipped) and set to null 66
  people homepages that pointed at a bare domain (51) or a generic
  staff or team page (15).

## Static stack

The browser side is **DuckDB-Wasm + MapLibre, no build step**:

- `index.html` defines an importmap that pulls `maplibre-gl` (4.7.1) and
  `@duckdb/duckdb-wasm` (pinned `1.33.1-dev65.0`, DuckDB core 1.5.6)
  from esm.sh. The browser reads the exported parquet over HTTP range
  requests; it does not attach the lake.
- `src/db.js` registers `public/parquet/*.parquet` as DuckDB views and
  re-creates helper views (these don't survive Parquet export).
- `src/views/{list,stats,docs,network,projects,people,datasets,sql}.js`
  render one tab each (`list.js` is Browse, `datasets.js` is Data).
- The deploy workflow (`.github/workflows/deploy.yml`) stages only
  `index.html`, `favicon.svg`, `src/`, `public/`, and `docs/`. Everything
  else (`agents/`, `scripts/`, `schema/`, `data/raw/`) is excluded from
  the live site.
