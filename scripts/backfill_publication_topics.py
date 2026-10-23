#!/usr/bin/env python3
"""Backfill publication_topics for already-stored publications.

When the enrichment script ran for the first time it didn't yet write
to publication_topics — that table didn't exist. Rather than re-fetching
every author's full work list, this script walks `publications` (which
already have an OpenAlex id) and fetches the per-Work topics in
batched calls (~50 works per request via OpenAlex `filter=ids.openalex:`),
which is ~10× faster than re-running enrich_people_openalex.py.

Idempotent: skips any publication that already has at least one row in
publication_topics. Re-running fills in the gaps left by previous runs.

Rows are staged in a TEMP table while the batches are fetched and land
in the DuckLake in one transaction at the end (one snapshot). Ctrl-C
stops fetching and still writes what was staged, so an interrupted run
keeps its progress.

Usage::

    python scripts/backfill_publication_topics.py
    python scripts/backfill_publication_topics.py --limit 500
    python scripts/backfill_publication_topics.py --batch-size 25
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("[error] pip install requests --break-system-packages", file=sys.stderr)
    raise

# Reuse the topic-row builder + id-shortener from the main enricher so
# we never diverge on what counts as a row.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from enrich_people_openalex import (  # noqa: E402
    _short_concept_id, session as _session,
)


def _topic_rows_for_work(pub_id: str, w: dict) -> list[tuple]:
    """Return all (publication_id, concept_id, ...) rows for one work."""
    rows: list[tuple] = []
    for c in (w.get("concepts") or []):
        cid = _short_concept_id(c.get("id"))
        name = c.get("display_name")
        if cid and name:
            rows.append((pub_id, cid, name, c.get("score"), c.get("level"),
                         "concept", "openalex"))
    for t in (w.get("topics") or []):
        tid = _short_concept_id(t.get("id"))
        name = t.get("display_name")
        if tid and name:
            rows.append((pub_id, tid, name, t.get("score"), None,
                         "topic", "openalex"))
    for k in (w.get("keywords") or []):
        kid = _short_concept_id(k.get("id"))
        name = k.get("display_name")
        if kid and name:
            rows.append((pub_id, kid, name, k.get("score"), None,
                         "keyword", "openalex"))
    return rows


TOPIC_STAGE_DDL = """
    CREATE OR REPLACE TEMP TABLE _topic_stage (
        publication_id  VARCHAR,
        concept_id      VARCHAR,
        concept_name    VARCHAR,
        score           DOUBLE,
        level           INTEGER,
        kind            VARCHAR,
        source          VARCHAR
    )
"""


def stage_topics(conn, all_rows: list[tuple], seen: set) -> int:
    """Stage topic rows in the TEMP table (not a lake write). Dedupes on
    (publication_id, concept_id) across the whole run via ``seen``; the
    insert-only merge in write_topics() skips pairs already in the lake.
    Returns the number of rows staged."""
    if not all_rows:
        return 0
    # Dedupe (the same (pub_id, concept_id) may appear twice if a work
    # somehow lists a concept under two ontologies — we keep whichever
    # came first, which is fine).
    deduped: list[tuple] = []
    for r in all_rows:
        key = (r[0], r[1])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    if deduped:
        conn.executemany(
            "INSERT INTO _topic_stage VALUES (?, ?, ?, ?, ?, ?, ?)",
            deduped,
        )
    return len(deduped)


def write_topics(conn, n_pubs: int) -> int:
    """Insert the staged pairs the lake lacks, in one transaction.
    Returns the number of rows inserted."""
    with lto_db.transaction(
            conn, f"backfill_publication_topics: topics for {n_pubs} "
                  f"publication(s)"):
        st = lto_db.merge_upsert(
            conn, "publication_topics", ["publication_id", "concept_id"],
            "_topic_stage", insert_only=True)
        lto_db.assert_integrity(conn, ["publication_topics"])
    return st["inserted"]


API = "https://api.openalex.org"
BATCH = 50
RETRY = 3


def fetch_works_batch(sess: requests.Session, oa_ids: list[str]) -> list[dict]:
    if not oa_ids:
        return []
    # OpenAlex accepts |-separated id list with filter=ids.openalex:
    flt = "ids.openalex:" + "|".join(oa_ids)
    for attempt in range(RETRY):
        try:
            r = sess.get(
                f"{API}/works",
                params={"filter": flt, "per_page": BATCH},
                timeout=30,
            )
            if r.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as e:
            print(f"[warn] batch fetch failed ({attempt + 1}/{RETRY}): {e}")
            time.sleep(1 + attempt)
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="Deprecated alias of --catalog.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Max publications to backfill (0 = all)")
    ap.add_argument("--batch-size", type=int, default=BATCH)
    ap.add_argument("--only-missing", action="store_true", default=True,
                    help="Skip publications that already have topic rows (default)")
    ap.add_argument("--authored-only", action="store_true",
                    help="Only backfill publications that have at least one "
                         "row in `authorship` (i.e. one of our known people "
                         "authored it). Cuts the work set from ~37k to ~8k "
                         "and is what compute_person_areas.py actually needs.")
    args = ap.parse_args()

    try:
        conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    sess = _session()
    conn.execute(TOPIC_STAGE_DDL)

    # publications that have an openalex_id and (when --only-missing)
    # don't already have any rows in publication_topics.
    authored_join = """
        JOIN (SELECT DISTINCT publication_id FROM authorship) au
          ON au.publication_id = p.publication_id
    """ if args.authored_only else ""
    pubs = conn.execute(f"""
        SELECT p.publication_id, p.openalex_id
        FROM publications p
        {authored_join}
        LEFT JOIN (
            SELECT DISTINCT publication_id FROM publication_topics
        ) t ON t.publication_id = p.publication_id
        WHERE p.openalex_id IS NOT NULL
          AND p.openalex_id <> ''
          AND t.publication_id IS NULL
        ORDER BY p.publication_id
    """).fetchall()
    if args.limit:
        pubs = pubs[: args.limit]
    print(f"[backfill] {len(pubs)} publications to fetch (batch={args.batch_size})")

    # Build a map oa_short_id -> publication_id so we can match returned
    # works back to the right publication_id (handles cases where the
    # publication_id is the DOI or differs from the short oa id).
    map_oa_to_pub: dict[str, str] = {}
    todo_ids: list[str] = []
    for pub_id, oa in pubs:
        oa_short = (oa.split("/")[-1] if oa.startswith("http") else oa).strip()
        if not oa_short:
            continue
        map_oa_to_pub[oa_short] = pub_id
        todo_ids.append(oa_short)

    total_topics = 0
    total_pubs_done = 0
    seen: set = set()
    try:
        for i in range(0, len(todo_ids), args.batch_size):
            chunk = todo_ids[i : i + args.batch_size]
            works = fetch_works_batch(sess, chunk)
            batch_rows: list[tuple] = []
            for w in works:
                oa_short = (w.get("id", "").split("/")[-1])
                pid = map_oa_to_pub.get(oa_short)
                if not pid:
                    continue
                batch_rows.extend(_topic_rows_for_work(pid, w))
                total_pubs_done += 1
            n = stage_topics(conn, batch_rows, seen)
            total_topics += n
            # Progress
            done_pct = 100 * (i + len(chunk)) / max(len(todo_ids), 1)
            print(f"  [{i + len(chunk)}/{len(todo_ids)} {done_pct:5.1f}%] "
                  f"pubs_done={total_pubs_done}  topics staged={total_topics}")
            # Tiny politeness delay; OpenAlex polite pool is generous.
    except KeyboardInterrupt:
        print("\n[interrupted] writing the topics staged so far")

    written = write_topics(conn, total_pubs_done) if total_topics else 0
    conn.close()
    print(f"[done] pubs={total_pubs_done}  topics_written={written}"
          f"{'  (run export_parquet.py to publish)' if written else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
