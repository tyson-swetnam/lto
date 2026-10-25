# Data model

The logical schema is defined in `schema/schema.sql`. The pipeline stores
it in a DuckLake (DuckDB 2.0; catalog `db/lto_catalog.sqlite`, data
`db/lake/`) and exports its tables (all but the `cpi_index_us` and
`ingest_runs` bookkeeping tables) to `public/parquet/`. The browser runs
DuckDB-Wasm 1.33.1-dev65.0 (DuckDB 1.5.6) and registers each table as a
Parquet-backed view (see `src/db.js`). Tables that only the SQL tab reads,
and all the helper views, are registered on the first visit to the SQL tab.
The helper views don't survive Parquet export, so they **must be defined
in both** `schema/schema.sql` and `src/db.js` (see
[Helper views](#helper-views)).

## Constraints are logical, enforced by QA

`schema/schema.sql` declares every primary key, foreign key, UNIQUE and
CHECK constraint, and those declarations are the contract. DuckLake
cannot store them, so:

- The lake's tables are created **column-only** from that file: names,
  types, `NOT NULL` and `DEFAULT`, which the lake does enforce. The full
  DDL runs only in a throwaway in-memory database that serves as the
  specification.
- **Nothing rejects a duplicate key or an orphaned reference at write
  time.** `scripts/qa.py` reads every constraint from the specification
  and checks it against the lake: duplicate primary/unique keys,
  foreign-key values with no parent row, failed CHECKs and NULLs in NOT
  NULL columns. Any violation fails QA, and export follows QA. Loaders
  run the same check on the tables they touched before they commit, so
  a bad batch rolls back.
- Loaders upsert with `MERGE` on the declared key, de-duplicating the
  source first. (`INSERT OR REPLACE` and `ON CONFLICT` need a real
  primary key and are not available.)
- Updating a referenced row is allowed. Native DuckDB refused to update
  a facility that personnel rows pointed at. The lake does not, so
  changing a key without updating its children leaves orphans, which
  QA then reports.
- A few relationships are deliberately **soft**: the project tables and
  the person-registry tables carry ids without declaring foreign keys.
  They are checked like declared ones all the same (the list is
  `SOFT_REFERENCES` in `scripts/lto_db.py`), by `qa.py` and by the
  loaders' pre-commit check, so deleting a facility that a registry row
  still names rolls back.
- The **derived tables** (`person_primary_groups`, `person_area_metrics`,
  `mvg_node_layout`, …) are not in `schema.sql` because each is
  recomputed wholesale, but the views and caches join on their keys.
  Their keys and references (`DERIVED_CONSTRAINTS`) are checked by
  `qa.py` and by the script that writes them. A parent change does not
  re-check them, so after people are deleted or merged QA fails until
  the `compute_*` step is re-run.
- QA also compares each table's columns with `schema.sql` and fails on
  a missing, extra or retyped column.
- **One writer at a time.** Each run's transaction holds an exclusive
  lock on `<catalog>.lock`; a second writer waits. Two overlapping
  transactions would otherwise each pass the pre-commit check against
  their own snapshot and commit a duplicate key or an orphan between
  them.

## History

Every write to the lake is a snapshot. Each loader, enricher and
`compute_*` run commits one snapshot with an author and a message naming
the script, so the lake keeps the history that the parquet files
(one state per commit) do not:

```sql
SELECT snapshot_id, snapshot_time, author, commit_message
FROM lake.snapshots() ORDER BY snapshot_id DESC;

-- a table as it was at snapshot 12
SELECT * FROM facility_personnel AT (VERSION => 12) WHERE facility_id = '…';

-- rows inserted / updated (pre- and post-image) / deleted between two snapshots
SELECT change_type, facility_id, person_id, role
FROM ducklake_table_changes('lake', 'main', 'facility_personnel', 12, 15);
```

This history is local to the machine that holds the lake: it is not
committed, snapshot ids differ between clones, a rebuild from parquet
(`scripts/rebuild_lake_from_parquet.py`) starts a fresh history, and
`scripts/lake_maintenance.py` expires snapshots older than 90 days by
default. The committed `public/parquet/` history in git is the long-term
record.

## Core facility tables

These are inherited from the cod-kmap engine. `facilities` carries the
LTO additions noted below.

| Table | Purpose |
|---|---|
| `facilities` | One row per observatory. `facility_id` (hash), `canonical_name`, `acronym`, `parent_org`, `facility_type`, `country`, `region`, `hq_address`, `hq_lat`, `hq_lng`, `url`, `established`, `ror`, plus the LTO columns `record_length_years`, `long_term_threshold_met` and `data_portal_url`. `state` is derived from the HQ point by `scripts/backfill_facility_state.py` and drives the New Mexico and Southwest drylands lenses (see [ARID & New Mexico](./arid.md)). |
| `provenance` | `(record_type, record_id, source_url, retrieved_at, confidence, agent)`: where each record (mostly facilities) came from, keyed by `record_type` and `record_id`. QA requires one for every facility. |
| `locations` | One row per HQ + satellite location. `facility_id`, `label`, `address`, `lat`, `lng`, `role` (headquarters / field-station / observatory / office / vessel / mooring-array / buoy / lab / weather-station / streamgage / flux-tower / glacier-site / snow-station). |
| `funders` | Funder catalogue (NSF, USDA, NOAA, DOE, USGS, NASA, EPA …). |
| `funding_events` | One row per funder → facility allocation: `funder_id`, `facility_id`, `amount_usd`, `fiscal_year`, `period_start`, `period_end`, `award_id`, `program`, `relation`, `source`, `source_url`, `retrieved_at`, `confidence`. Filled by the funding research agents in May 2026. As of 2026-10-25 it has 937 rows, 383 of them with a dollar amount. 340 of those amounts are labelled as recall in `source` (mostly "training-data recall"), not fetched from an award database; the other 43 are the four LTREB award series, fetched from the NSF Award API on 2026-10-25 (`source` 'NSF Award Search', by `scripts/fetch_funding_nsf.py`). The other 554 rows carry no amount. |
| `networks` | Controlled vocabulary from `schema/vocab/networks.csv`. |
| `network_membership` | `(facility_id, network_id, role)` join table. |
| `research_areas` | `area_id` slugs from `schema/vocab/research_areas.csv` (GCMD-aligned). |
| `area_links` | `(facility_id, area_id)` join table. |

## LTO extension tables

Added in Wave A for the sphere model. There were six spheres at first;
Arid became the seventh in August 2026 (see [Spheres](./spheres.md)).

| Table | Purpose |
|---|---|
| `spheres` | Catalogue of the seven spheres + display labels. |
| `ecosystem_types` | EcoTrends + WWF biome slugs (`schema/vocab/ecosystem_types.csv`). |
| `life_zones` | Holdridge life-zone slugs per Lugo et al. 2006 (`schema/vocab/life_zones.csv`). |
| `facility_spheres` | `(facility_id, sphere_slug, role)` where `role` ∈ {primary, secondary}. A facility has at most one primary sphere. |
| `facility_ecosystems` | `(facility_id, ecosystem_slug)`. |
| `facility_life_zones` | `(facility_id, life_zone_slug)`. |

## People-side tables

Added in Wave F (R-PEOPLE-*); provenance columns added with the
R-PEOPLE2 wave.

| Table | Purpose |
|---|---|
| `people` | One row per person: `person_id` (the first 16 hex characters of the SHA-1 of the trimmed, lower-cased name followed by two pipe characters; see `stable_person_id` in `scripts/load_people_research.py`), `name`, `name_family`, `name_given`, `orcid`, `openalex_id`, `google_scholar_id`, `homepage_url`, `research_interests`, `bio`, `status`, plus the provenance columns below. `email` and `photo_url` exist but no view shows them; `email` is blanked on export. |
| `facility_personnel` | One row per `(person_id, facility_id, role)`: `title`, `is_key_personnel`, `start_date`, `end_date`, `is_current`, `source`, `source_url`, `retrieved_at`, `confidence`, `evidence`, `notes`. |
| `publications` | Publication catalogue keyed on `publication_id`: the OpenAlex work id for OpenAlex records, or a hash of the DOI (or, without one, the title) for the older recalled records; `doi` is unique. |
| `authorship` | `(person_id, publication_id, author_position, is_corresponding, raw_name)`. |
| `publication_topics` | OpenAlex concepts, topics and keywords per publication (`concept_id`, `concept_name`, `score`, `kind`). |
| `person_areas` | `(person_id, area_id, weight, evidence_count, source)`. |
| `collaborations` | Person-pair edges derived from co-authorship (`person_a_id`, `person_b_id`, `co_pub_count`, `first_year`, `last_year`, `strength`). |

As of 2026-10-24, 63,511 of the 64,231 publications were retrieved from
OpenAlex (August to October 2026). The other 720 are older records
labelled as training-data recall in `source`. `person_areas` and
`collaborations` are recomputed by the `compute_*` scripts. A person's
areas come from two sources that sit side by side: the areas of their
facilities (source `facility-area-inheritance`) and, for people with
enough OpenAlex-tagged publications, areas derived from those topics
(source `openalex_topics`). As of 2026-10-24, 521 people have inherited
areas, 556 have topic-derived areas, and 279 have both (798 people in
all). See [Methods](./methods.md) for how
identifiers are matched.

### People data: provenance and status

Every narrative or identity field that `scripts/load_people_research.py`
writes names the page it came from. The loader refuses a value without
one, so a field and its source arrive together or not at all.

| Field | Source column | Date column |
|---|---|---|
| `people.bio` | `bio_source_url` | `bio_retrieved_at` |
| `people.research_interests` | `research_interests_source_url` | — |
| `people.orcid` | `orcid_source_url`: the page that ties this iD to this person | — |
| `people.homepage_url` | — | `homepage_checked_at`: the last date it was fetched and resolved |
| a `facility_personnel` row | `source_url`, plus `evidence`, a short quote from that page | `retrieved_at` |

Values written before that rule, or by the enrichment scripts, may lack
a source column. As of 2026-10-24 all 780 bios carry `bio_source_url`.
650 of the 974 research-interest lines carry a source; when the OpenAlex
pass fills one, the source is the author's OpenAlex page (98 lines). 373
of the 611 stored ORCID iDs carry `orcid_source_url`.

- **Bios** paraphrase the cited page in 60 words or fewer. They contain no
  email address, phone number or photo, and no run of 8 or more words is
  copied from the source. The People tab shows the bio with a *source* link
  and its retrieval date.
- **`is_current`** says whether a role is held now. `true` means a page
  fetched on `retrieved_at` lists the person in the role. `false` means the
  row is superseded: a later batch listed someone else as the current
  holder of a leadership role at that facility, or a verification found
  the person no longer listed. The row is kept, never deleted, and its
  `notes` name the batch that superseded it. `NULL` means nobody has
  checked. Read `end_date` then: a past `end_date` means a former role,
  and `NULL` makes no claim either way. `v_facility_key_personnel` ignores
  `is_current`: it keeps key-personnel rows whose `end_date` is NULL or
  still ahead. The People tab labels a role *current* only when
  `is_current = true`, and *former* when it is `false` or the `end_date`
  has passed. Browse cards mark a role *former* when `is_current = false`
  and list those holders last. As of 2026-10-25, of 1,519 rows, 743 are
  `true`, 178 `false` and 598 `NULL`.
- **`confidence`** rates how directly the source supports the row, not how
  important the person is. The researching agent sets it, and the verifier
  lowers it when the page supports less than claimed. `agents/R-PEOPLE.md`
  defines the levels:
  - `high`: the page names this person in this role at this facility.
  - `medium`: the page supports the row, but by inference. Examples are an
    older page, a title that has to be mapped onto a role, or a program
    page rather than the site's own page.
  - `low`: the support is thin, for example a news item or a page that
    mentions the person without stating the role.

  Rows from before R-PEOPLE2 were mostly recalled rather than fetched. Their
  `confidence` is the agent's own rating and is not backed by `evidence`.
  As of 2026-10-25, 858 rows were fetched (851 on 2026-10-22, 7 on
  2026-10-25) and all of them carry `evidence`; 641 older rows and 20
  undated rows do not.
- **Roles** are slugs from `schema/vocab/personnel_roles.csv` (copied to
  `public/vocab/` for display labels). Its `is_leadership` column marks
  the roles that one batch can supersede at a facility: `director`,
  `deputy-director`, `associate-director`, `lead-PI`, `site-manager`,
  `manager`, `leadership-team` and the rest flagged `true`. Historical
  roles (`founding-PI`, `former-director`, `emeritus`, `alumnus`) are never
  superseded. The loader maps common spellings, such as "Principal
  Investigator", "Reserve Manager" and "research-collaborator", onto slugs
  (`ROLE_ALIASES`). Any other value stops the load, so a new role needs a
  vocabulary entry first.
- **Identity.** A person is matched on `existing_person_id`, then on exact
  ORCID, then on an exact normalised name among the people already at one
  of the same facilities (or, failing that, a unique match there under
  another spelling of the name). Names never merge people across
  facilities. If an ORCID conflicts with the one on file, the conflict is
  reported and the iD is not written.

## Project tables

Added with the ARID layer and loaded by `scripts/load_arid.py` (see
[ARID & New Mexico](./arid.md)). They use soft references.

| Table | Purpose |
|---|---|
| `projects` | One row per project: `name`, `acronym`, `parent_project_id`, `lead_facility_id`, `description`, `url`, optional `lat`/`lng`, plus `source_url`, `retrieved_at`, `confidence`. |
| `project_personnel` | `(project_id, person_id, role, title)` with `source_url`, `retrieved_at`, `confidence`. |
| `project_facilities` | `(project_id, facility_id, relation)` with `source_url`. |

## Data-access tables

Added in Wave J. They record where each facility's data can be reached
and how, as links and metadata only (see
[Data Access (OKF)](./okf/index.md)). `url_health` was added later with
the weekly URL sweep (`scripts/check_url_health.py`); it is not in
`schema.sql`, and the sweep replaces it wholesale.

| Table | Purpose |
|---|---|
| `data_archives` | One row per repository, portal or service: `archive_id`, `name`, `organization`, `archive_type`, `base_url`, `api_url`, `license_slug`. |
| `facility_archives` | `(facility_id, archive_id, role)`: which facility publishes data where. |
| `data_products` | One row per identifiable dataset or portal layer: `archive_id`, `facility_id`, `title`, `doi`, `url`, `format_slug`, `license_slug`, temporal and spatial extent. |
| `api_endpoints` | Documented API calls per archive (`path_or_url`, `method`, `purpose`, `example_call`). |
| `cloud_buckets` | Public cloud buckets (`provider`, `bucket_name`, `region`, `access_mode`). |
| `url_health` | Result of the weekly URL sweep (`url`, `status`, `http_code`, `checked_at`). |

## Region-side tables

Polygon overlays as records, and facility containment edges.
`scripts/populate_regions.py` fills them from `public/overlays/*.geojson`
by point-in-polygon. As of 2026-10-23 all three ship with **zero rows**;
the map draws its overlays straight from the GeoJSON files.

| Table | Purpose |
|---|---|
| `regions` | Polygon catalogue (marine sanctuaries and monuments, NERR reserves, NPS coastal units, NEP programs, NEON domains, EPA regions). |
| `region_area_links` | `(region_id, area_id)`. |
| `facility_regions` | `(facility_id, region_id, relation, distance_km)` containment edges. |

## Helper views

Defined in **both** `schema/schema.sql` and `src/db.js`, with the same
SQL. Re-create them in both places when adding a new view, and keep the
browser copy to DuckDB 1.5 syntax, because the browser engine is 1.5.6.
The lake gets them from `schema.sql` (on rebuild, or
`lto_db.ensure_schema`). In the browser they are created on the first
visit to the SQL tab.

- `v_facility_map`: facilities with coordinates, as map points.
- `v_facility_enriched`: one row per facility with its research areas,
  networks, funders, regions, spheres and ecosystem types as lists.
- `v_region_enriched`: regions with their research areas and contained
  facilities.
- `v_facility_funding_by_year`: facility-level annual funding totals.
- `v_funder_funding_by_year`: funder-level annual totals.
- `v_funding_ledger`: long-form ledger of `funding_events` with funder
  and facility names.
- `v_facility_key_personnel`: key personnel not past their `end_date`,
  one row per (facility, person, role).
- `v_person_enriched`: one row per person with their facilities, roles,
  research areas and publication count.
- `v_person_areas_enriched`: `person_areas` with person, area and
  facility names.
- `v_person_validation_latest`, `v_person_validation_summary`,
  `v_coauthor_edges_enriched`: the person-registry audit views.

`v_facility_funding_by_year_real` exists only in `schema.sql`: it joins
`cpi_index_us`, which is not exported.

The table list that drives the front-end is the `tables` array (loaded
at start-up) and the `lazyTables` array (loaded for the SQL tab) in
`initDB()` in `src/db.js`. It must agree with `TABLES` in
`scripts/export_parquet.py`.
