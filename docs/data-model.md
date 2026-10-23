# Data model

The logical schema is defined in `schema/schema.sql`. The pipeline stores
it in a DuckLake (DuckDB 2.0; catalog `db/lto_catalog.sqlite`, data
`db/lake/`) and exports every table to `public/parquet/`. The browser
registers each table as a Parquet-backed view on first load (see
`src/db.js`), then re-creates the helper views (`v_facility_funding_by_year`,
`v_funder_funding_by_year`, `v_facility_key_personnel`, `v_funding_ledger`,
`v_person_enriched`) — those don't survive Parquet export and **must be
defined in both** `schema/schema.sql` and `src/db.js` to stay in sync.

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
starts again at snapshot 1, and `scripts/lake_maintenance.py` expires
snapshots older than 90 days. The committed `public/parquet/` history in
git is the long-term record.

## Core facility tables

These are inherited from the cod-kmap engine and used unchanged.

| Table | Purpose |
|---|---|
| `facilities` | One row per observatory. `facility_id` (hash), `canonical_name`, `acronym`, `parent_org`, `facility_type`, `country`, `region`, `established`, `record_length_years`, `long_term_threshold_met`, `url`, `data_portal_url`, provenance fields. |
| `locations` | One row per HQ + satellite location. `facility_id`, `label`, `address`, `lat`, `lng`, `role` (headquarters / field-station / observatory / vessel / mooring-array / buoy / lab / weather-station / streamgage / flux-tower / glacier-site / snow-station). |
| `funders` | Funder catalogue (NSF, USDA, NOAA, DOE, USGS, NASA, EPA …). |
| `funding_events` | `(facility_id, funder_id, relation, year_start, year_end, amount_usd)`. Filled by `R-FUND`. |
| `networks` | Controlled vocabulary from `schema/vocab/networks.csv`. |
| `network_membership` | `(facility_id, network_slug)` join table. |
| `research_areas` | Slugs from `schema/vocab/research_areas.csv` (GCMD-aligned). |
| `area_links` | `(facility_id, area_slug)` join table. |

## LTO extension tables

Added in Wave A to support the six-sphere model.

| Table | Purpose |
|---|---|
| `spheres` | Catalogue of the six spheres + display labels. |
| `ecosystem_types` | EcoTrends + WWF biome slugs (`schema/vocab/ecosystem_types.csv`). |
| `life_zones` | Holdridge life-zone slugs per Lugo et al. 2006 (`schema/vocab/life_zones.csv`). |
| `facility_spheres` | `(facility_id, sphere, role)` where `role` ∈ {primary, secondary}. |
| `facility_ecosystems` | `(facility_id, ecosystem_slug)`. |
| `facility_life_zones` | `(facility_id, life_zone_slug)`. |

## People-side tables

Added in Wave F (R-PEOPLE-*); provenance columns added with the
R-PEOPLE2 wave.

| Table | Purpose |
|---|---|
| `people` | One row per person: `person_id` (`sha1(lower(name)‖'‖')[:16]`, see `stable_person_id` in `scripts/load_people_research.py`), `name`, `name_family`, `name_given`, `orcid`, `openalex_id`, `google_scholar_id`, `homepage_url`, `research_interests`, `bio`, `status`, plus the provenance columns below. `email` and `photo_url` exist but no view shows them; `email` is empty. |
| `facility_personnel` | One row per `(person_id, facility_id, role)`: `title`, `is_key_personnel`, `start_date`, `end_date`, `is_current`, `source`, `source_url`, `retrieved_at`, `confidence`, `evidence`, `notes`. |
| `project_personnel` | `(project_id, person_id, role, title)` with `source_url`, `retrieved_at`, `confidence` (ARID projects). |
| `publications` | DOI-keyed publication catalogue. |
| `authorship` | `(person_id, publication_id, author_position)`. |
| `person_areas` | `(person_id, area_slug)`. |
| `collaborations` | Person-pair edges derived from co-authorship. |

### People data: provenance and status

Every narrative or identity field about a person names the page it came
from. `scripts/load_people_research.py` refuses a value without one, so
a field and its source arrive together or not at all.

| Field | Source column | Date column |
|---|---|---|
| `people.bio` | `bio_source_url` | `bio_retrieved_at` |
| `people.research_interests` | `research_interests_source_url` | — |
| `people.orcid` | `orcid_source_url`: the page that ties this iD to this person | — |
| `people.homepage_url` | — | `homepage_checked_at`: the last date it was fetched and resolved |
| a `facility_personnel` row | `source_url`, plus `evidence`, a short quote from that page | `retrieved_at` |

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
  and `NULL` makes no claim either way. `v_facility_key_personnel` treats
  `end_date IS NULL` as serving. The People and Browse tabs label a role
  *current* only when `is_current = true`, and *former* when it is
  `false` or the `end_date` has passed.
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
  of the same facilities. Names never merge people across facilities. If
  an ORCID conflicts with the one on file, the conflict is reported and
  the iD is not written.

## Region-side tables

Polygon overlays and containment edges.

| Table | Purpose |
|---|---|
| `regions` | Polygon catalogue (LME, FMP regions, NPS units, USFS regions, Climate Hubs). |
| `region_area_links` | `(region_id, area_slug)`. |
| `facility_regions` | `(facility_id, region_id)` containment edges, computed by point-in-polygon at ingest time. |

## Helper views

Defined in **both** `schema/schema.sql` and `src/db.js`. Re-create them
in both places when adding a new view. The lake gets them from
`schema.sql` (on rebuild, or `lto_db.ensure_schema`).

- `v_facility_funding_by_year` — facility-level annual funding totals.
- `v_funder_funding_by_year` — funder-level annual totals.
- `v_facility_key_personnel` — flatten `facility_personnel` to one row
  per (facility, key person).
- `v_funding_ledger` — long-form ledger for the Funding tab.
- `v_person_enriched` — `people` + best-available identifier flag for
  the People tab.

The full table list driving the front-end is the `tables` array near
`src/db.js:142`.
