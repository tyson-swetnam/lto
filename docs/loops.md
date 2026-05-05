# Agent loops

The `lto` pipeline runs in **fan-out batches**: the parent dispatches a
group of subagents in parallel, waits for all of them to write their
JSON, and then runs the next wave. Some scopes need a second pass —
either because the first-pass coverage was incomplete or because an
identifier could not be resolved without API access. Those are handled
by **loop agents**.

## Wave-B parallel research agents

The 11 facility agents under [methods](./methods.md) are dispatched as a
single batch. Each agent owns one sphere or sub-network and writes
`data/raw/<AGENT_ID>/facilities_<slug>.json`. The batch is followed by
`R-XREF` (sphere reconciliation + dedupe) and `R-FUND` (funding flows).

## Wave-F parallel people agents

The 9 `R-PEOPLE-*` agents (one per sphere/network) are dispatched as a
single batch. Each writes
`data/raw/R-PEOPLE-<sphere>/people.json` with `people[]` and
`affiliations[]` arrays. Cap is ~50 people per agent for first-pass
coverage.

## Loop iterations

When the first pass leaves measurable gaps, a loop agent re-runs over
the same scope with a narrower brief.

| Loop agent | Why |
|---|---|
| `R-PEOPLE-LOOP2-EFR` | First-pass `R-PEOPLE-EFR` covered ~40 of the 77 EFRs. The loop expands to the missing 37. |
| `R-PEOPLE-LOOP2-ORCID` | Re-runs over people whose ORCID is null but whose homepage suggests one is publicly listed. |
| `R-PEOPLE-LOOP2-OPENALEX` | Same pattern for OpenAlex Author IDs. |

## Sandbox network constraint

The agent sandbox has **WebFetch disabled** and the public ORCID /
OpenAlex / Google Scholar APIs blocked. This is the root cause of
Wave-B sub-agent timeouts in earlier runs — agents that tried to fetch
remote pages stalled.

The fix has two parts:

1. **Knowledge-only agents** — every R-* spec carries the rule
   *"DO NOT use WebFetch. Use your training-data knowledge."* Agents
   produce records from memory and explicitly leave low-confidence
   fields null.
2. **CI enrichment** — the heavy network calls (ORCID lookup, OpenAlex
   author search, Google Scholar profile scrape) run in CI via
   `.github/workflows/refresh-data.yml`, which executes
   `scripts/enrich_people_orcid.py`, `_openalex.py`, and `_gscholar.py`
   against the public APIs and rewrites the parquet outputs.

## Pattern for future contributors

When adding a new agent:

- Write a knowledge-only single-Write agent. One JSON file, one Write
  call, no streaming Edits.
- **Never hallucinate identifiers** — ORCIDs, DOIs, OpenAlex IDs. A
  wrong ID is worse than a missing one.
- Leave low-confidence fields null and mark
  `provenance.confidence = "low"`. The CI enrichment scripts (or a
  later loop agent) will backfill from the public APIs.
- Cite a `source_url` for every record. No record is ingested without
  one.
- If your scope overlaps another agent's, leave a `notes` field for
  `R-XREF` to reconcile in Wave E.
