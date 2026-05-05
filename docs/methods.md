# Methods

`lto` is a research-agent ETL on top of a static visualisation stack.
Source records are produced by **knowledge-only** subagents (one markdown
spec per agent under `agents/`), validated by a QA gate, ingested into
DuckDB, and exported as Parquet + GeoJSON for the browser.

## Wave model

```
Wave 0  Vendor cod-kmap engine                    (one-time bootstrap)
Wave A  D1 schema deltas + D3 vocab extension     (contracts)
Wave B  R-* facility research agents              (raw JSON per sphere)
Wave C  D2 ingest → db/lto.duckdb → public/parquet/
Wave D  F1..F4 frontend + deploy
Wave E  R-XREF reconciliation + coverage report
Wave F  R-PEOPLE-* + R-PEOPLE-LOOP2-* people pass
```

Each wave is a single parallel batch over its sub-agents; the parent
runs the next wave only after every agent in the prior wave has emitted
its JSON. The entry-point script for each wave is `scripts/ingest.py`
(Wave C), `scripts/qa.py` (gate between waves), and the per-pass
enrichment scripts (post-Wave-F).

## Sub-agent roster

| Bundle | Agents | Scope |
|---|---|---|
| Wave-B facility | 11 | One per sphere or sub-network: `R-ATM`, `R-CRY`, `R-TER-LTER`, `R-TER-EFR`, `R-TER-NEON`, `R-TER-OTHER`, `R-AGR`, `R-AQ-OCEAN-CULL`, `R-AQ-FRESH`, plus `R-XREF` and `R-FUND` |
| Wave-F people | 9 | One per sphere/network: `R-PEOPLE-LTER`, `R-PEOPLE-NEON`, `R-PEOPLE-EFR`, `R-PEOPLE-AGR`, `R-PEOPLE-OCEAN`, `R-PEOPLE-FRESH`, `R-PEOPLE-ATM`, `R-PEOPLE-CRY`, `R-PEOPLE-OTHER` |
| Loop / repair | 2+ | `R-PEOPLE-LOOP2-EFR`, `R-PEOPLE-LOOP2-ORCID`, etc. — see [loops](./loops.md) |
| Cross-cutting | 2 | `R-XREF` (sphere reconciliation), `R-FUND` (funding flows) |

## Inclusion gate

The default filter is the **Peters et al. 2013 ≥10-year continuous-record
threshold** (`record_length_years >= 10`). Records below the threshold
are kept in the database with `long_term_threshold_met = false` but
hidden by default in the UI. NEON, LTER, and LTAR sites with shorter
records are kept on the basis of their parent network's intent.

## Provenance

Every record carries a `provenance` block:

```json
{
  "source_url": "https://hubbardbrook.org/about-us/",
  "retrieved_at": "2026-05-05",
  "confidence": "high",
  "agent": "R-TER-LTER"
}
```

- **`source_url`** is required. No record may be ingested without one.
- **`retrieved_at`** is the date the agent observed the source.
- **`confidence`** is one of `high` (primary agency / institution page),
  `medium` (third-party aggregator), or `low` (inferred or memory-only).
  Low-confidence records are kept and surfaced for manual review.

## Identifier strategy

For the people side (`R-PEOPLE-*`):

- The ID priority is **ORCID > OpenAlex > Google Scholar > homepage URL**.
- Subagents **never hallucinate** identifiers. If they cannot recall an
  ORCID with high confidence, they leave the field null and the record
  is marked `confidence = "low"`.
- ORCID format is regex-validated (`^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$`).
- OpenAlex format is regex-validated (`^A\d+$`).
- Empty identifier fields are backfilled by the enrichment scripts in CI
  (`scripts/enrich_people_orcid.py`, `_openalex.py`, `_gscholar.py`)
  which query the public APIs by name + institution.

## Static stack

The browser side is **DuckDB-Wasm + MapLibre, no build step**:

- `index.html` defines an importmap that pulls `maplibre-gl` and
  `@duckdb/duckdb-wasm` from esm.sh.
- `src/db.js` registers `public/parquet/*.parquet` as DuckDB views and
  re-creates helper views (these don't survive Parquet export).
- `src/views/{list,stats,docs,network,people,sql}.js` render one tab each.
- The deploy workflow (`.github/workflows/deploy.yml`) stages only
  `index.html`, `favicon.svg`, `src/`, `public/`, and `docs/`. Everything
  else (`agents/`, `scripts/`, `schema/`, `data/raw/`) is excluded from
  the live site.
