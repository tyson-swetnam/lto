# R-PEOPLE-* — Key personnel of the LTO network

## Scope

Every `R-PEOPLE-<sphere>` agent identifies the **key personnel** for the
facilities in its sphere — directors, lead PIs, co-PIs, information managers,
and faculty/scientists with publication histories at the site. Each person
must carry at least one **validated** identifier from this priority list:

1. ORCID (16-digit `0000-XXXX-XXXX-XXXX`)
2. OpenAlex Author ID (`A` + digits — e.g. `A5078473812`)
3. Google Scholar user ID (the `user=` query value — e.g. `WSV5ms8AAAAJ`)
4. As a fallback, an institutional homepage URL is acceptable; mark
   `provenance.confidence = "low"` for those records and let the
   enrichment scripts (`scripts/enrich_people_orcid.py`,
   `scripts/enrich_people_openalex.py`,
   `scripts/enrich_people_gscholar.py`) backfill IDs against the public
   APIs in a follow-up pass.

## Sub-agent fan-out

| Agent | Sphere(s) covered |
|---|---|
| `R-PEOPLE-LTER` | 28 NSF LTER sites — lead PIs, IMs, key co-PIs |
| `R-PEOPLE-NEON` | NEON Battelle leadership + 81 site PIs |
| `R-PEOPLE-EFR` | USFS Experimental Forest / Range project leaders |
| `R-PEOPLE-AGR` | USDA-ARS LTAR + rangeland directors |
| `R-PEOPLE-OCEAN` | IOOS RA directors, NERR managers, NMS superintendents, WHOI/Scripps/Lamont/PMEL leadership |
| `R-PEOPLE-FRESH` | USGS WMA / WEBB PIs, NTL-LTER, NOAA GLERL, EPA GLNPO, GLEON US |
| `R-PEOPLE-ATM` | NOAA-GML, NADP, AmeriFlux, ARM, CASTNET, IMPROVE, SURFRAD, TCCON US PIs |
| `R-PEOPLE-CRY` | USGS Benchmark Glaciers, Toolik, McMurdo, Palmer, CRREL leadership |
| `R-PEOPLE-OTHER` | OBFS, UC-NRS, MAB, NPS-IM, Cary, RMBL, SERC, UMBS |

## Output format

Each agent writes one JSON file:
`data/raw/R-PEOPLE-<sphere>/people.json` with this structure:

```json
{
  "people": [
    {
      "name": "Full Name",
      "name_family": "Family",
      "name_given": "Given Middle",
      "email": "optional",
      "orcid": "0000-XXXX-XXXX-XXXX",
      "openalex_id": "A1234567890",
      "google_scholar_id": "WSV5ms8AAAAJ",
      "homepage_url": "https://institution.edu/person/...",
      "research_interests": "short, comma-separated",
      "status": "active|emeritus|deceased|moved-on",
      "notes": "free text"
    }
  ],
  "affiliations": [
    {
      "person_name": "Full Name",
      "facility_canonical_name": "Hubbard Brook Experimental Forest",
      "facility_acronym": "HBR",
      "role": "founding-PI|lead-PI|co-PI|information-manager|director|deputy-director|site-manager|faculty|emeritus|technical-staff",
      "title": "Distinguished Senior Scientist",
      "is_key_personnel": true,
      "start_date": "1988-01-01",
      "end_date": null,
      "source": "Cary Institute / HBR website",
      "source_url": "https://hubbardbrook.org/about-us/",
      "confidence": "high|medium|low",
      "notes": "Founder of Hubbard Brook Ecosystem Study"
    }
  ]
}
```

## Field requirements

- **At least one of orcid / openalex_id / google_scholar_id** per person
  is the goal. If you don't know any with high confidence, **omit the field**
  rather than invent one and set the affiliation `confidence = "low"` so
  the post-pass enrichment can fill in.
- **NEVER hallucinate identifiers.** A wrong ORCID is worse than a missing
  one. If you can't recall it confidently, leave the field null.
- **`person_name`** in `affiliations[]` joins to `name` in `people[]`;
  the ingest pipeline will resolve to a stable `person_id` hash.
- **`facility_canonical_name`** must match a facility already in the
  LTO database (check the names emitted by R-* agents in `data/raw/`).
  If the spelling differs slightly (apostrophes, dashes), the ingest
  pipeline will fuzz-match on lower-cased name + acronym.
- **`role`** vocabulary: `founding-PI`, `lead-PI` (current), `co-PI`,
  `information-manager`, `director`, `deputy-director`, `site-manager`,
  `faculty`, `emeritus`, `technical-staff`, `executive-officer`,
  `superintendent` (NMS), `manager` (NERR), `domain-manager` (NEON),
  `coordinator` (NPS-IM, MAB).
- **`is_key_personnel = true`** for directors, lead PIs, founding PIs,
  IMs, and named senior scientists. Set false for general faculty.

## Hard constraints (per agent)

- **DO NOT use WebFetch.** It's slow / blocked in this sandbox and is the
  root cause of Wave-B sub-agent timeouts. Use your training-data
  knowledge.
- Output the JSON in one Write call; do not stream multiple Edits.
- **Cap at ~50 people per agent** for first-pass coverage. A second loop
  can expand.
- **Validate ORCID format**: must match `^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$`.
- **Validate OpenAlex format**: must match `^A\d+$` (case-sensitive).
- Set `agent` provenance to your agent ID (e.g. `R-PEOPLE-LTER`).
- `retrieved_at = "2026-05-05"`.

## Post-pass enrichment

After all R-PEOPLE-* agents complete, the parent will:
1. Run `scripts/load_facility_personnel.py` → `db/lto.duckdb`.
2. Run `scripts/enrich_people_orcid.py` to backfill missing ORCIDs by
   querying the ORCID public API by name + institution.
3. Run `scripts/enrich_people_openalex.py` to backfill missing
   OpenAlex IDs by querying the OpenAlex API.
4. Run `scripts/enrich_people_gscholar.py` (optional, rate-limited).
5. Re-export parquet so the People tab in the UI shows everyone.
