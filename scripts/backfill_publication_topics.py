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

import duckdb

try:
    import requests
except ImportError:
    print("[error] pip install requests --break-system-packages", file=sys.stderr)
    raise

# Reuse the topic-row builder + id-shortener from the main enricher so
# we never diverge on what counts as a row.
sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def bulk_upsert_topics(conn, all_rows: list[tuple]) -> int:
    """Bulk-insert topic rows. Uses a temp table + INSERT ... SELECT
    DISTINCT to dedupe within the batch, then ANTI-JOIN against the
    existing publication_topics so we only insert new (publication_id,
    concept_id) pairs. ~50× faster than per-row ON CONFLICT INSERTs."""
    if not all_rows:
        return 0
    # Dedupe within the batch (the same (pub_id, concept_id) may appear
    # twice if a work somehow lists a concept under two ontologies — we
    # keep whichever came first, which is fine).
    seen: set = set()
    deduped: list[tuple] = []
    for r in all_rows:
        key = (r[0], r[1])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("""
            CREATE TEMP TABLE _topic_stage (
                publication_id  VARCHAR,
                concept_id      VARCHAR,
                concept_name    VARCHAR,
                score           DOUBLE,
                level           INTEGER,
                kind            VARCHAR,
                source          VARCHAR
            )
        """)
        conn.executemany(
            "INSERT INTO _topic_stage VALUES (?, ?, ?, ?, ?, ?, ?)",
            deduped,
        )
        before = conn.execute("SELECT COUNT(*) FROM publication_topics").fetchone()[0]
        conn.execute("""
            INSERT INTO publication_topics
            SELECT s.* FROM _topic_stage s
            LEFT JOIN publication_topics t
              ON t.publication_id = s.publication_id
             AND t.concept_id     = s.concept_id
            WHERE t.publication_id IS NULL
        """)
        after = conn.execute("SELECT COUNT(*) FROM publication_topics").fetchone()[0]
        conn.execute("DROP TABLE _topic_stage")
        conn.execute("COMMIT")
        return after - before
    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"[bulk-insert] failed, falling back to per-row: {e}")
        return 0

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
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
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
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

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))
    sess = _session()

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
        n = bulk_upsert_topics(conn, batch_rows)
        total_topics += n
        # Progress
        done_pct = 100 * (i + len(chunk)) / max(len(todo_ids), 1)
        print(f"  [{i + len(chunk)}/{len(todo_ids)} {done_pct:5.1f}%] "
              f"pubs_done={total_pubs_done}  topics+={total_topics}")
        # Tiny politeness delay; OpenAlex polite pool is generous.

    conn.close()
    print(f"[done] pubs={total_pubs_done}  topics_written={total_topics}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
