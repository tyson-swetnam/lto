
"""Capped, quota-aware LTO-works harvest for the lto registry.

Design constraints measured live (on upstream cod-kmap's runs), not assumed:
  * The OpenAlex key carries a HARD quota (X-RateLimit-Limit: 10000/day, one
    credit per request). Budget is therefore counted in REQUESTS, not seconds.
  * Throughput is capped server-side at ~62 works/s and does NOT improve with
    concurrency (1/4/8 threads all measured 60-87 works/s), so this runs
    single-threaded. Sharding would split bookkeeping, not wall time.
  * Authors are batched 50 per cursor: same per-work cost, but one cursor
    covers 50 authors instead of one (3.4s/200 works vs ~7s/200 single-author).
  * Per-author cap: works are requested most-cited-first so a truncated author
    keeps their highest-signal collaborations.

Writes incrementally: every batch appends to parquet and updates a resume
manifest, so an interrupted or quota-exhausted run resumes where it stopped.
Works are restricted to the curated LTO topic set
(schema/vocab/lto_openalex_topics.csv).
"""
import json, math, os, sys, time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oa_harvest as oah

ROOT = Path(__file__).resolve().parents[1]
# Resume manifest + per-batch shards are checkpoint state, not committed
# pipeline artifacts: they live under data/raw/oa_harvest/_state/ (gitignored).
STATE_DIR = ROOT / "data" / "raw" / "oa_harvest" / "_state"
STATE = str(STATE_DIR / "harvest_state.json")
WORKS_OUT = str(STATE_DIR / "harvest_works.parquet")
PAIRS_OUT = str(STATE_DIR / "harvest_pairs.parquet")


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"done_batches": [], "requests_used": 0, "works": 0, "pairs": 0}


def save_state(st):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"))
    os.replace(tmp, STATE)


def append_parquet(path, rows, batch_index=None):
    """Write rows as an IMMUTABLE per-batch shard under <path>.d/.

    The earlier implementation (upstream cod-kmap) read the whole file,
    concatenated, and rewrote it. That is a read-modify-write on a growing
    file: a reader (or a second harvest process) that opens it mid-write sees
    truncated bytes and fails with "Parquet magic bytes not found in footer"
    — observed once upstream at 19.5 MB. Per-batch shards are write-once, so
    no reader ever sees a partial file and the cost per batch stops growing
    with the corpus. Consumers read the directory as a dataset:
    pq.read_table('data/raw/oa_harvest/_state/harvest_pairs.parquet.d').
    """
    if not rows:
        return
    d = path + ".d"
    os.makedirs(d, exist_ok=True)
    tag = f"{batch_index:05d}" if batch_index is not None else str(int(time.time() * 1000))
    tmp = os.path.join(d, f".tmp-{tag}.parquet")
    final = os.path.join(d, f"part-{tag}.parquet")
    pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False),
                   tmp, compression="zstd")
    os.replace(tmp, final)   # atomic: readers see either absent or complete


def harvest(shards_df, topic_ids=None, per_author_cap=200, batch_size=50,
            request_budget=6500, progress_every=10):
    """Harvest LTO works for every author in shards_df.

    topic_ids None loads the curated set from
    schema/vocab/lto_openalex_topics.csv (fails loudly when missing/empty).

    per_author_cap bounds pages per BATCH as ceil(cap*batch_size/200), which is
    the honest way to cap when authors share a cursor: a batch of 50 authors at
    cap 200 gets at most 50 pages. Authors within a batch that are far more
    prolific than their peers therefore share the batch budget -- recorded in
    the manifest as batch_truncated so the report can state it.
    """
    if topic_ids is None:
        topic_ids = oah.load_topic_ids()
    st = load_state()
    raw_ids = list(shards_df.openalex_id)
    ids = [str(v).rsplit("/", 1)[-1] for v in raw_ids
           if v is not None and str(v).strip() not in ("", "nan", "None")]
    skipped = len(raw_ids) - len(ids)
    if skipped:
        # A row without an openalex_id cannot be harvested (the works filter
        # is author.id). It is skipped and counted -- never minted a local
        # id; lto's registry has no third id form.
        print(f"[warn] skipped {skipped} shard rows lacking openalex_id")
    batches = [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)]
    max_pages = math.ceil(per_author_cap * batch_size / 200)
    t0 = time.time()
    for bi, batch in enumerate(batches):
        if bi in st["done_batches"]:
            continue
        if st["requests_used"] >= request_budget:
            print(f"[budget] stopping: {st['requests_used']} requests used "
                  f"of {request_budget}")
            break
        focal = set(batch)
        works, pairs = [], []
        # Resume from the saved cursor for a batch previously cut short by
        # budget, instead of restarting at '*'. Restarting re-fetches pages
        # already paid for: upstream cod-kmap measured 1,000 duplicate works
        # and 5 wasted requests on a 2-run test before this was stored.
        resume = (st.get("cursors") or {}).get(str(bi))
        cursor = resume or "*"
        pages = int((st.get("pages_done") or {}).get(str(bi), 0))
        seen_works = set()
        while pages < max_pages:
            # Budget is checked INSIDE the page loop, not just between
            # batches: one batch can otherwise spend up to max_pages
            # requests past the limit (measured upstream: 50 spent against
            # a budget of 6 when the check was per-batch only).
            if st["requests_used"] >= request_budget:
                break
            d = oah.oa_get(
                "works",
                filter="author.id:" + "|".join(batch) + ",topics.id:" + "|".join(topic_ids),
                select="id,doi,publication_year,title,cited_by_count,authorships",
                sort="cited_by_count:desc",
                cursor=cursor, **{"per-page": "200"})
            st["requests_used"] += 1
            pages += 1
            res = d.get("results") or []
            for w in res:
                wid = oah.short_id(w.get("id"))
                if wid in seen_works:
                    continue
                seen_works.add(wid)
                # Attribute the work to every focal author on it.
                authorships = w.get("authorships") or []
                focal_on_work = [oah.short_id((a.get("author") or {}).get("id"))
                                 for a in authorships]
                hits = [f for f in focal_on_work if f in focal]
                wr, _ = oah.coauthor_pairs(w, hits[0] if hits else None)
                wr["focal_openalex_ids"] = ";".join(sorted(set(hits)))
                works.append(wr)
                for f in set(hits):
                    _, prs = oah.coauthor_pairs(w, f)
                    pairs.extend(prs)
            cursor = (d.get("meta") or {}).get("next_cursor")
            if not cursor or not res:
                break
        append_parquet(WORKS_OUT, works, batch_index=bi)
        append_parquet(PAIRS_OUT, pairs, batch_index=bi)
        # A batch is "done" only if it exhausted its cursor or hit the
        # per-author cap. A batch cut short by the REQUEST BUDGET is left
        # unmarked so the next run re-attempts it -- otherwise a
        # quota-exhausted run silently drops those authors' remaining works.
        # (Re-attempting re-fetches its earlier pages; the work_id dedupe in
        # the consumer handles the overlap.)
        budget_cut = (st["requests_used"] >= request_budget
                      and cursor and pages < max_pages)
        if budget_cut:
            st.setdefault("budget_cut_batches", [])
            if bi not in st["budget_cut_batches"]:
                st["budget_cut_batches"].append(bi)
            st.setdefault("cursors", {})[str(bi)] = cursor
            st.setdefault("pages_done", {})[str(bi)] = pages
        else:
            st["done_batches"].append(bi)
            (st.get("cursors") or {}).pop(str(bi), None)
            (st.get("pages_done") or {}).pop(str(bi), None)
        st["works"] += len(works)
        st["pairs"] += len(pairs)
        save_state(st)
        if bi % progress_every == 0:
            el = time.time() - t0
            print(f"[{bi+1}/{len(batches)}] req={st['requests_used']} "
                  f"works={st['works']:,} pairs={st['pairs']:,} "
                  f"{el/60:.1f}min", flush=True)
    return st
