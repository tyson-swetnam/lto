# R-PEOPLE2 — Key personnel of the LTO network, from fetched sources

## Scope

R-PEOPLE2 agents find the people who run each facility. That means
directors, lead PIs, site and reserve managers, NEON domain managers,
information managers and named senior scientists. They also verify the
leadership rows already in the lake and write short bios for people who
are already there.

Every value must come from a page the agent fetched in this run. Do not
fill a field from memory. A missing person or field is better than a
wrong one: the old R-PEOPLE wave was written from training-data recall,
and the result was stale lead PIs, mixed-up reserves and ORCIDs that
belonged to someone else.

There are two kinds of batch:

| Kind | Directory | One file per | Loaded as |
|---|---|---|---|
| Research | `data/raw/R-PEOPLE2/<batch_id>.json` | batch of up to 12 facilities | new people, affiliations, verdicts on existing rows |
| Bio update | `data/raw/R-PEOPLE2-BIO/<batch_id>.json` | batch of about 12 existing people | bio, interests, ORCID, status for people already in the lake |

Batch ids follow `R-PEOPLE2-<FAMILY>-NN[a|b]`, for example
`R-PEOPLE2-NERR-01a`, and `R-PEOPLE2-BIO-NN`. Families are ARID-NM,
DRYLANDS-SW, LTER, LTAR-ARS, USFS-EFR, NERR, NEP, HYDRO-CRYO, LTREB,
ATMOSPHERE, FLUX, NEON, OCEAN-COASTAL, PROTECTED-AREAS,
OTHER-INSTITUTIONS and FIELD-STATIONS. Both directories are committed;
they are an exception to the `data/raw/**` gitignore.

## Method

1. **Research.** For each facility in the batch, fetch the facility's own
   pages: leadership or contact pages, the network's site page (for
   example lternet.edu "Site Contacts", the NEON domain page or the NERR
   reserve page), and people's profile pages. Record every page fetched,
   with its HTTP status, in `pages_fetched`. Use only pages that returned
   200; a page drawn by JavaScript may be read in a headless browser.
2. **Verify existing rows.** For each leadership row the lake already holds
   at the facility, the batch's input lists `person_id` and role. Give each
   one a verdict: `confirmed`, `stale`, `not-found` or `unverifiable`.
3. **Adversarial verify.** A second agent, the verifier, takes the draft and
   tries to break it before anything is loaded. It:
   - re-fetches every cited URL and drops any field whose page no longer
     returns 200;
   - checks each `evidence` quote appears on its `source_url`, and that the
     page names that person in that role at that facility;
   - fetches `pub.orcid.org/v3.0/<iD>/person` and `/employments` for every
     ORCID, and keeps an iD only if the name matches and it is shown on a
     fetched profile or matched by an employment at the right institution;
   - checks the bio policy below by script (word count, longest copied
     run);
   - checks every role is in the vocabulary, every `facility_id` is in the
     batch, and every `current_holder_key` points to a person in the file.

   It corrects or drops what fails, lowers `confidence` where the page
   supports less than claimed, sets `verified_by` (for example
   `"adversarial-verifier 2026-10-22"`) and writes the file. Only verified
   files go in `data/raw/`. It records what it dropped in `dropped` (bio
   batches) or `verification_notes`.
4. **Load** with `scripts/load_people_research.py` (see [Loader](#loader)).

## Research batch format (`data/raw/R-PEOPLE2/*.json`)

```json
{
  "batch_id": "R-PEOPLE2-ARID-NM-01a",
  "retrieved_at": "2026-10-22",
  "verified_by": "adversarial-verifier 2026-10-22",
  "facilities": [
    { "facility_id": "be89811018d4119f",
      "pages_fetched": [ { "url": "https://lternet.edu/site/sevilleta-lter/", "status": 200 } ],
      "notes": "what was found, moved or unreachable" }
  ],
  "people": [
    { "key": "rudgers-jennifer",
      "existing_person_id": null,
      "name": "Jennifer A. Rudgers", "name_given": "Jennifer", "name_family": "Rudgers",
      "orcid": "0000-0001-7094-4857",
      "orcid_source_url": "https://lternet.edu/directory/?user=5225",
      "homepage_url": "https://biology.unm.edu/people/faculty/profile/…",
      "bio": "≤60-word paraphrase …",
      "bio_source_url": "https://biology.unm.edu/people/faculty/profile/…",
      "research_interests": "Climate change; plant-microbe symbiosis",
      "research_interests_source_url": "https://biology.unm.edu/people/faculty/profile/…" }
  ],
  "affiliations": [
    { "facility_id": "be89811018d4119f",
      "person_key": "rudgers-jennifer",
      "role": "lead-PI",
      "title": "Lead Principal Investigator, Sevilleta LTER",
      "is_key_personnel": true,
      "is_current": true,
      "start_year": null, "end_year": null,
      "source_url": "https://lternet.edu/site/sevilleta-lter/",
      "evidence": "Site Contacts Lead Principal Investigator: Jennifer Rudgers",
      "confidence": "high" }
  ],
  "verifications": [
    { "facility_id": "be89811018d4119f",
      "person_id": "1eb3771506b20c11",
      "existing_role": "lead-PI",
      "status": "stale",
      "current_holder_key": "rudgers-jennifer",
      "source_url": "https://lternet.edu/site/sevilleta-lter/",
      "evidence": "Lead Principal Investigator: Jennifer Rudgers" }
  ]
}
```

- **`retrieved_at`** is the real date the pages were fetched, once per file.
  The loader copies it into every row; it never uses the clock.
- **`facility_id`** is copied from the batch's input list and is
  authoritative. There is no name or acronym matching, and an unknown id
  stops the load.
- **`key`** is a slug that joins `affiliations[].person_key` and
  `verifications[].current_holder_key` to `people[]`. Set
  `existing_person_id` when the person is already in the lake (the input
  lists who is at each facility); otherwise leave it null.
- **Every affiliation needs `source_url` and `evidence`**, a quote of 25
  words or fewer copied from that page. A row without them is refused.
- **`is_current`** is `true` when the page lists the person in the role
  now, and `false` when it shows a past role. Use `null` only when the page
  does not say.
- **`start_year` / `end_year`** only when the page gives them.
- **`confidence`**: how directly the page supports the row.
  - `high`: the page names this person in this role at this facility.
  - `medium`: the page supports the row by inference, for example an older
    page, a title that has to be mapped onto a role, or a program page
    rather than the site's own page.
  - `low`: thin support, for example a news item, or a page that mentions
    the person without stating the role.
- **Verification `status`**:
  - `confirmed`: the page still shows the person in the role.
  - `stale`: someone else holds the role now. Name them in
    `current_holder_key`.
  - `not-found`: the person is not on the pages that list the role.
  - `unverifiable`: no page could be fetched.

## Bio update format (`data/raw/R-PEOPLE2-BIO/*.json`)

```json
{
  "batch_id": "R-PEOPLE2-BIO-01",
  "retrieved_at": "2026-10-22",
  "verified_by": "adversarial-verifier 2026-10-22",
  "updates": [
    { "person_id": "1189b0add865bb00",
      "name": "Aaron R. Weiskittel",
      "homepage_url": "https://crsf.umaine.edu/people/aaron-weiskittel/",
      "bio": "≤60-word paraphrase …",
      "bio_source_url": "https://umaine.edu/space/people/aaron-weiskittel/",
      "research_interests": null, "research_interests_source_url": null,
      "orcid": null, "orcid_source_url": null,
      "current_title": "Director, Center for Research on Sustainable Forests",
      "current_affiliation": "University of Maine",
      "status": "active", "status_source_url": "https://crsf.umaine.edu/people/aaron-weiskittel/",
      "evidence": "Aaron Weiskittel CRSF Director",
      "evidence_source_url": "https://crsf.umaine.edu/people/aaron-weiskittel/",
      "notes": "what was checked; why a field was left null" }
  ],
  "dropped": [ { "person_id": "…", "name": "…", "reason": "no page could be fetched" } ]
}
```

- **`person_id` must exist** in the lake, and the family name in `name`
  must agree with the lake's. Otherwise the file stops.
- **`status`** is `active`, `emeritus`, `former` or `unknown`. It is
  written only with a `status_source_url`; `unknown` is never written.
- `current_title` and `current_affiliation` go into `people.notes`, not into
  `facility_personnel`. An affiliation needs a research batch.

## Bio and personal-data policy

- **A bio is at most 60 words.** It is a paraphrase of `bio_source_url`
  with no run of 8 or more words copied from that page. It covers role,
  institution and research focus, and it must say nothing the page does
  not.
- **Every bio, research-interests line, ORCID and status names its
  source.** A value without its `*_source_url` is not written.
- **Never record an email address, phone number, home address or photo,**
  even when the page shows one. The verifier rejects a file that contains
  any of them. (`people.email` and `photo_url` exist in the schema for
  older loaders; nothing in this wave fills them.)
- **Identifiers:** ORCID must match `^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$` and be
  confirmed at pub.orcid.org as described above. If an ORCID conflicts
  with the one on file, the loader reports it and keeps the lake's. A
  wrong ORCID is worse than a missing one. OpenAlex and Google Scholar
  ids are left to the enrichment scripts.

## Roles

`role` is a slug from `schema/vocab/personnel_roles.csv`: `director`,
`deputy-director`, `associate-director`, `lead-PI`, `co-PI`,
`founding-PI`, `site-manager`, `manager`, `executive-officer`,
`superintendent`, `research-coordinator`, `stewardship-coordinator`,
`education-coordinator`, `information-manager`, `data-manager`,
`domain-manager`, `scientist`, `faculty`, `coordinator`, `technical-staff`,
`emeritus`, `former-director`, `leadership-team`, `advisory-board`,
`collaborator`, `staff`, `land-manager` or `alumnus`. The free-text job
title goes in `title`.

- `is_leadership = true` in the vocabulary marks the roles where a batch
  that lists the current holders supersedes anyone else holding that role
  at the facility.
- An unknown role stops the load and lists every unknown value, so a
  genuinely new role needs a vocabulary row first (in `schema/vocab/` and
  `public/vocab/`).
- NEON site pages name a site host, not a PI. Record the `domain-manager`
  from the NEON domain page instead of forcing a lead PI.

## Loader

```bash
python scripts/load_people_research.py --dry-run   # per-file diff, rolled back
python scripts/load_people_research.py             # R-PEOPLE2/*.json, then R-PEOPLE2-BIO/*.json
python scripts/load_people_research.py data/raw/R-PEOPLE2/R-PEOPLE2-NERR-01a.json
python scripts/qa.py && python scripts/export_parquet.py && python scripts/export_view_caches.py
```

- **One lake transaction (one snapshot) per file**, with the commit message
  `load_people_research: <batch_id>`. A failing file rolls back on its
  own. Re-running changes nothing.
- **People are matched** on `existing_person_id`, then on exact ORCID, then
  on an exact normalised name among the people already at one of the same
  facilities. Otherwise a new `person_id` is minted from the name. Names
  never merge people across facilities.
- **People fields:**
  - A research batch fills empty or unsourced fields. It replaces a sourced
    field only with a value retrieved on a later date.
  - A bio batch replaces sourced fields outright.
  - Neither ever writes a NULL over a value.
- **Affiliations** are keyed `(person_id, facility_id, role)`. When a batch
  lists the current holders of a leadership role, any other current holder
  of that role at the facility gets `is_current = false`. The row is kept,
  and its `notes` name the batch. `end_date` is not touched.
- **Verifications:**
  - `stale` sets `is_current = false` on that row.
  - `confirmed` refreshes `source_url`, `retrieved_at`, `confidence` and
    `evidence`.
  - `not-found` and `unverifiable` are reported and change nothing.

`docs/data-model.md` ("People data: provenance and status") documents how
these columns are read, and the People tab shows them. Each bio has a
*source* link, and each affiliation shows *current* or *former* with its
source page and retrieval date.

## Post-pass enrichment

After loading, `RUNBOOK.md` covers the identity passes:
`enrich_people_orcid.py --only-missing`, `enrich_people_openalex.py`
(needs `OPENALEX_API_KEY`) and optionally `enrich_people_gscholar.py`.
Then rerun the derived tables in order: `compute_collaborations` →
`compute_person_areas` → `compute_primary_groups` → `compute_area_metrics`
→ `build_mvg_layout`. Finish with `qa.py` → `export_parquet.py` →
`export_view_caches.py`.

## Historical note

The first wave (`R-PEOPLE-<sphere>`, `data/raw/R-PEOPLE-*/people.json`,
loaded by `load_facility_personnel.py`) was written without fetching,
from model recall, with a fixed `retrieved_at` of 2026-05-05 and
name/acronym facility matching. Its rows are still in the lake. R-PEOPLE2
verdicts mark the ones found stale, and later research batches supersede
them. Do not use that format for new work.
