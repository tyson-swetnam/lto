# H-FUND-* / H-PUB-* — Funding amounts and publications for the LTO network

## Scope (Wave H)

The LTO database has 647 `funding_events` rows but **0 of them carry an
`amount_usd` value**, and **0 publications / 0 authorship rows** despite
360 people in the database. External APIs (NSF Award Search,
USAspending.gov, OpenAlex, ORCID) all return `403 host_not_allowed` in
this sandbox, so this wave uses parallel sub-agents drawing on training-
data knowledge.

Two task families:

### H-FUND — funding amounts + award details

Six agents in parallel, each scoped to one funding agency / sphere:

| Agent | Scope |
|---|---|
| `H-FUND-NSF` | NSF DEB LTER cores, NSF DBI NEON, NSF OCE OOI, NSF OPP PAL/MCM, LTREB awards |
| `H-FUND-USDA` | USDA-ARS LTAR + Range Lab + Climate Hubs appropriations; USFS EFR appropriations |
| `H-FUND-NOAA` | IOOS RA cooperative agreements (NA21NOS… family), NERR base funding, NMS, NEP, GLERL/PMEL/AOML/GML appropriations, Sea Grant |
| `H-FUND-DOE` | AmeriFlux Management Project (LBNL), ARM user facility appropriation, FLUXNET; DOE BER terrestrial ecology |
| `H-FUND-USGS-DOI` | USGS Water Mission Area / WEBB / HBN / Benchmark Glaciers; NPS-IM appropriation; FWS NWRS appropriation |
| `H-FUND-OTHER` | EPA NEP / GLNPO / NARS / CASTNET / IMPROVE; NASA AERONET / TCCON; foundation + university endowments |

### H-PUB — flagship publications

Five agents in parallel:

| Agent | Scope |
|---|---|
| `H-PUB-LTER-FOUNDATIONAL` | Likens & Bormann's Hubbard Brook books, Magnuson NTL papers, Carpenter cascading-trophic, Tilman Cedar Creek, Chapin Arctic boreal, Pickett urban ecology, Knapp Konza, Peters Jornada, Lugo Luquillo |
| `H-PUB-EFR-USFS` | Lugo et al. 2006 BioScience, Coweeta Swank & Crossley, Andrews old-growth (Franklin), Fernow acid-rain (Adams), Bonanza Creek fire (Chapin) |
| `H-PUB-NEON-FLAGSHIP` | Schimel et al. NEON design papers, Keller et al. AOP, Loescher tower data, Kao et al. NEON aquatic |
| `H-PUB-ATM-CRY` | Keeling Curve Mauna Loa series, Tans NOAA-GML synthesis, Wofsy AmeriFlux, McKnight DOM, Romanovsky permafrost, Fountain glacier mass balance, Serreze sea-ice |
| `H-PUB-OCEAN-FRESH` | Ducklow Palmer LTER, Ohman CCE, Sosik PIE, Schofield OOI, Feely PMEL OA, Capers GLEON, Hanson lake CO2, Carpenter NTL |

## Output formats

### H-FUND output (per agent)

`/home/user/lto/data/raw/<AGENT>/funding_events.json`:

```json
[
  {
    "facility_canonical_name": "Hubbard Brook Experimental Forest",
    "facility_acronym": "HBR",
    "funder_name": "NSF",
    "funder_type": "federal",
    "amount_usd": 980000,
    "fiscal_year": 2022,
    "period_start": "2017-12-01",
    "period_end": "2023-11-30",
    "award_id": "DEB-1633026",
    "award_title": "LTER: The Hubbard Brook Ecosystem Study",
    "program": "NSF LTER",
    "relation": "grant",
    "source": "NSF Award Search (training-data recall)",
    "source_url": "https://www.nsf.gov/awardsearch/showAward?AWD_ID=1633026",
    "confidence": "high",
    "notes": "Approximate annual obligation; nominal USD"
  }
]
```

### H-PUB output (per agent)

`/home/user/lto/data/raw/<AGENT>/publications.json`:

```json
{
  "publications": [
    {
      "doi": "10.1126/science.184.4142.1176",
      "title": "Nutrient cycling in a deciduous forest ecosystem",
      "pub_year": 1974,
      "pub_type": "journal-article",
      "journal": "Science",
      "venue": "Science 184(4142): 1176-1179",
      "cited_by_count": 600,
      "openalex_id": null,
      "url": "https://doi.org/10.1126/science.184.4142.1176",
      "source": "training-data recall",
      "notes": "Foundational HBR nutrient-cycling paper"
    }
  ],
  "authorship": [
    {"doi": "10.1126/science.184.4142.1176", "person_name": "Gene E. Likens", "author_position": 1, "is_corresponding": true},
    {"doi": "10.1126/science.184.4142.1176", "person_name": "F. Herbert Bormann", "author_position": 2, "is_corresponding": false}
  ]
}
```

## Hard constraints (every agent)

- **NEVER hallucinate a DOI, ORCID, NSF award ID, or amount.** If you are
  not highly confident, leave the field null and rely on `notes` to
  describe the source. A wrong DOI / award ID is worse than a missing one.
- **Single Write per file** — no streaming Edits.
- **NO WebFetch** — hosts are blocked at the sandbox network and will
  time out the agent (root cause of every Wave-B / Wave-F retry).
- For funding amounts, prefer round-number annual obligations from the
  NSF cooperative-agreement / award abstract you remember; mark
  `confidence = "medium"` if you only remember the order-of-magnitude
  total. Do not guess to the dollar.
- DOIs must match the format `^10\.\d{4,9}/[\w./()<>:;-]+$` (Crossref
  pattern). If a DOI you think you remember doesn't match, drop it.
- NSF award IDs must match `^(DEB|DBI|OCE|OPP|EAR|AGS|ATM|GEO|NSF)-?\d{6,7}$`.
- Authorship `person_name` must be a name already in the people table —
  the loader resolves `lower(person_name)` to `person_id`. If you don't
  know the actual lead author from training data, drop the affiliation
  rather than guess.
- `agent` provenance set to your agent ID; `retrieved_at = "2026-05-05"`.

## Loader pattern

After all agents complete, the parent runs:

1. `scripts/load_lto_funding.py` — merges agent JSON into `funding_events`
   with `event_id = sha1(funder||facility||award||fy)` for idempotent
   upsert.
2. `scripts/load_lto_publications.py` — merges into `publications` +
   `authorship` with deterministic `publication_id = sha1(doi or title)`.
3. `scripts/dedupe_people.py` — re-run to merge any new person duplicates.
4. `scripts/export_parquet.py` — re-publish parquet + facilities.geojson.

## Loop iteration

If first-pass coverage is below the targets below, fan-out a second
loop of agents focused on the gaps reported by Wave H-1:

- Funding target: ≥1 amount-bearing event per LTER + LTAR + EFR + IOOS
  RA + NERR (≈ 80 facilities → 80 amount-bearing rows).
- Publications target: ≥3 high-cited papers per top-100 most-affiliated
  PI (i.e. ≈ 300 publications + 600+ authorship rows after dedup).
