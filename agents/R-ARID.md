# R-ARID — ARID Institute (UNM): institute, partner centers, projects, people

## Scope

The University of New Mexico's ARID Institute (Accelerating Resilience
Innovations in Drylands, <https://arid.unm.edu>) and what its own site
lists: the UNM centers on its Resources Hub, its projects and their
sub-projects, its leadership team and staff, and each project's named
team. Spheres: `arid` primary for the institute; partner centers carry a
sphere only where one plainly fits.

Excluded: the Resources Hub's 20 external "Resources in the community"
links; news, events and newsletters; the homepage carousel item
"Quantifying Ecosystem exports across Space and Time" (no page, PI or
link); e-mail addresses (present on the source pages, deliberately not
copied).

Unlike the earlier waves, nothing here is recalled: every row is read
from a fetched page or from a hand-reviewed seed that cites one.

## Sources

1. <https://arid.unm.edu/leadership-team.html> — 26 leadership cards.
2. <https://arid.unm.edu/contact.html> — four staff.
3. <https://arid.unm.edu/projects/for-nm.html> — 15 FOR-NM leadership panels.
4. <https://arid.unm.edu/projects/changes/index.html> — CHANGES
   sub-projects with their leaders and co-leaders.
5. <https://arid.unm.edu/projects/changes/community-engagement-core/team.html>
   and `.../projects.html` — engagement-core team and its two field efforts.
6. The four single-page projects under <https://arid.unm.edu/projects/>
   (each carries one "PIs:" line).
7. <https://arid.unm.edu/contact1.html> — Resources Hub, "Resources at UNM".
8. Each partner center's own home page, for its address.
9. OpenStreetMap Nominatim, for coordinates of named buildings and counties.

## Inputs

- `schema/vocab/networks.csv` (`arid-unm`), `facility_types.csv`
  (`university-institute`).
- The existing `Sevilleta LTER` facility row (matched on acronym `SEV`,
  never duplicated).

## Outputs

- `data/raw/R-ARID/arid_site.json` — `scripts/fetch_arid_site.py`. What
  each page says, as written, typos included.
- `data/seed/arid_partner_centers.csv` — ARID plus 11 centers as facility rows.
- `data/seed/arid_projects.csv` — 12 projects; `team_sources` names the
  scraped section(s) that supply each team.
- `data/seed/arid_people.csv` — one row per real person, with the
  spellings the site uses for them (`aliases`) and any verified ORCID /
  OpenAlex id.
- Tables written by `scripts/load_arid.py`: `facilities`,
  `facility_spheres`, `network_membership`, `provenance`, `people`,
  `facility_personnel`, `projects`, `project_personnel`, `project_facilities`.

## Method

- Run `fetch_arid_site.py`, then `load_arid.py`, then
  `backfill_facility_state.py`, then the usual `qa.py` → `export_parquet.py`
  → `export_view_caches.py`.
- A name on the site that `arid_people.csv` does not know stops the load.
  Add it as a new row, or as an alias when it is a misspelling of someone
  already listed ("Kim Eichorst", "Eva Sticker", "Susan Boufous").
- Titles are stored as each page words them. Where pages disagree about
  a person (Debbie Lee's two titles; Jennifer Rudgers as "co-director" in
  one caption only) both survive, on the rows they came from, and the
  disagreement is noted on the person. Nothing is merged silently.
- A project gets coordinates only when its page names a place, with
  `location_precision` saying how exact the point is (`site`, `county`,
  `city`). Statewide and regional projects have no point.
- A center whose own page gives no street address is placed at the UNM
  campus point and its `hq_address` says "campus-level".
- ORCID / OpenAlex ids are added to `arid_people.csv` only after the
  strict resolver (`enrich_people_orcid.py`) or a human confirms them, and
  `orcid_basis` records which: name plus employer on the ORCID record, a
  sole name match whose employer was then checked by hand, or a sole name
  match whose works were compared with the person's UNM profile. A wrong
  id is worse than a missing one.

## Known landmarks

- The `ARID` facility exists, type `university-institute`, state `NM`.
- 26 `leadership-team` rows on it, matching `arid_site.json`.
- Marcy Litvak is one person: on the leadership team, `lead-PI` of
  FOR-NM, and a `PI` of the Sevilleta project.
- Stephanie Bestelmeyer (Asombro) is not merged with Brandon T.
  Bestelmeyer (Jornada).
- `arid-sevilleta-lter` links to the existing `Sevilleta LTER` facility.
- `arid-changes-gc-airwise` has a county-precision point in Grant County.
