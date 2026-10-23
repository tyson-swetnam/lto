# Coverage

Snapshot as of **2026-10-23**. Every number on this page was counted from
the committed `public/parquet/` files, the same tables the site loads, after
the merges of PR #13 (fetched-source people), PR #16 (partial OpenAlex
pass) and PR #15 (URL-health sweep). The counts change whenever the data is
re-exported. To recount, query the tables on the [SQL tab](#/sql). For
example:

```sql
SELECT sphere_slug, count(*) FROM facility_spheres
WHERE role = 'primary' GROUP BY 1 ORDER BY 2 DESC;
```

## Total facilities

The catalogue holds **456 facilities**: US 441, Puerto Rico 10,
Antarctica 3, American Samoa 1 and US Virgin Islands 1. Every facility has
coordinates, and every US facility has a state.

- **315** meet the Peters et al. 2013 long-term threshold (≥10 years of
  record), 130 do not, and 11 are unclassified. 68 facilities have no
  record length at all, and 57 of those are counted as not meeting the
  threshold. The "≥10y" filter is off by default.
- Scope lenses: ARID Institute & partners **12**, New Mexico **19**,
  Southwest drylands (the default view) **67**, All U.S. **456**. See
  [ARID & New Mexico](./arid.md).

Deduplication is not complete. Several LTER sites still appear as two rows
with near-duplicate names, for example Plum Island / Plum Island Ecosystems,
Georgia Coast / Georgia Coastal Ecosystems and Florida Coast / Florida
Coastal Everglades.

## By primary sphere

| Sphere | Primary | Tagged in any role |
|---|---:|---:|
| ocean-estuarine | 153 | 160 |
| terrestrial | 112 | 287 |
| freshwater | 61 | 124 |
| agriculture | 59 | 66 |
| cryosphere | 31 | 55 |
| atmosphere | 23 | 99 |
| arid | 11 | 31 |
| **total** | **450** | |

That accounts for 450 facilities. The other **6** have no primary sphere.
All six are ARID partner institutes at UNM: METALS, the Public Policy
Program, the SW Environmental Finance Center, Sustainability Studies, the
Center for Health Equity and the Utton Center. By primary sphere,
ocean-estuarine is the largest. Terrestrial is the largest only when
secondary tags are counted.

## Landmark coverage

These are counts from the catalogue. `qa.py` does not check them.

| Landmark list | In the catalogue | Notes |
|---|---|---|
| **NEON** | 82 facilities in network `neon` | 77 of them are named "… NEON Site". The others are NEON members under other names. |
| **LTER** | 59 in network `lter` (11 of them also tagged `lter-site`) | Includes the near-duplicate rows above, so this is not a count of LTER sites. **26** LTER sites have a current lead PI that matches the LTER Network's site page (lternet.edu) or the site's own page. |
| **LTAR** | 26 in network `ltar` | 19 of them are of type `ltar-site`. |
| **NERRS** | 29 of 30 reserves | Network `nerrs` also includes NOAA's Office for Coastal Management. Connecticut is missing. Guana Tolomato Matanzas and Mission-Aransas, missing in May 2026, are now present. |
| **IOOS Regional Associations** | 10 of 11 | GLOS is missing. |
| **EcoTrends (Peters 2013 Table 1-1)** | Not re-run since 2026-05-05 (then 44 / 49 by name) | A facility named "H.J. Andrews Experimental Forest" is now present. No facility is named for Shortgrass Steppe, Coram EF, Tallgrass Prairie or Bandelier. A name match can miss a site that is catalogued under a different name. |
| **USFS Experimental Forests & Ranges** | 40 of type `experimental-forest-range`; 36 in network `usfs-rna-ef`; 49 in either | Still short of the 77 on the Lugo 2006 list that the May check used. No pass since then has added EFRs. |

## People

As of 2026-10-23 the people table holds **1,305 people**. Of these,
**1,217** have at least one facility affiliation. There are 1,537
affiliation rows across 441 facilities.

How the affiliation rows were made:

- **862 rows** were fetched on 2026-10-22 by the R-PEOPLE2 wave. Each was
  read from a cited page, carries a quote of the evidence, and was checked
  by an adversarial re-fetch. See [Methods](./methods.md).
- **654 rows** are older, dated 2026-04-24 to 2026-10-09, and 21 rows have
  no date. Many come from the earlier recall-based people waves. Some were
  repaired or ended by the 2026-10-22 pass, but most have **not been
  re-verified** against a fetched page.
- `is_current` is true on 747 rows and false on 177. It is not set on 613
  rows, which are mostly older rows that nobody has marked as current or
  former.

Rows by role (a person can hold several):

| Role | Rows |
|---|---:|
| director | 209 |
| lead-PI | 209 |
| co-PI | 195 |
| manager | 105 |
| scientist | 91 |
| leadership-team | 83 |
| founding-PI | 76 |
| faculty | 74 |
| domain-manager | 73 |
| emeritus | 58 |
| former-director | 44 |
| 16 other roles | 320 |

The 16 other roles include information-manager (31), superintendent (23)
and site-manager (12).

**Biographies:** 780 people have a bio, and every one cites its source page.

**Research interests:** 921 people have research interests. 552 of them
cite a source page.

**[Knowledge Map](./knowledge-map.md):** 1,234 people are placed under a
primary research area.

## Identifier validation

- **ORCID**: **612** people (46.9%). The ORCID log
  (`data/seed/orcid_resolution_log.csv`) records 78 stored iDs that were
  later cleared: 68 no longer resolved, and 10 belonged to someone else.
  PR #16 also cleared two wrong iDs and replaced a third.
- **OpenAlex Author ID**: **333** people (25.5%). The OpenAlex pass on
  2026-10-23 matched people only through a stored OpenAlex id or a
  confirmed ORCID. Name search is disabled. The pass processed 378 of the
  1,302 people in its queue before the daily OpenAlex credit ran out, so
  **924 have not yet been through it**. Every new attribution was checked
  against its OpenAlex author record, and disputed ones got a second,
  independent review. The review log
  (`data/seed/openalex_attribution_review_2026-10-23.csv`) has 106 entries:
  97 kept, 2 kept but disputed, and 7 removed.
- **`homepage_url`**: **771** people (59.1%). On 2026-10-23 the weekly URL
  sweep removed 66 homepages that pointed only at a bare domain (51) or a
  generic staff, about or contact page (15).
- **Google Scholar user ID**: 1 person. `scripts/enrich_people_gscholar.py`
  is optional and rate-limited.
- **Email**: none. Email addresses are never published.

Enrichment is not automatic. No scheduled workflow runs the
`enrich_people_*` scripts. They are run by hand in the order given in
`RUNBOOK.md`.

The hard rule (per `agents/R-PEOPLE.md`): **never record an identifier
that cannot be confirmed**. A wrong ORCID is worse than a missing one, so
an unmatched person keeps an empty field.

## Publications and data access

| Table | Rows |
|---|---:|
| publications (37,519 from OpenAlex, 720 recalled) | 38,239 |
| authorship (links to 489 people) | 41,710 |
| co-author pairs (`collaborations`) | 4,355 |
| data archives | 80 |
| data products | 634 |
| API endpoints | 158 |

Most publication and co-author links cover only the people OpenAlex has
reached so far (see above). 316 of the 489 linked people have an OpenAlex
id. The other 173 are linked only through 333 older authorship rows that
did not come from OpenAlex.

## Known gaps

- **29 facilities have no current leader on record.** A current leader is
  a leadership role that a fetched page lists as current, or an older row
  that nobody has marked as former.
  - 15 of the 29 have no personnel at all: 10 SCAN stations, 4 SNOTEL sites
    and the Glacier Peak / Lyman Lake snow pillow.
  - The other 14 list only non-leadership or former roles: Cullars
    Rotation, Dead Lake NEON Site, Magruder Plots, USDA-ARS Subarctic
    Agricultural Research Unit, Walnut Gulch #1 SCAN, Chesapeake Bay
    Sentinel Site, USGS WEBB Trout Lake, Calhoun EF, Mojave Global Change
    Facility (LTREB), NPS-IM Klamath Network, South Cascade Glacier, Kings
    River Experimental Watersheds, North Carolina Sentinel Site and Swan's
    Island LTREB.
- **924 people have not been through OpenAlex**, so their publication and
  co-author counts are missing or incomplete.
- **Older people rows have not been re-verified.** The 654 affiliation rows
  dated before 2026-10-22, plus the 21 undated ones, still rest on the
  earlier, mostly recall-based research.
- **720 publications are recalled, not fetched.** Their `source` labels
  them as training-data recall. They are older rows from before the
  OpenAlex pass and have not been checked against a bibliographic record.
- **Funding amounts are recalled, not fetched.** All 341 `funding_events`
  rows that carry a dollar amount are labelled as training-data recall in
  their `source`. Treat them as rough indications.
- **Regions are empty.** The `regions` and `facility_regions` tables have
  no rows.
