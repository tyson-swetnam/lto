# Coverage

Snapshot as of **2026-10-25**. Every number on this page was counted from
the committed `public/parquet/` files, the same tables the site loads, after
the merges of PR #13 (fetched-source people), PR #16 and PR #18 (the two
OpenAlex passes), PR #15 (URL-health sweep), PR #20 (LTER duplicates) and
the 2026-10-25 MarineGEO / LTREB fixes. The counts change whenever the data is
re-exported. To recount, query the tables on the [SQL tab](#/sql). For
example:

```sql
SELECT sphere_slug, count(*) FROM facility_spheres
WHERE role = 'primary' GROUP BY 1 ORDER BY 2 DESC;
```

## Total facilities

The catalogue holds **446 facilities**: US 431, Puerto Rico 10,
Antarctica 3, American Samoa 1 and US Virgin Islands 1. Every facility has
coordinates, and every US facility has a state.

- **320** meet the Peters et al. 2013 long-term threshold (≥10 years of
  record), 115 do not, and 11 are unclassified. 53 facilities have no
  record length at all, and 42 of those are counted as not meeting the
  threshold. The "≥10y" filter is off by default.
- Scope lenses: ARID Institute & partners **12**, New Mexico **19**,
  Southwest drylands (the default view) **67**, All U.S. **446**. See
  [ARID & New Mexico](./arid.md).

Eight LTER sites used to appear twice: once as their LTER site row and once
as a COMPASS synthesis-networks import under a near-duplicate name (Plum
Island LTER, Georgia Coast LTER, Florida Coast LTER and others). On
2026-10-24 `scripts/merge_facilities.py` merged each import into its site
row on reviewed, cited pairs (`data/seed/facility_merge_seed.csv`). On
2026-10-25 two MarineGEO imports went the same way: "Indian River Lagoon
MarineGEO" into the Smithsonian Marine Station at Fort Pierce and "SERC,
GCREW MarineGEO" into the Smithsonian Environmental Research Center. Each
MarineGEO site page names that Smithsonian unit as its only participating
institution. The merge does not search for duplicates; other
near-duplicates may remain.

## By primary sphere

| Sphere | Primary | Tagged in any role |
|---|---:|---:|
| ocean-estuarine | 142 | 149 |
| terrestrial | 112 | 286 |
| freshwater | 62 | 125 |
| agriculture | 59 | 66 |
| cryosphere | 31 | 55 |
| atmosphere | 23 | 99 |
| arid | 11 | 31 |
| **total** | **440** | |

That accounts for 440 facilities. The other **6** have no primary sphere.
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
| **LTER** | 51 in network `lter` (2 of them also tagged `lter-site`) | Also holds NEON, NADP, AmeriFlux and field-station rows at LTER sites, so this is not a count of LTER sites. **26** LTER sites have a current lead PI that matches the LTER Network's site page (lternet.edu) or the site's own page. |
| **LTAR** | 26 in network `ltar` | 19 of them are of type `ltar-site`. |
| **NERRS** | 29 of 30 reserves | Network `nerrs` also includes NOAA's Office for Coastal Management. Connecticut is missing. Guana Tolomato Matanzas and Mission-Aransas, missing in May 2026, are now present. |
| **IOOS Regional Associations** | 10 of 11 | GLOS is missing. |
| **EcoTrends (Peters 2013 Table 1-1)** | Not re-run since 2026-05-05 (then 44 / 49 by name) | A facility named "H.J. Andrews Experimental Forest" is now present. No facility is named for Shortgrass Steppe, Coram EF, Tallgrass Prairie or Bandelier. A name match can miss a site that is catalogued under a different name. |
| **USFS Experimental Forests & Ranges** | 40 of type `experimental-forest-range`; 36 in network `usfs-rna-ef`; 49 in either | Still short of the 77 on the Lugo 2006 list that the May check used. No pass since then has added EFRs. |

## People

As of 2026-10-25 the people table holds **1,310 people**. Of these,
**1,221** have at least one facility affiliation. There are 1,519
affiliation rows across 431 facilities.

How the affiliation rows were made:

- **851 rows** were fetched on 2026-10-22 by the R-PEOPLE2 wave. Each was
  read from a cited page, carries a quote of the evidence, and was checked
  by an adversarial re-fetch. See [Methods](./methods.md). Seven more
  (batch R-PEOPLE2-MARINEGEO-01) were fetched on 2026-10-25.
- **641 rows** are older, dated 2026-04-24 to 2026-10-09, and 20 rows have
  no date. Many come from the earlier recall-based people waves. Some were
  repaired or ended by the 2026-10-22 pass, but most have **not been
  re-verified** against a fetched page.
- `is_current` is true on 743 rows and false on 178. It is not set on 598
  rows, which are mostly older rows that nobody has marked as current or
  former.

Rows by role (a person can hold several):

| Role | Rows |
|---|---:|
| director | 204 |
| lead-PI | 203 |
| co-PI | 191 |
| manager | 104 |
| scientist | 95 |
| leadership-team | 83 |
| founding-PI | 75 |
| faculty | 74 |
| domain-manager | 73 |
| emeritus | 58 |
| former-director | 44 |
| 16 other roles | 315 |

The 16 other roles include information-manager (27), superintendent (23)
and site-manager (12).

**Biographies:** 780 people have a bio, and every one cites its source page.

**Research interests:** 973 people have research interests. 649 of them
cite a source page, 98 of those an OpenAlex author page.

**[Knowledge Map](./knowledge-map.md):** 1,257 people are placed under a
primary research area.

## Identifier validation

- **ORCID**: **611** people (46.6%). The ORCID log
  (`data/seed/orcid_resolution_log.csv`) records 79 stored iDs that were
  later cleared: 68 no longer resolved, and 11 belonged to someone else.
  PR #16 also cleared two wrong iDs and replaced a third, and PR #18
  cleared one more (Pat Burke's iD belonged to a meteorologist).
- **OpenAlex Author ID**: **560** people (42.7%). The OpenAlex passes
  matched people only through a stored OpenAlex id or a confirmed ORCID.
  Name search is disabled. Two passes (PR #16: 378 people; PR #18: the
  remaining 924) have now taken all 1,302 people in the queue through
  OpenAlex. The second pass resolved 407 of its 924; the other 517 cannot
  be matched this way: 478 have neither an ORCID nor an OpenAlex id, and
  39 have an ORCID that OpenAlex does not know. Every new attribution was
  checked against its OpenAlex author record, and disputed ones got a
  second, independent review. The two review logs
  (`data/seed/openalex_attribution_review_2026-10-23.csv` and
  `…_2026-10-24.csv`) have 338 entries between them: 322 kept, 5 kept but
  disputed, and 11 removed.
- **`homepage_url`**: **772** people (58.9%). On 2026-10-23 the weekly URL
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
| publications (63,511 from OpenAlex, 720 recalled) | 64,231 |
| authorship (links to 689 people) | 73,423 |
| co-author pairs (`collaborations`) | 6,686 |
| data archives | 80 |
| data products | 634 |
| API endpoints | 158 |

Most publication and co-author links cover only the people OpenAlex could
match (see above). 560 of the 689 linked people have an OpenAlex id. The
other 129 are linked only through 241 older authorship rows that did not
come from OpenAlex.

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
- **750 people have no OpenAlex id**, so their publication and co-author
  counts are missing or incomplete: 684 have neither an ORCID nor an
  OpenAlex id, and 66 have an ORCID but no OpenAlex id (8 of them had one
  removed in review). In the second pass alone, 517 of 924 could not be
  matched: 478 with no identifier, 39 whose ORCID OpenAlex does not know.
- **Older people rows have not been re-verified.** The 641 affiliation rows
  dated before 2026-10-22, plus the 20 undated ones, still rest on the
  earlier, mostly recall-based research.
- **720 publications are recalled, not fetched.** Their `source` labels
  them as training-data recall. They are older rows from before the
  OpenAlex pass and have not been checked against a bibliographic record.
- **Most funding amounts are recalled, not fetched.** Of the 383
  `funding_events` rows that carry a dollar amount, 340 are labelled as
  training-data recall in their `source`; treat them as rough indications.
  The other 43 are the per-fiscal-year obligations of the four LTREB award
  series (North Inlet, GCReW, Swan's Island, West Falmouth Harbor), fetched
  from the NSF Award API on 2026-10-25 (`source` 'NSF Award Search').
- **Regions are empty.** The `regions` and `facility_regions` tables have
  no rows.
