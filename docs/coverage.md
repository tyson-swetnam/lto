# Coverage

Snapshot as of **2026-10-25**. Every number on this page was counted from
the committed `public/parquet/` files, the same tables the site loads, after
the merges of PR #13 (fetched-source people), PR #16 and PR #18 (the two
OpenAlex passes), PR #15 (URL-health sweep), PR #20 (LTER duplicates) and
the 2026-10-25 MarineGEO / LTREB fixes, the 2026-10-25 LTAR and funder
merges, the 2026-10-25 Reynolds Creek / Walnut Gulch merges, and the
2026-10-25 Fort Keogh / Northern Plains / Southern Plains merges, and the
2026-10-25 National Estuary Program host typing, the 2026-10-25 BLE and
MCR map-point fixes, the 2026-10-25 NERR / NEP award fetch from
USAspending.gov, and the 2026-10-25 map-point fixes for eight more LTER
sites. The counts
change whenever the data is
re-exported. To recount, query the tables on the [SQL tab](#/sql). For
example:

```sql
SELECT sphere_slug, count(*) FROM facility_spheres
WHERE role = 'primary' GROUP BY 1 ORDER BY 2 DESC;
```

## Total facilities

The catalogue holds **440 facilities**: US 424, Puerto Rico 10,
Antarctica 3, American Samoa 1, French Polynesia 1 and US Virgin Islands 1.
Every facility has coordinates, and every US facility has a state.

- **341** meet the Peters et al. 2013 long-term threshold (≥10 years of
  record), 88 do not, and 11 are unclassified. 24 facilities have no
  record length at all, and 13 of those are counted as not meeting the
  threshold. The "≥10y" filter is off by default.
- Scope lenses: ARID Institute & partners **12**, New Mexico **18**,
  Southwest drylands (the default view) **63**, All U.S. **440**. See
  [ARID & New Mexico](./arid.md).

Ten LTER sites used to sit on their lead institution's office instead of
the site. Beaufort Lagoon Ecosystems (BLE) was mapped at the UT Marine
Science Institute in Port Aransas, TX, and Moorea Coral Reef (MCR) at the
UCSB Marine Science Institute, on the same point as Santa Barbara Coastal.
On 2026-10-25 both moved to the point their lternet.edu site profile gives:
BLE to the Alaskan Beaufort Sea coast (state AK), and MCR to Moorea,
French Polynesia (country PF, no state, like the Antarctic LTER sites).
MCR still shows in the All U.S. lens, as McMurdo and Palmer do.

The same day eight more sites moved from their institution to their
lternet.edu profile point:

| Site | Was at | Now at | State |
|---|---|---|---|
| California Current Ecosystem (CCE) | Scripps, La Jolla | 32.8736, -120.28, offshore in the California Current | CA |
| Florida Coastal Everglades (FCE) | FIU, Miami | 25.4682, -80.8533, coastal Everglades | FL |
| Northeast U.S. Shelf (NES) | WHOI, Woods Hole | 40.6967, -70.8833, on the shelf transect south of Martha's Vineyard | MA |
| Northern Gulf of Alaska (NGA) | UAF, Fairbanks | 59.045, -148.7, on the Gulf of Alaska shelf off Seward | AK |
| Plum Island Ecosystems (PIE) | MBL, Woods Hole | 42.759, -70.891, Plum Island Sound | MA |
| Virginia Coast Reserve (VCR) | UVA, Charlottesville | 37.283, -75.913, the Coastal Research Center at Oyster | VA |
| Sevilleta (SEV) | UNM, Albuquerque | 34.353, -106.882, Sevilleta National Wildlife Refuge | NM |
| Konza Prairie (KNZ) | Kansas State University, Manhattan | 39.093, -96.575, Konza Prairie Biological Station | KS |

No state changed. The CCE, NES and NGA points are offshore, outside every
state polygon, so `backfill_facility_state.py` gives them the nearest state
(CA at 72.9 km, MA at 56.2 km, AK at 75.2 km). Sevilleta stays in the
ARID, New Mexico and Southwest drylands lenses, and the lens counts above
did not change. Each of the ten sites keeps its institution as an `office`
location, and every change is cited in `data/seed/facility_fixes.csv`.
Jornada Basin (JRN) was already mapped on its profile point, but its
address was the NMSU office in Las Cruces. It now gives a site description,
and the NMSU location has role `office` too. Three sites stay on a campus
because their lternet.edu profile point is the campus: Central
Arizona-Phoenix (ASU, Tempe), Minneapolis-St. Paul (University of
Minnesota, St. Paul) and Santa Barbara Coastal (UCSB). Each campus lies
inside its urban or coastal site. Every
LTER site row now sits within 20 km of its lternet.edu profile point except
"Bonanza Creek LTER Caribou-Poker Creeks Permafrost Sites". That row is
mapped at the Caribou-Poker Creeks watershed, 38 km from the Bonanza Creek
profile point in Fairbanks. McMurdo is the farthest of the rest, at 17 km.

Eight LTER sites used to appear twice: once as their LTER site row and once
as a COMPASS synthesis-networks import under a near-duplicate name (Plum
Island LTER, Georgia Coast LTER, Florida Coast LTER and others). On
2026-10-24 `scripts/merge_facilities.py` merged each import into its site
row on reviewed, cited pairs (`data/seed/facility_merge_seed.csv`). On
2026-10-25 two MarineGEO imports went the same way: "Indian River Lagoon
MarineGEO" into the Smithsonian Marine Station at Fort Pierce and "SERC,
GCREW MarineGEO" into the Smithsonian Environmental Research Center. Each
MarineGEO site page names that Smithsonian unit as its only participating
institution. Also on 2026-10-25, two "(USDA-ARS historic)" rows from a
knowledge-only enrichment pass were merged into their LTAR site rows:
Jornada Experimental Range into Jornada Experimental Range LTAR, and
Central Plains Experimental Range into Central Plains Experimental Range
LTAR. The LTAR site pages show that each LTAR site is the range itself.
Later the same day three more rows went into their LTAR sites: the
Reynolds Creek and Walnut Gulch "(USDA-ARS historic)" rows into Reynolds
Creek Experimental Watershed LTAR and Walnut Gulch Experimental Watershed
LTAR, and a "Great Basin LTAR" row placed at Reno, NV into Reynolds Creek.
LTAR lists one Great Basin site, and its site page names Reynolds Creek as
that site; the Reno row's own LTAR and ARS links returned 404. Three more
followed: "Fort Keogh Livestock and Range Research Laboratory (USDA-ARS
historic)" into Fort Keogh Livestock and Range Research Laboratory (one
ARS lab at one address), "Northern Great Plains Research Laboratory
(Mandan)" into Northern Plains LTAR, and "USDA-ARS Grazinglands Research
Laboratory (El Reno)" into Southern Plains LTAR. The LTAR Northern Plains
page describes only the Mandan laboratory, and the Southern Plains page
says the Grazinglands Research Laboratory manages that site. A recalled
AmeriFlux funding event that came with the El Reno row was removed: the
towers it names are ARM Southern Great Plains sites about 145 km north.
Fort Keogh is not part of an LTAR site. The
merge does not search for duplicates; other near-duplicates may remain.

Funders get the same treatment. On 2026-10-25 `scripts/merge_funders.py`
merged 24 duplicate `funders` rows on reviewed pairs
(`data/seed/funder_merge_seed.csv`). Most were an abbreviation next to the
full name: NSF, EPA / U.S. EPA, NPS, USGS, DOE, USACE, USDA-ARS, NOAA OCM,
NOAA IOOS, DOI-FWS, Smithsonian, Cary Institute. The rest were two
endowment spellings each for Archbold and Bigelow, and eight state
governments listed both as "X Government" and as "State of X" or
"Commonwealth of X". The table now holds **128 funders**. No dollar amount
changed: the merge re-keyed 373 `funding_events` rows and dropped two
award-less stubs that duplicated a stub the survivor already had.

The reserves' and estuary programs' funding was then fetched from
USAspending.gov (2026-10-25). 1,054 awards are pinned one by one in
`data/funding_overrides/usaspending_award_whitelist.csv`: NOAA CFDA 11.420
awards to 30 reserves (703 awards, filed under NOAA Office for Coastal
Management) and EPA CFDA 66.456 awards to 27 programs (351 awards), FY2008
to FY2026. An award counts only when it was attributed (certain or likely)
to one reserve or program and its recipient is that facility's lead agency
or host, or the program's own entity or foundation. The test is the
recipient, not the award's purpose, so a small graduate research
fellowship counts when it goes to a reserve's lead university (VIMS,
Rutgers, UT Austin and others; at most about $2.4M in all) and not when it
goes to another institution. Of the 291 awards left out, 113 are research,
fellowship or partner awards to other institutions and 37 more are
partner awards or the three-way Narragansett Bay split; 21 are
system-wide (the 19 NERRS data-office awards and 2 to Restore America's
Estuaries); 81 name no single reserve or program; 33 have a net
obligation of zero or less in the window; 4 are for proposed reserves; 2
are ambiguous or another program's money. All 1,345 awards considered,
with the reason for each, are in
`data/funding_overrides/usaspending_estuary_review.csv`. Puget Sound
Partnership is the outlier: $105.3M of the $989.0M, most of it two
pass-through awards (01J97401 and 02J98701, about $37M each, with 42 and
13 subawards), one of which was obligated in a single FY2026 action. They
are counted uncapped, so Puget Sound dominates FY2026 and the
coastal-processes area total. Each award gives
one row per fiscal year of its actions, with the net obligation, so a
closeout de-obligation shows as a negative row (120 rows). The 48 recalled
rows these awards replace were removed in `data/seed/facility_fixes.csv`:
the $700,000 NOAA "base funding" row on 29 reserves, the $700,000 EPA
"Section 320" row on 18 programs, and a $30M "appropriation" to the NOAA
Office for Coastal Management itself (the office that makes these
awards). Long Island Sound has no award rows: its 66.456 awards are
partner awards, and its program money is CFDA 66.437, not fetched here.
The table now holds 2,397 `funding_events` rows, 1,844 of them with an
amount, $4.31B in all (was 933, 380 and $3.38B).

## By primary sphere

| Sphere | Primary | Tagged in any role |
|---|---:|---:|
| ocean-estuarine | 142 | 149 |
| terrestrial | 112 | 281 |
| freshwater | 64 | 126 |
| agriculture | 51 | 58 |
| cryosphere | 31 | 55 |
| atmosphere | 23 | 99 |
| arid | 11 | 27 |
| **total** | **434** | |

That accounts for 434 facilities. The other **6** have no primary sphere.
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
| **LTER** | 50 in network `lter` (2 of them also tagged `lter-site`) | Also holds NEON, NADP, AmeriFlux and field-station rows at LTER sites, so this is not a count of LTER sites. **26** LTER sites have a current lead PI that matches the LTER Network's site page (lternet.edu) or the site's own page. |
| **LTAR** | 23 in network `ltar` | 18 of them are of type `ltar-site`, one row per LTAR site except Northern Headwaters (NH), which is not catalogued. |
| **NERRS** | 30 of 30 reserves | Network `nerrs` also includes NOAA's Office for Coastal Management. Connecticut, the 30th reserve (designated 2022), was added on 2026-10-25 from its NOAA page and the reserve's own site (`data/raw/R-ESTUARY/`). Guana Tolomato Matanzas and Mission-Aransas, missing in May 2026, are now present. Names, designation years, lead agencies and websites follow each reserve's NOAA page (2026-10-25). Facility type follows NOAA's lead agency: `state` for a state agency (20 reserves), `university-marine-lab` for a university marine lab or institute (6), `university-institute` for another university unit (Kachemak Bay, Lake Superior, Connecticut), and `federal` for Tijuana River, whose lead is California State Parks together with the U.S. Fish and Wildlife Service. |
| **National Estuary Programs** | 28 of 28 on EPA's list | Network `nep`. The Coastal and Heartland National Estuary Partnership (CHNEP) was added on 2026-10-25 from EPA's list and chnep.org (`data/raw/R-ESTUARY/`). Each program is typed by its host, which EPA's NEP guidance defines as the grant recipient and employer of the staff. The host comes from the program's own statement of its host or legal form, or else from the recipient of its current EPA §320 awards on USAspending. `parent_org` names the host's legal entity, never "EPA National Estuary Program" (the funding program); Long Island Sound, which EPA itself directs, has the EPA Long Island Sound Office as its host. A program that is itself a 501(c)(3) is `nonprofit` and its own parent. The 28 split 10 `nonprofit`, 6 `university-institute`, 5 `local-gov` (Charlotte County, the Indian River Lagoon Council, the Sarasota Bay and Tampa Bay special districts, and ABAG/MTC for San Francisco), 4 `state`, 2 `university-marine-lab` (LUMCON for Barataria-Terrebonne and Dauphin Island Sea Lab for Mobile Bay) and 1 `federal` (Long Island Sound, the one program EPA directs). Every typing is cited in `data/seed/facility_fixes.csv` (provenance agent `nep_host_rule`). Names and websites follow EPA's program list (2026-10-25). Only four establishment years are confirmed by a fetched page: Buzzards Bay (1985), Mobile Bay (1995), Lower Columbia (1995) and CHNEP (1995). The other programs' years, and the ≥10y flags that follow from them, are unverified values from the original cull. |
| **IOOS Regional Associations** | 10 of 11 | GLOS is missing. |
| **EcoTrends (Peters 2013 Table 1-1)** | Not re-run since 2026-05-05 (then 44 / 49 by name) | A facility named "H.J. Andrews Experimental Forest" is now present. No facility is named for Shortgrass Steppe, Coram EF, Tallgrass Prairie or Bandelier. A name match can miss a site that is catalogued under a different name. |
| **USFS Experimental Forests & Ranges** | 33 of type `experimental-forest-range`; 36 in network `usfs-rna-ef`; 42 in either | Still short of the 77 on the Lugo 2006 list that the May check used. No pass since then has added EFRs. |

## People

As of 2026-10-25 the people table holds **1,329 people**. Of these,
**1,236** have at least one facility affiliation. There are 1,529
affiliation rows across 425 facilities.

How the affiliation rows were made:

- **851 rows** were fetched on 2026-10-22 by the R-PEOPLE2 wave. Each was
  read from a cited page, carries a quote of the evidence, and was checked
  by an adversarial re-fetch. See [Methods](./methods.md). Seven more
  (batch R-PEOPLE2-MARINEGEO-01) and 20 for the Connecticut NERR and
  CHNEP (batch R-PEOPLE2-ESTUARY-01) were fetched on 2026-10-25.
- **14 rows** from the spring passes were re-cited on 2026-10-25 from
  fetched LTAR, Jornada, ARS (Southwest Watershed Research Center, Fort
  Keogh Livestock and Range Research Laboratory) and ORCID pages (`data/seed/facility_fixes.csv`), each with an `evidence` quote.
- **617 rows** are older, dated 2026-04-24 to 2026-10-09, and 20 rows have
  no date. Many come from the earlier recall-based people waves. Some were
  repaired or ended by the 2026-10-22 pass, but most have **not been
  re-verified** against a fetched page.
- `is_current` is true on 767 rows and false on 182. It is not set on 580
  rows, which are mostly older rows that nobody has marked as current or
  former.

Rows by role (a person can hold several):

| Role | Rows |
|---|---:|
| director | 205 |
| lead-PI | 196 |
| co-PI | 187 |
| manager | 107 |
| scientist | 101 |
| leadership-team | 83 |
| faculty | 74 |
| founding-PI | 74 |
| domain-manager | 73 |
| emeritus | 57 |
| coordinator | 45 |
| former-director | 44 |
| 15 other roles | 283 |

The 15 other roles include information-manager (27), superintendent (23)
and site-manager (12).

**Biographies:** 780 people have a bio, and every one cites its source page.

**Research interests:** 972 people have research interests. 649 of them
cite a source page, 98 of those an OpenAlex author page.

**[Knowledge Map](./knowledge-map.md):** 1,268 people are placed under a
primary research area.

## Identifier validation

- **ORCID**: **611** people (46.0%). The ORCID log
  (`data/seed/orcid_resolution_log.csv`) records 79 stored iDs that were
  later cleared: 68 no longer resolved, and 11 belonged to someone else.
  PR #16 also cleared two wrong iDs and replaced a third, and PR #18
  cleared one more (Pat Burke's iD belonged to a meteorologist).
- **OpenAlex Author ID**: **560** people (42.1%). The OpenAlex passes
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
- **`homepage_url`**: **804** people (60.5%). On 2026-10-23 the weekly URL
  sweep removed 66 homepages that pointed only at a bare domain (51) or a
  generic staff, about or contact page (15); on 2026-10-25, 32 of them that
  were personal or lab sites rather than bare roots were restored.
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
| data products | 628 |
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
- **769 people have no OpenAlex id**, so their publication and co-author
  counts are missing or incomplete: 703 have neither an ORCID nor an
  OpenAlex id, and 66 have an ORCID but no OpenAlex id (8 of them had one
  removed in review). In the second pass alone, 517 of 924 could not be
  matched: 478 with no identifier, 39 whose ORCID OpenAlex does not know.
- **Older people rows have not been re-verified.** The 617 affiliation rows
  dated before 2026-10-22, plus the 20 undated ones, still rest on the
  earlier, mostly recall-based research.
- **720 publications are recalled, not fetched.** Their `source` labels
  them as training-data recall. They are older rows from before the
  OpenAlex pass and have not been checked against a bibliographic record.
- **Most funding dollars are still recalled, not fetched.** Of the 1,844
  `funding_events` rows that carry a dollar amount, 289 are labelled as
  recall in their `source` and hold $3.31B of the $4.31B total; treat them
  as rough indications. The other 1,555 are fetched per-fiscal-year
  obligations: the four LTREB award series (North Inlet, GCReW, Swan's
  Island, West Falmouth Harbor; 43 rows from the NSF Award API, `source`
  'NSF Award Search') and the reserves' and estuary programs' own awards
  (1,512 rows, $989.0M, `source` 'USAspending.gov'; see the funders
  section above). All were fetched on 2026-10-25.
- **Regions are empty.** The `regions` and `facility_regions` tables have
  no rows.
