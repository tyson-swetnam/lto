# Coverage

Snapshot of the database as of 2026-05-05. Numbers come from
`data/raw/R-XREF/coverage_report.md` after the Wave-E reconciliation pass.
Re-run `python scripts/qa.py` after re-ingest to refresh.

## Total facilities

Roughly **465 facilities** are retained after R-XREF deduplicates the 14
cross-agent duplicate clusters (Hubbard Brook, H.J. Andrews, Coweeta,
Konza Prairie, Bonanza Creek, Luquillo, Palmer, McMurdo, Kellogg, Santa
Barbara Coastal, SERC, Reynolds Creek, Mountain Lake, NOAA GLERL).

## By primary sphere

| Sphere | Count |
|---|---:|
| ocean-estuarine | 184 |
| terrestrial | 129 |
| freshwater | 65 |
| agriculture | 51 |
| cryosphere | 37 |
| atmosphere | 30 |

Note: dedupe drops a handful of records, so the post-merge totals are
slightly lower than the pre-merge sum (496) reported above.

## Landmark coverage

Each anchor list is checked at QA time so we can quantify gaps.

| Landmark list | Found / expected | Gaps |
|---|---|---|
| **NEON** | 81 / 81 | none |
| **LTAR** | 18 / 18 | none |
| **EcoTrends (Peters 2013 Table 1-1)** | 44 / 49 | Shortgrass Steppe; Coram EF; Andrews Forest; Tallgrass Prairie; Bandelier |
| **NERR** | 27 / 29 | Guana Tolomato Matanzas; Mission-Aransas |
| **IOOS RA** | 10 / 11 | GLOS |
| **USFS Experimental Forests & Ranges** | 40 / 77 | 37 EFRs short of the Lugo 2006 list — addressed by `R-PEOPLE-LOOP2-EFR` |

## People

After Wave-F (R-PEOPLE-* fan-out) and the LOOP2 backfill agents, the
people table holds approximately **360 people** with at least one
affiliation. Approximate role distribution:

| Role | Count |
|---|---:|
| lead-PI | ~140 |
| co-PI | ~70 |
| director | ~40 |
| information-manager | ~30 |
| founding-PI | ~25 |
| site-manager / domain-manager / superintendent / manager | ~30 |
| faculty / emeritus / technical-staff | ~25 |

(Roles totals sum to more than the headcount because some people hold
multiple affiliations across sites or sphere.)

## Identifier validation

- **`homepage_url`** — present for **100%** of people. Required fallback.
- **ORCID** — present for **~26%** of people at first-pass research time.
  ORCID enrichment in CI (see [loops](./loops.md)) is the path to a
  higher hit-rate.
- **OpenAlex Author ID** — present for **~20%** of people at first-pass.
  Backfilled by `scripts/enrich_people_openalex.py` in CI.
- **Google Scholar user ID** — sparsest field; backfilled by
  `scripts/enrich_people_gscholar.py` (rate-limited, optional).

The hard rule (per `agents/R-PEOPLE.md`): **never hallucinate
identifiers**. A wrong ORCID is worse than a missing one. Low-confidence
records are kept with the homepage URL as the only locator and the
enrichment scripts fill in the rest in CI.
