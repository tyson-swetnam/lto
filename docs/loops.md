# Agent loops

The `lto` pipeline runs in **fan-out batches**: the parent dispatches a
group of subagents in parallel, waits for all of them to write their
JSON, and then runs the next wave. Some scopes need a second pass,
either because the first pass left gaps or because what it wrote could
not be trusted. Those second passes are the **loops** on this page.

## Wave-B parallel facility agents

The nine facility agents listed under [methods](./methods.md) (`R-ATM`,
`R-CRY`, `R-TER-LTER`, `R-TER-EFR`, `R-TER-NEON`, `R-TER-OTHER`,
`R-AGR`, `R-AQ-OCEAN-CULL`, `R-AQ-FRESH`) are dispatched as a single
batch. Each agent owns one sphere or sub-network and writes
`data/raw/<AGENT_ID>/facilities_<slug>.json`. The batch is followed by
`R-XREF` (sphere reconciliation + dedupe) and `R-FUND` (funding flows).

Later regional layers are built by scripts that fetch their sources:
the ARID Institute (`fetch_arid_site.py`), EnviroData-NM
(`fetch_envirodata_nm.py`) and the Arizona Water Observatory
(`fetch_az_water_observatory.py`). See [ARID & New Mexico](./arid.md).

## People: from recall to fetched sources

### First pass (May 2026, superseded)

The first people wave was nine `R-PEOPLE-<sphere>` agents (one per
sphere or network), each capped at about 50 people. They wrote
`data/raw/R-PEOPLE-<sphere>/people.json`, which `load_lto_people.py`
loaded. The sandbox blocked web access, so the spec told agents to work
from training-data knowledge, and every row was stamped
`retrieved_at = 2026-05-05`. The result was stale lead PIs, managers
attached to the wrong reserve, and ORCIDs that belonged to someone else.
That wave is no longer the method. Its rows that have not been
re-checked are still in the lake.

### R-PEOPLE2 (October 2026)

The current wave follows `agents/R-PEOPLE.md`. Every value comes from a
page fetched in the run, and a missing field is preferred to a guessed
one. Each batch goes through five steps.

1. **Research.** An agent takes a batch of up to 12 facilities, fetches
   each facility's leadership pages, the network's site page and
   people's profile pages, and records every page it fetched. Each
   affiliation carries a `source_url` and an `evidence` quote from that
   page. Existing leadership rows at the facility get a verdict:
   `confirmed`, `stale`, `not-found` or `unverifiable`. A separate
   bio batch (`R-PEOPLE2-BIO`) adds a short sourced bio, research
   interests, ORCID and status for people already in the lake.
2. **Adversarial verify.** A second agent tries to break the draft. It
   re-fetches every cited URL, checks that each quote is on its page,
   confirms every ORCID at `pub.orcid.org`, checks the bio rules (60
   words or fewer, no long copied runs, no email, phone or photo) and
   the role vocabulary. It drops or corrects what fails and stamps the
   file `verified_by`. Only verified files are committed.
3. **Load.** `scripts/load_people_research.py` loads each file as one
   lake transaction. An unknown `facility_id` or role stops the file.
   A batch that names the current holder of a leadership role marks any
   other current holder of that role `is_current = false`; the old row
   is kept.
4. **Dedupe and merge.** `scripts/dedupe_people.py` merges two `people`
   rows only on evidence: a shared ORCID, a verified ORCID, the same
   name plus the same OpenAlex id, homepage or cited page, or a reviewed
   pair in `data/seed/people_merge_seed.csv`. A name alone never merges
   two people. Each merge is logged in `data/seed/people_merge_log.csv`.
5. **Identity enrichment.** An operator runs the ORCID and OpenAlex
   passes from `RUNBOOK.md` (they need network access and, for OpenAlex,
   `OPENALEX_API_KEY`), then the `compute_*` scripts, `qa.py`,
   `export_parquet.py` and `export_view_caches.py`. In both OpenAlex
   passes every new or changed attribution was checked against the
   OpenAlex author record, and disputed ones got a second review
   (`data/seed/openalex_attribution_review_2026-10-23.csv` and
   `…_2026-10-24.csv`).

As of 2026-10-23 the committed batches are 51 research files covering
267 facilities and 31 bio files with 290 updates, all fetched on
2026-10-22 and verified the same day.

## Loop iterations

| Loop | What it does | State as of 2026-10-24 |
|---|---|---|
| `R-PEOPLE2` research | Re-researches each facility's leaders from fetched pages and rules on the rows already there | 51 batches, 267 facilities. 862 of 1,537 affiliation rows come from this pass |
| `R-PEOPLE2-BIO` | Sourced bio, interests, ORCID and status for existing people | 31 batches, 290 updates; 780 people have a bio |
| `dedupe_people.py` | Merges duplicate people on identifier or page evidence | 56 merges logged |
| `enrich_people_orcid.py` | Strict ORCID backfill: family name, given name and an employment at a known facility must all match; a person with no facility on file is matched only when the name resolves to exactly one ORCID (34 such matches logged `accept-name-only`) | 611 people have an ORCID. 79 wrong or dead iDs are logged `cleared-*` in `data/seed/orcid_resolution_log.csv` and are never re-attached; `qa.py` fails if a cleared-wrong iD comes back |
| `enrich_people_openalex.py` | Attaches OpenAlex ids and publication lists by stored id or ORCID only; name search is disabled, and research interests are fill-only | Complete: all 1,302 people in the queue processed (378 in pass 1, 924 in pass 2); 560 people have an OpenAlex id and 745 do not (679 with neither an ORCID nor an OpenAlex id, 66 with an ORCID only). In pass 2, 517 of 924 could not be matched: 478 with neither identifier, 39 with an ORCID OpenAlex does not know. Reviews are in `data/seed/openalex_attribution_review_2026-10-23.csv` and `…_2026-10-24.csv` (338 rows: 322 keep, 5 keep-disputed, 11 remove) |
| `url-health.yml` (weekly) | HEAD sweep of every stored URL, then pattern rewrites | The 2026-10-23 sweep nulled 66 junk homepage URLs |

What the next loops should cover:

- **OpenAlex, unmatched people.** Every person in the queue has been
  through OpenAlex, but 745 people still have no OpenAlex id: 679 have
  neither an ORCID nor an OpenAlex id, and 66 have an ORCID but no
  OpenAlex id (8 of them had one removed in review). Pass 2 alone left
  517 of these (478 with no identifier, 39 with an ORCID OpenAlex does not
  know). They can be reached only once a confirmed identifier is found.
- **Older affiliation rows.** 675 affiliation rows predate R-PEOPLE2
  (654 dated 2026-04-24 to 2026-10-09, and 21 with no date). R-PEOPLE2
  has ruled on 91 of them (62 marked former, 29 not found on official
  pages), and 30 are ARID rows built from fetched pages. The other 554
  have not been re-checked against a fetched page.
- **Facilities with no current leader.** 29 facilities have no current
  leadership row (a row marked current by a fetched page, or an older
  row nobody has marked former). 15 of them have no personnel at all;
  they are SCAN, SNOTEL and snow-pillow stations.

The first plan also named three loop agents, `R-PEOPLE-LOOP2-EFR`,
`R-PEOPLE-LOOP2-ORCID` and `R-PEOPLE-LOOP2-OPENALEX`. None of them left
a spec or a batch file in the repo. The two enrichment scripts now do
the ORCID and OpenAlex work. The EFR work is only partly done: the
catalogue holds 40 facilities of type `experimental-forest-range`, and
R-PEOPLE2 has re-researched 11 of them so far (6 in its `USFS-EFR`
batch). The other 29 carry only older rows.

## Network access

In the first runs the agent sandbox had **WebFetch disabled**, and the
public ORCID, OpenAlex and Google Scholar APIs were blocked. Agents that
tried to fetch remote pages stalled, and that caused the Wave-B
sub-agent timeouts. The workaround was knowledge-only agents: the first
`R-PEOPLE` spec, `H-FUND-PUB` and `J-DATA` all told agents not to fetch
and to use training-data knowledge instead.

That workaround is retired for people. R-PEOPLE2 agents fetch pages and
the verifier re-fetches them. Compared with the recall-era data, this
pass raised LTER lead PIs that match lternet.edu from 8 of 26 to 26 of
26 and cut facilities with no current leader from 252 to 29. It also
cleared 75 wrong stored ORCIDs (figures from the PR #13 summary).

Two older layers are still recall-based, and the site should be read
with that in mind:

- **Funding.** The `source` of every `funding_events` row that has a
  dollar amount marks it as recalled, not fetched.
- **Personnel rows from the May 2026 recall pass.** 555 rows are dated
  2026-05-05 or 2026-05-06; R-PEOPLE2 has ruled on 75 of them, and the
  rest have not been re-checked. The ARID rows are not in this group:
  they are built from fetched pages.

The enrichment passes are **not** run in CI. `refresh-data.yml` rebuilds
the lake from the committed Parquet, reloads the ARID and data-archive
layers, backfills facility states, runs `qa.py` and the exports, and
opens a pull request. It does not ingest new raw JSON or run any
`enrich_people_*` script. An operator runs those locally, following
`RUNBOOK.md`.

## Pattern for future contributors

When adding a new agent:

- **Fetch, don't recall.** Every value cites a page fetched in this run,
  and `retrieved_at` is the real fetch date (rule 9 in
  `agents/README.md`). If a page cannot be fetched, leave the field
  null.
- Write one JSON file per batch, then have a second agent verify it
  adversarially before it goes into `data/raw/`.
- **Never hallucinate identifiers** (ORCIDs, DOIs, OpenAlex ids). A
  wrong ID is worse than a missing one. Confirm an ORCID at
  `pub.orcid.org` and leave OpenAlex and Google Scholar ids to the
  enrichment scripts.
- Cite a `source_url` for every record. For people, every affiliation
  also needs an `evidence` quote; `load_people_research.py` refuses an
  affiliation that lacks either. (Some recall-era rows have no
  `source_url`: 46 facilities and 31 personnel rows.)
- Mark `confidence` honestly: `high` when the page names the person in
  that role at that facility, and lower when the page supports less.
- If a facility agent's scope overlaps another agent's, leave a `notes`
  field for `R-XREF` to reconcile in Wave E.
