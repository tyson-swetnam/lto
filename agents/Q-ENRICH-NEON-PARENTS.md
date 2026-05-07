# Q-ENRICH-NEON-PARENTS-* — NEON parent-observatory enrichment

## Goal

For NEON sites that **lack a co-located long-term parent observatory** in
the LTO database (i.e. the NEON tower is currently the only entry at
that location), add the parent observatory as a separate
`facilities` row with deep history. NEON sites began field operations
in 2010-2018 — many of them were sited inside long-running
experimental forests, biological field stations, USDA-ARS ranges,
USFWS refuges, or national parks with multi-decade-to-century
observation records that should be first-class entries.

Examples of parent observatories:

| NEON site | Parent observatory | Established |
|-----------|--------------------|-------------|
| WREF (Wind River) | Wind River Experimental Forest (USFS) | 1932 |
| BLAN (Blandy) | Blandy Experimental Farm (UVA) | 1926 |
| MLBS (Mountain Lake) | Mountain Lake Biological Station (UVA) | 1930 |
| SJER (San Joaquin) | San Joaquin Experimental Range (USFS) | 1934 |
| GRSM | Great Smoky Mountains National Park | 1934 |
| YELL | Yellowstone National Park | 1872 |
| GUAN | Guánica State Forest (UNESCO MAB) | 1919 |

## Input

A list of orphan NEON sites with `(canonical_name, acronym, lat, lng)`
provided by the parent prompt. Look at the Wikipedia-grade common
knowledge for the location (don't fetch — sandbox blocks all network).

## Output (write to `data/raw/Q-ENRICH-NEON-PARENTS-<slice>/`)

1. **`additional_facilities.json`** — array of facility rows
   conforming to `agents/README.md` shape. Fields used by the loader
   (`scripts/load_lto_enrichment.py`):
   - `record_id`, `canonical_name`, `acronym` (NOT the NEON acronym;
     pick the parent's distinct acronym, e.g. `WREF-EF`, `MLBS-BS`).
   - `parent_org`, `facility_type` (from `schema/vocab/facility_types.csv`)
   - `country = "US"`, `region`
   - `hq.{address,lat,lng}` — physical HQ (NOT just the NEON tower).
   - `primary_sphere`, `secondary_spheres`, `ecosystem_types`,
     `life_zones`, `research_areas`, `networks`
   - `established` (year), `record_length_years`,
     `long_term_threshold_met = true` if record ≥ 10 years
   - `url`, `data_portal_url`
   - `funders` (list of `{name, relation}`)

2. **`additional_people.json`** — at least 2 key personnel per parent:
   - `people[]` — person rows (`name`, `name_family`, `name_given`,
     possibly `orcid`, `homepage_url`, `bio`). **Never invent ORCIDs**;
     omit the field if uncertain.
   - `affiliations[]` — `{person_name, facility_canonical_name,
     facility_acronym, role, title, is_key_personnel,
     start_date, source, source_url, confidence}`

3. **`additional_publications.json`** — 1-2 flagship long-record
   papers per facility:
   - `publications[]` — `{publication_id, doi, title, journal, year,
     volume, pages, source, source_url, confidence}`
   - `authorship[]` — `{publication_id, person_name, position,
     facility_canonical_name, facility_acronym}`
   - **Never invent DOIs**; omit DOI if uncertain.

4. **`additional_data_products.json`** — 1-2 long-term datasets per
   parent observatory (continuous met record, vegetation plots,
   stream gauge, etc.):
   - `[{product_id, facility_canonical_name, facility_acronym,
       title, description, type, format, license, url,
       temporal_coverage_start, temporal_coverage_end, source,
       confidence}]`

## Hard rules

- **Never hallucinate** DOIs, ORCIDs, award IDs. Omit the field when
  uncertain (`null` is fine; `confidence: "low"` flags it).
- **Don't duplicate** the NEON site itself. The NEON tower is already
  in the DB; you are adding the parent. Different `acronym`,
  different `record_id`.
- If you cannot confidently identify a parent observatory for a NEON
  site, skip it. Note it in `notes` or in a top-level `skipped` array.
- Keep `confidence` honest: `"high"` only when the fact is a
  well-known historical record (e.g. Yellowstone established 1872).
- Use the existing vocabulary slugs in `schema/vocab/*.csv`. If a slug
  doesn't exist, propose a new one in a `vocab_proposals.json`.

## Idempotency

The loader (`load_lto_enrichment.py`) skips rows whose acronym OR
canonical_name already matches an existing facility. Re-running this
agent's output is therefore a no-op — safe to iterate.
