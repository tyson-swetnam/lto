-- cod-kmap DuckDB schema (D1 deliverable)
-- Idempotent: safe to re-read against an existing DB.
-- Load the spatial extension externally (INSTALL spatial; LOAD spatial;)
-- before calling ST_Point on the locations table.

-- All tables live in the default `main` schema. DuckDB does not allow
-- a custom schema with the same name as the database file, and the
-- browser-side Wasm client expects tables to be discoverable without a
-- schema prefix.

-------------------------------------------------------------------------------
-- Vocabularies (seeded from schema/vocab/*.csv by ingest.py)
-------------------------------------------------------------------------------

CREATE OR REPLACE TABLE facility_types (
    slug         VARCHAR PRIMARY KEY,
    label        VARCHAR NOT NULL,
    description  VARCHAR
);

CREATE OR REPLACE TABLE research_areas (
    area_id      VARCHAR PRIMARY KEY,   -- slug
    label        VARCHAR NOT NULL,
    gcmd_uri     VARCHAR,
    parent_id    VARCHAR                -- soft reference to research_areas.area_id; no FK to allow unordered bulk load
);

CREATE OR REPLACE TABLE networks (
    network_id   VARCHAR PRIMARY KEY,   -- slug
    label        VARCHAR NOT NULL,
    level        VARCHAR,               -- e.g. us-national / international
    url          VARCHAR
);

-------------------------------------------------------------------------------
-- Core entities
-------------------------------------------------------------------------------

CREATE OR REPLACE TABLE facilities (
    facility_id     VARCHAR PRIMARY KEY,             -- hash(name||acronym)
    canonical_name  VARCHAR NOT NULL,
    acronym         VARCHAR,
    parent_org      VARCHAR,
    facility_type   VARCHAR NOT NULL REFERENCES facility_types(slug),
    country         VARCHAR NOT NULL,                -- ISO 3166-1 alpha-2
    region          VARCHAR,
    hq_address      VARCHAR,
    hq_lat          DOUBLE,
    hq_lng          DOUBLE,
    url             VARCHAR,
    contact         VARCHAR,
    established     INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE TABLE locations (
    location_id     VARCHAR PRIMARY KEY,             -- hash(facility_id||label)
    facility_id     VARCHAR NOT NULL REFERENCES facilities(facility_id),
    label           VARCHAR,
    address         VARCHAR,
    lat             DOUBLE,
    lng             DOUBLE,
    role            VARCHAR                          -- headquarters|field-station|observatory|vessel|mooring-array|buoy|lab|office|virtual
);

CREATE OR REPLACE TABLE funders (
    funder_id       VARCHAR PRIMARY KEY,             -- hash(lower(name))
    name            VARCHAR NOT NULL,
    type            VARCHAR,                         -- federal|state|foundation|international|industry|private
    country         VARCHAR,
    url             VARCHAR,
    notes           VARCHAR
);

-- Time-series funding record. One row per (funder, facility, award,
-- fiscal_year) — so a multi-year grant produces one row per year with
-- its annual allocation, and the same facility can receive multiple
-- awards from the same funder in the same year. Nominal USD is stored
-- as-reported; CPI adjustment is done at query time against the
-- `cpi_index_us` helper table below.
--
-- `event_id` is a deterministic hash of the grain columns so re-ingests
-- are idempotent. This replaces the older `funding_links` table (which
-- had no primary key and no support for per-award-per-year granularity);
-- a backwards-compatible view with the old `funding_links` shape is
-- defined at the bottom of this file so existing queries keep working.
CREATE OR REPLACE TABLE funding_events (
    event_id        VARCHAR PRIMARY KEY,                -- hash(funder_id||facility_id||coalesce(award_id,'')||coalesce(fiscal_year,''))
    funder_id       VARCHAR NOT NULL REFERENCES funders(funder_id),
    facility_id     VARCHAR NOT NULL REFERENCES facilities(facility_id),
    -- Money (nominal, as reported by the source)
    amount_usd      DOUBLE,                             -- allocation for THIS fiscal_year (or one-time if period_* null)
    amount_currency VARCHAR DEFAULT 'USD',              -- ISO 4217; 'USD' by default, 'CAD', 'EUR' allowed
    -- Time
    fiscal_year     INTEGER,                            -- US FY (Oct 1 – Sep 30) unless funder is non-US
    period_start    DATE,                               -- optional: multi-year award window start
    period_end      DATE,                               -- optional: multi-year award window end
    -- Identity
    award_id        VARCHAR,                            -- funder's canonical award number (NSF 1234567, NOAA NA21NOS...)
    award_title     VARCHAR,                            -- short free-text award title
    program         VARCHAR,                            -- funder's internal program (NSF LTER, NOAA IOOS, EPA NEP, …)
    -- Classification
    relation        VARCHAR,                            -- parent-agency|appropriation|grant|contract|cooperative-agreement|endowment|state-appropriation|private-donor|membership-fee|in-kind
    -- Provenance
    source          VARCHAR,                            -- 'USAspending' | 'NSF Award Search' | 'NOAA Grants' | 'agency-report' | 'manual'
    source_url      VARCHAR,                            -- direct URL to the authoritative record
    retrieved_at    DATE,                               -- when we pulled this row from `source`
    confidence      VARCHAR,                            -- high|medium|low — how confident is the mapping funder → facility
    notes           VARCHAR,                            -- free-text qualifier (sub-award, pass-through, partial attribution…)
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Optional index helpers (DuckDB creates these only when beneficial;
-- INSERT throughput is fine without them for the expected <100k rows).
-- CREATE INDEX IF NOT EXISTS idx_funding_events_year  ON funding_events(fiscal_year);
-- CREATE INDEX IF NOT EXISTS idx_funding_events_fac   ON funding_events(facility_id);
-- CREATE INDEX IF NOT EXISTS idx_funding_events_funder ON funding_events(funder_id);

-- Annual CPI for deflating nominal awards into real dollars. Optional;
-- keep this table empty if you don't need CPI-adjusted queries.
-- Source: US Bureau of Labor Statistics CPI-U, yearly average. Load via
-- scripts/seed_cpi.py (not yet written — we'll add it alongside the
-- first real CPI query).
CREATE OR REPLACE TABLE cpi_index_us (
    year    INTEGER PRIMARY KEY,                         -- e.g. 2024
    cpi_u   DOUBLE NOT NULL,                             -- CPI-U annual average, 1982-84=100 base
    source  VARCHAR DEFAULT 'BLS CPI-U'
);

-- Backwards-compatible view matching the original funding_links shape
-- (columns in the exact same order). Existing app code queries against
-- funding_links; new analyses that need period/title/program/provenance
-- should hit funding_events directly.
CREATE OR REPLACE VIEW funding_links AS
SELECT funder_id, facility_id, amount_usd, fiscal_year, award_id,
       relation, source_url
FROM   funding_events;

CREATE OR REPLACE TABLE area_links (
    facility_id     VARCHAR NOT NULL REFERENCES facilities(facility_id),
    area_id         VARCHAR NOT NULL REFERENCES research_areas(area_id),
    PRIMARY KEY (facility_id, area_id)
);

CREATE OR REPLACE TABLE network_membership (
    facility_id     VARCHAR NOT NULL REFERENCES facilities(facility_id),
    network_id      VARCHAR NOT NULL REFERENCES networks(network_id),
    role            VARCHAR,
    PRIMARY KEY (facility_id, network_id)
);

-------------------------------------------------------------------------------
-- Regions (overlay polygons as first-class records)
-------------------------------------------------------------------------------
--
-- Every polygon shown under "Map overlays" (NMS sanctuaries, marine national
-- monuments, NERR reserves, NPS coastal units, NEP programs, NEON ecological
-- domains, EPA regions) becomes a row here, with the same rich metadata the
-- per-point facilities already carry (name / acronym / url / manager / etc.)
-- plus a foreign key to the `networks` vocabulary so region ↔ facility
-- joins are cheap.

CREATE OR REPLACE TABLE regions (
    region_id       VARCHAR PRIMARY KEY,             -- hash(network_id||lower(name))
    name            VARCHAR NOT NULL,
    acronym         VARCHAR,
    kind            VARCHAR,                          -- sanctuary | monument | nerr-reserve | nep-program | nps-unit | neon-domain | epa-region
    network_id      VARCHAR REFERENCES networks(network_id),
    url             VARCHAR,
    manager         VARCHAR,
    designated      INTEGER,
    state           VARCHAR,
    description     VARCHAR,
    source_file     VARCHAR,                          -- which public/overlays/*.geojson produced this row
    source          VARCHAR,                          -- upstream attribution (e.g. COMPASS-DOE/synthesis-networks)
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Region ↔ research_area (editable; empty by default — seed via
-- scripts/populate_regions.py based on kind heuristics, or by hand).
CREATE OR REPLACE TABLE region_area_links (
    region_id       VARCHAR NOT NULL REFERENCES regions(region_id),
    area_id         VARCHAR NOT NULL REFERENCES research_areas(area_id),
    PRIMARY KEY (region_id, area_id)
);

-- Facility ↔ region (derived: point-in-polygon against each overlay).
-- `relation` is 'within' when the facility's HQ coordinate lies inside
-- the polygon; future work may add 'nearby' or 'adjacent' links.
CREATE OR REPLACE TABLE facility_regions (
    facility_id     VARCHAR NOT NULL REFERENCES facilities(facility_id),
    region_id       VARCHAR NOT NULL REFERENCES regions(region_id),
    relation        VARCHAR,                          -- within | nearby | adjacent
    distance_km     DOUBLE,                           -- 0.0 when within
    PRIMARY KEY (facility_id, region_id)
);

-------------------------------------------------------------------------------
-- Provenance & ingest bookkeeping
-------------------------------------------------------------------------------

CREATE OR REPLACE TABLE provenance (
    record_type     VARCHAR NOT NULL,                -- 'facility' | 'funding_link' | ...
    record_id       VARCHAR NOT NULL,
    source_url      VARCHAR,
    retrieved_at    DATE,
    confidence      VARCHAR,                         -- high|medium|low
    agent           VARCHAR                          -- R1..R9, D2, etc.
);

CREATE OR REPLACE TABLE ingest_runs (
    run_id          VARCHAR PRIMARY KEY,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    git_sha         VARCHAR,
    facility_count  INTEGER,
    status          VARCHAR                          -- success|failed|partial
);

-------------------------------------------------------------------------------
-- Helper views for the web UI (F3 consumes these)
-------------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_facility_map AS
SELECT
    f.facility_id           AS id,
    f.canonical_name        AS name,
    f.acronym               AS acronym,
    f.facility_type         AS type,
    f.country               AS country,
    f.region                AS region,
    f.hq_lat                AS lat,
    f.hq_lng                AS lng,
    f.url                   AS url,
    f.parent_org            AS parent_org
FROM facilities f
WHERE f.hq_lat IS NOT NULL AND f.hq_lng IS NOT NULL;

CREATE OR REPLACE VIEW v_facility_enriched AS
SELECT
    f.facility_id,
    f.canonical_name,
    f.acronym,
    f.facility_type,
    f.country,
    f.hq_lat,
    f.hq_lng,
    f.url,
    list(DISTINCT ra.label)        AS research_areas,
    list(DISTINCT n.label)         AS networks,
    list(DISTINCT fu.name)         AS funders,
    list(DISTINCT r.name)          AS regions
FROM facilities f
LEFT JOIN area_links al        ON al.facility_id = f.facility_id
LEFT JOIN research_areas ra    ON ra.area_id    = al.area_id
LEFT JOIN network_membership nm ON nm.facility_id = f.facility_id
LEFT JOIN networks n           ON n.network_id   = nm.network_id
LEFT JOIN funding_links fl     ON fl.facility_id = f.facility_id
LEFT JOIN funders fu           ON fu.funder_id   = fl.funder_id
LEFT JOIN facility_regions fr  ON fr.facility_id = f.facility_id
LEFT JOIN regions r            ON r.region_id    = fr.region_id
GROUP BY f.facility_id, f.canonical_name, f.acronym, f.facility_type,
         f.country, f.hq_lat, f.hq_lng, f.url;

-- Region enriched — every polygon with its network + any facilities within.
CREATE OR REPLACE VIEW v_region_enriched AS
SELECT
    r.region_id,
    r.name,
    r.acronym,
    r.kind,
    r.network_id,
    n.label         AS network_label,
    r.url,
    r.manager,
    r.designated,
    r.state,
    r.description,
    list(DISTINCT ra.label)         AS research_areas,
    list(DISTINCT f.canonical_name) AS facilities,
    count(DISTINCT fr.facility_id)  AS facility_count
FROM regions r
LEFT JOIN networks n             ON n.network_id  = r.network_id
LEFT JOIN region_area_links ral  ON ral.region_id = r.region_id
LEFT JOIN research_areas ra      ON ra.area_id    = ral.area_id
LEFT JOIN facility_regions fr    ON fr.region_id  = r.region_id
LEFT JOIN facilities f           ON f.facility_id = fr.facility_id
GROUP BY r.region_id, r.name, r.acronym, r.kind, r.network_id, n.label,
         r.url, r.manager, r.designated, r.state, r.description;

-------------------------------------------------------------------------------
-- Funding time-series views
-------------------------------------------------------------------------------
--
-- These read from `funding_events` directly (which is what ingest writes to)
-- and expose the common aggregates the UI + SQL tab want to show without
-- rewriting the GROUP BY every time.

-- Facility × fiscal_year totals: one row per (facility, year) with
-- summed nominal USD and the list of funders that contributed that year.
CREATE OR REPLACE VIEW v_facility_funding_by_year AS
SELECT
    f.facility_id,
    f.canonical_name              AS facility,
    f.acronym,
    fe.fiscal_year,
    SUM(fe.amount_usd)            AS total_usd_nominal,
    COUNT(*)                      AS n_awards,
    list(DISTINCT fu.name)        AS funders
FROM facilities        f
JOIN funding_events    fe ON fe.facility_id = f.facility_id
JOIN funders           fu ON fu.funder_id   = fe.funder_id
WHERE fe.fiscal_year IS NOT NULL AND fe.amount_usd IS NOT NULL
GROUP BY f.facility_id, f.canonical_name, f.acronym, fe.fiscal_year;

-- Funder × fiscal_year totals: "how much did NSF allocate to this
-- dataset's facilities in 2019?" Useful for the funder's perspective.
CREATE OR REPLACE VIEW v_funder_funding_by_year AS
SELECT
    fu.funder_id,
    fu.name                       AS funder,
    fu.type                       AS funder_type,
    fe.fiscal_year,
    SUM(fe.amount_usd)            AS total_usd_nominal,
    COUNT(*)                      AS n_awards,
    COUNT(DISTINCT fe.facility_id) AS n_facilities
FROM funders         fu
JOIN funding_events  fe ON fe.funder_id = fu.funder_id
WHERE fe.fiscal_year IS NOT NULL AND fe.amount_usd IS NOT NULL
GROUP BY fu.funder_id, fu.name, fu.type, fe.fiscal_year;

-- Per-award ledger with facility and funder joined in. Flat enough
-- to export as CSV for an auditor.
CREATE OR REPLACE VIEW v_funding_ledger AS
SELECT
    fe.event_id,
    fe.fiscal_year,
    fe.period_start,
    fe.period_end,
    fu.name                AS funder,
    fu.type                AS funder_type,
    f.canonical_name       AS facility,
    f.acronym              AS facility_acronym,
    f.facility_type        AS facility_kind,
    f.country,
    fe.amount_usd          AS amount_usd_nominal,
    fe.amount_currency,
    fe.award_id,
    fe.award_title,
    fe.program,
    fe.relation,
    fe.source,
    fe.source_url,
    fe.retrieved_at,
    fe.confidence,
    fe.notes
FROM funding_events fe
JOIN funders    fu ON fu.funder_id   = fe.funder_id
JOIN facilities f  ON f.facility_id  = fe.facility_id;

-- CPI-adjusted version of the per-year facility totals. Joins to
-- cpi_index_us; returns NULL for real_usd_2024 when the CPI row for
-- that year hasn't been seeded yet. The constant 313.689 = 2024
-- annual CPI-U (BLS) — update the anchor year below when you refresh
-- cpi_index_us.
CREATE OR REPLACE VIEW v_facility_funding_by_year_real AS
SELECT
    v.*,
    CASE
      WHEN cpi_yr.cpi_u IS NOT NULL AND cpi_anchor.cpi_u IS NOT NULL
      THEN v.total_usd_nominal * (cpi_anchor.cpi_u / cpi_yr.cpi_u)
      ELSE NULL
    END AS total_usd_real_2024
FROM v_facility_funding_by_year v
LEFT JOIN cpi_index_us cpi_yr     ON cpi_yr.year     = v.fiscal_year
LEFT JOIN cpi_index_us cpi_anchor ON cpi_anchor.year = 2024;

-------------------------------------------------------------------------------
-- People (staff, administrators, scientists) at facilities
-------------------------------------------------------------------------------
--
-- Keeps everything in one DuckDB file so JOIN-heavy queries across
-- facilities ↔ people ↔ publications ↔ research_areas stay cheap. The
-- shape is adapted from UNM's knowledge-map schema (github.com/…/unm_kmap)
-- but adds a facility_personnel table because cod-kmap tracks _which_
-- role a person holds at _which_ facility (and when), which UNM's
-- single-institution model didn't need.

CREATE OR REPLACE TABLE people (
    person_id           VARCHAR PRIMARY KEY,       -- hash(lower(name)+orcid_or_email_or_idx)
    name                VARCHAR NOT NULL,          -- "First Middle Last", display form
    name_family         VARCHAR,                   -- last name (sort key)
    name_given          VARCHAR,                   -- first + middle
    email               VARCHAR,
    orcid               VARCHAR,                   -- 0000-0002-xxxx-xxxx
    openalex_id         VARCHAR,                   -- Axxxxxxxxxx
    scopus_author_id    VARCHAR,
    wos_researcher_id   VARCHAR,
    google_scholar_id   VARCHAR,
    homepage_url        VARCHAR,                   -- personal or institutional bio page
    photo_url           VARCHAR,
    research_interests  VARCHAR,                   -- free-text keywords, comma-separated
    bio                 VARCHAR,                   -- short narrative bio
    status              VARCHAR,                   -- active | emeritus | former | unknown
    notes               VARCHAR,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Role a person plays at a facility. A single person can hold multiple
-- roles across multiple facilities over time (professor AND LTER
-- director, or past-director AND current-emeritus). The grain is
-- (person, facility, role) so (Jane Doe, SBC LTER, Director) is
-- distinct from (Jane Doe, UCSB, Professor).
CREATE OR REPLACE TABLE facility_personnel (
    person_id           VARCHAR NOT NULL REFERENCES people(person_id),
    facility_id         VARCHAR NOT NULL REFERENCES facilities(facility_id),
    role                VARCHAR NOT NULL,          -- Director | Deputy Director | Associate Director |
                                                   -- Chief Scientist | Principal Investigator |
                                                   -- Program Manager | Head Administrator |
                                                   -- Professor | Research Scientist | Postdoc |
                                                   -- Graduate Student | Technician | Staff | Emeritus
    title               VARCHAR,                   -- free-text (e.g. "Professor of Marine Biology")
    is_key_personnel    BOOLEAN DEFAULT false,     -- flag for Director / Chief Scientist / Head Admin
    start_date          DATE,
    end_date            DATE,                      -- NULL = currently serving
    source              VARCHAR,                   -- 'facility-webpage' | 'manual' | 'orcid' | 'openalex'
    source_url          VARCHAR,
    retrieved_at        DATE,
    confidence          VARCHAR,                   -- high | medium | low
    notes               VARCHAR,
    PRIMARY KEY (person_id, facility_id, role)
);

CREATE OR REPLACE TABLE publications (
    publication_id      VARCHAR PRIMARY KEY,       -- hash(doi) or openalex_id or scopus_eid
    doi                 VARCHAR UNIQUE,
    title               VARCHAR,
    abstract            VARCHAR,
    pub_year            INTEGER,
    pub_type            VARCHAR,                   -- journal-article | conference-paper | book-chapter | preprint | report
    journal             VARCHAR,
    venue               VARCHAR,                   -- conference or book
    cited_by_count      INTEGER DEFAULT 0,
    openalex_id         VARCHAR,
    scopus_eid          VARCHAR,
    wos_uid             VARCHAR,
    url                 VARCHAR,
    source              VARCHAR,                   -- 'openalex' | 'scopus' | 'wos' | 'gscholar' | 'manual'
    retrieved_at        DATE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE TABLE authorship (
    person_id           VARCHAR NOT NULL REFERENCES people(person_id),
    publication_id      VARCHAR NOT NULL REFERENCES publications(publication_id),
    author_position     INTEGER,                   -- 1 = first author, NULL unknown
    is_corresponding    BOOLEAN DEFAULT false,
    raw_name            VARCHAR,                   -- as printed on the paper
    PRIMARY KEY (person_id, publication_id)
);

-- Person ↔ research_area (re-uses the existing research_areas vocab).
CREATE OR REPLACE TABLE person_areas (
    person_id           VARCHAR NOT NULL REFERENCES people(person_id),
    area_id             VARCHAR NOT NULL REFERENCES research_areas(area_id),
    weight              DOUBLE DEFAULT 1.0,        -- usually n-of-publications-on-topic / n-total
    evidence_count      INTEGER DEFAULT 0,         -- how many of this person's pubs contributed
    source              VARCHAR,                   -- 'openalex-topic' | 'gscholar-interest' | 'manual'
    PRIMARY KEY (person_id, area_id)
);

-- Per-publication OpenAlex topics / concepts / keywords. Captured at
-- enrichment time so we can later derive *fine-grained* person→area
-- weights without re-fetching every Work. OpenAlex returns three
-- parallel ontologies on each Work payload:
--
--   * concepts  — legacy 6-level (0..5) Wikidata-derived concepts (~65k)
--   * topics    — newer ~4500-leaf hierarchy (domain → field → subfield → topic)
--   * keywords  — free-text-ish keyword annotations
--
-- We store all three rather than picking one, because the marine /
-- coastal crosswalk (data/vocab_crosswalk/openalex_to_area.csv) is
-- easier to maintain when it can match against whichever ontology
-- best disambiguates a research_area slug. Topic IDs (T10102) and
-- concept IDs (C2778805511) live in the same column because they
-- share no prefix collision; `kind` flags which ontology the row
-- came from.
CREATE OR REPLACE TABLE publication_topics (
    publication_id      VARCHAR NOT NULL REFERENCES publications(publication_id),
    concept_id          VARCHAR NOT NULL,          -- 'C2778805511' | 'T10102' | 'keywords/citation'
    concept_name        VARCHAR NOT NULL,
    score               DOUBLE,                    -- 0..1 confidence reported by OpenAlex
    level               INTEGER,                   -- concept level (0..5); NULL for topics/keywords
    kind                VARCHAR DEFAULT 'concept', -- 'concept' | 'topic' | 'keyword'
    source              VARCHAR DEFAULT 'openalex',
    PRIMARY KEY (publication_id, concept_id)
);

-- Co-authorship graph between people in the dataset. Store with
-- person_a_id < person_b_id so each pair has one canonical row.
CREATE OR REPLACE TABLE collaborations (
    person_a_id         VARCHAR NOT NULL REFERENCES people(person_id),
    person_b_id         VARCHAR NOT NULL REFERENCES people(person_id),
    co_pub_count        INTEGER DEFAULT 0,
    first_year          INTEGER,
    last_year           INTEGER,
    strength            DOUBLE DEFAULT 0.0,        -- normalised 0..1
    PRIMARY KEY (person_a_id, person_b_id)
);

-------------------------------------------------------------------------------
-- People helper views
-------------------------------------------------------------------------------

-- Current, key personnel only — driven by the facility_personnel
-- is_key_personnel flag and a NULL end_date. Perfect for a "who runs
-- the site today?" directory.
CREATE OR REPLACE VIEW v_facility_key_personnel AS
SELECT
    f.facility_id,
    f.canonical_name        AS facility,
    f.acronym               AS facility_acronym,
    p.person_id,
    p.name,
    fp.role,
    fp.title,
    p.orcid,
    p.openalex_id,
    p.email,
    p.homepage_url,
    fp.start_date,
    fp.source_url
FROM facility_personnel fp
JOIN people     p ON p.person_id   = fp.person_id
JOIN facilities f ON f.facility_id = fp.facility_id
WHERE fp.is_key_personnel = true
  AND (fp.end_date IS NULL OR fp.end_date > CURRENT_DATE);

-- Person-rollup: every person with list-aggregated facilities, roles,
-- research areas, and publication count. Powers a "staff search" view
-- in the web app.
CREATE OR REPLACE VIEW v_person_enriched AS
SELECT
    p.person_id,
    p.name,
    p.name_family,
    p.orcid,
    p.openalex_id,
    p.email,
    p.homepage_url,
    p.research_interests,
    p.status,
    list(DISTINCT f.canonical_name)  AS facilities,
    list(DISTINCT fp.role)           AS roles,
    list(DISTINCT ra.label)          AS research_areas,
    COUNT(DISTINCT a.publication_id) AS n_publications,
    MAX(pub.pub_year)                AS latest_pub_year
FROM people p
LEFT JOIN facility_personnel fp ON fp.person_id   = p.person_id
LEFT JOIN facilities         f  ON f.facility_id  = fp.facility_id
LEFT JOIN person_areas       pa ON pa.person_id   = p.person_id
LEFT JOIN research_areas     ra ON ra.area_id     = pa.area_id
LEFT JOIN authorship         a  ON a.person_id    = p.person_id
LEFT JOIN publications       pub ON pub.publication_id = a.publication_id
GROUP BY p.person_id, p.name, p.name_family, p.orcid, p.openalex_id,
         p.email, p.homepage_url, p.research_interests, p.status;

-- person × research_area enriched with the actual evidence count and
-- the top topics (drawn from publication_topics) that pushed the
-- person into that area. Powers the SQL canned query "Person research
-- areas (by publication topics)".
CREATE OR REPLACE VIEW v_person_areas_enriched AS
SELECT
    p.person_id,
    p.name                       AS person,
    ra.area_id,
    ra.label                     AS area,
    pa.weight,
    pa.evidence_count,
    pa.source,
    f0.facilities                AS facilities
FROM person_areas pa
JOIN people         p  ON p.person_id  = pa.person_id
JOIN research_areas ra ON ra.area_id   = pa.area_id
LEFT JOIN (
    SELECT fp.person_id, list(DISTINCT f.canonical_name) AS facilities
    FROM facility_personnel fp
    JOIN facilities f ON f.facility_id = fp.facility_id
    GROUP BY fp.person_id
) f0 ON f0.person_id = p.person_id;
