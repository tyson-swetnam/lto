# R9 — Funding flows cross-cut

## Scope
Populate the `funders` table and `funding_links` many-to-many edges for every
facility produced by R1-R8. Runs after Wave 2 so facility IDs exist to link to.

Funding categories captured:
- Federal grants / cooperative agreements (NSF, NOAA, NIH, EPA, BOEM, ONR,
  USDA, USAID, NASA, DOE)
- State appropriations and grants
- Foundation grants (Moore, Packard, Walton, Schmidt, Bezos, Allen, Heising-Simons)
- Private donations / endowment income (where publicly disclosed)
- International / multilateral (IDB, World Bank, GEF, UN agencies)
- Industry / contract research

## Sources
- https://api.usaspending.gov/ — federal obligation-level data
- https://www.research.gov/common/webapi/awardapisearch-v1.htm
- https://api.nsf.gov/services/v1/awards.json
- https://api.reporter.nih.gov/v2/projects/search (coastal-health subset)
- https://projects.propublica.org/nonprofits/ — IRS 990 / 990-PF
- Foundation annual reports and public grant databases (Packard, Moore, Schmidt)
- State budget documents
- https://www.iadb.org/ — IDB project portal
- https://www.worldbank.org/en/projects-operations/projects-home

## Inputs
- `data/raw/R1..R8/*.json` (must be finalized first)

## Outputs
- `data/raw/R9/funders.csv`  columns: `funder_id,name,type,country,url,notes`
- `data/raw/R9/funding_links.csv`  columns: `funder_id,recipient_record_id,
  amount_usd,fiscal_year,award_id,relation,source_url`
- `data/raw/R9/notes.md`

## Method
1. Resolve recipient IDs by joining on `canonical_name` + `acronym` across all
   Wave 2 outputs.
2. For each recipient, query USAspending.gov for federal obligations aggregated
   by fiscal year and awarding agency.
3. Query NSF and NIH APIs for grant awards naming the facility as awardee.
4. For foundation grants, scrape annual-report grant lists where available or
   fall back to 990-PF data via ProPublica.
5. Normalize funder names (e.g., "NOAA NOS" → "NOAA"). Maintain an alias map
   in `data/raw/R9/funder_aliases.json`.
6. Convert foreign-currency amounts to USD using FX on award date (record rate).

## Verification expectations
- Every facility with a federal parent-agency relation in R1 should have at
  least one USAspending.gov link.
- Top funders by total should include: NSF, NOAA, NIH, EPA, Moore, Packard.
- Cross-check: NAML labs should collectively show >$100M in NSF awards over
  the last decade.

## Known landmarks
Not applicable — this agent produces edges, not facilities.
