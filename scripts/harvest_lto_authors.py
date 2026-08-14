#!/usr/bin/env python3
"""Harvest the addressable LTO-topic author population from OpenAlex.

Replaces the three-stage candidate/hydrate/measure pipeline that upstream
cod-kmap's build_community_scholars.py ran for the bulk case. That pipeline
grouped /works by author to find candidates, then re-fetched each author,
then spent ~3 more requests per author computing topical output. The
/authors endpoint filters on `topics.id` directly and returns everything
those three stages produced — ORCID, ROR-bearing institution,
summary_stats, and per-topic work counts — in one page of 200.

Measured upstream (cod-kmap, 2026-07-27) against its 15 resolved coastal
topics:

    topics.id:<15 topics>                     1,126,552 authors
    … + works_count:>9                          190,397
    … + works_count:>19,cited_by_count:>99       95,776

The ≥10-works floor is the default: below it OpenAlex author records are
dominated by disambiguation shards (see MIN_STUB_WORKS in upstream
cod-kmap's enrich_registry_identifiers.py) rather than researchers.

LTO's topic set (schema/vocab/lto_openalex_topics.csv) is much broader
than upstream's coastal set — ecology, hydrology, atmospheric science, … —
so an uncapped sweep can blow OpenAlex's 10k req/day quota. The
`--per-topic-cap N` option (new here; upstream has no equivalent) pages
each topic as its own filter and stops paging that topic after N kept
authors, keeping the pool bounded. With the cap unset (0) the harvest runs
upstream's single combined-filter sweep.

`lto_works_count` is summed from `topics[].count` on the author record, so
it costs no extra requests.

Everything harvested lands in `person_registry` with tier='archive'.
scripts/rank_person_registry.py then promotes a ranked core tier to
tier='core', and only that tier is exported to public/parquet for the
browser — a 190k-row parquet would make the site unusable.

Usage::

    python scripts/harvest_lto_authors.py --min-works 20 --max-authors 20000
    python scripts/harvest_lto_authors.py --per-topic-cap 2000
    python scripts/harvest_lto_authors.py --resume
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openalex_auth  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
TOPICS_CSV = ROOT / "schema" / "vocab" / "lto_openalex_topics.csv"
STATE = ROOT / "data" / "raw" / "lto_authors" / "_state"
API = "https://api.openalex.org"
PER_PAGE = 200
SLEEP = 0.05

SELECT = ("id,display_name,orcid,ids,works_count,cited_by_count,summary_stats,"
          "last_known_institutions,topics,counts_by_year")


def lto_topic_ids() -> list[str]:
    # The topic set is curated by the M5 operator before any harvest runs.
    # A missing or empty file must stop the run loudly: harvesting against
    # nothing would either error obscurely or silently match no one.
    if not TOPICS_CSV.exists():
        print(f"[error] {TOPICS_CSV.relative_to(ROOT)} is missing. Curate the "
              f"LTO topic set (columns: topic_id,label,notes) before "
              f"harvesting — this is the M5 operator step.", file=sys.stderr)
        raise SystemExit(2)
    with TOPICS_CSV.open() as fh:
        rows = list(csv.DictReader(l for l in fh if not l.startswith("#")))
    ids = sorted({r["topic_id"].strip() for r in rows
                  if r.get("topic_id", "").strip()})
    sentinels = [r for r in rows if r.get("topic_id", "").strip() == "RESOLVE"]
    if sentinels:
        print(f"[error] {len(sentinels)} unresolved RESOLVE sentinel(s) in "
              f"{TOPICS_CSV.name}; harvesting against them would silently "
              f"drop those topics.", file=sys.stderr)
        raise SystemExit(2)
    if not ids:
        print(f"[error] {TOPICS_CSV.relative_to(ROOT)} has no topic_id rows; "
              f"the LTO topic set must be curated before harvesting — this "
              f"is the M5 operator step.", file=sys.stderr)
        raise SystemExit(2)
    return ids


def short(v) -> str | None:
    if not v:
        return None
    return str(v).rstrip("/").rsplit("/", 1)[-1] or None


def flatten(a: dict, lto: set[str]) -> dict | None:
    stats = a.get("summary_stats") or {}
    insts = a.get("last_known_institutions") or []
    inst = insts[0] if insts else {}
    topics = a.get("topics") or []
    # OpenAlex lists a work under EVERY topic it carries, so summing
    # topics[].count over the LTO set counts a paper once per LTO topic it
    # touches — not once. In upstream cod-kmap, raw sums exceeded
    # works_count for 10,571 of 152,004 harvested authors, reaching a
    # nonsensical share of 3.0. The sum is still the best available signal
    # of LTO output volume, but it is an upper bound on distinct LTO
    # papers, so the share it feeds is clamped to 1.0 and named accordingly.
    lw_topic_hits = sum(t.get("count", 0) for t in topics
                        if short(t.get("id")) in lto)
    works = a.get("works_count") or 0
    lw = min(lw_topic_hits, works) if works else lw_topic_hits
    oa_id = short(a.get("id"))
    orcid = short(a.get("orcid"))
    # No OpenAlex id (and by construction no ORCID either) means the row
    # cannot satisfy qa.py's identifier requirement — lto never mints a
    # local id (upstream's codp: form does not exist here), so the caller
    # counts and reports these rather than inventing an identity.
    if not oa_id:
        return None
    years = [c.get("year") for c in (a.get("counts_by_year") or [])
             if c.get("works_count")]
    ids = a.get("ids") or {}
    recent = sum(c.get("works_count", 0) for c in (a.get("counts_by_year") or [])
                 if (c.get("year") or 0) >= date.today().year - 5)
    return dict(
        canonical_id=f"orcid:{orcid}" if orcid else f"openalex:{oa_id}",
        display_name=a.get("display_name") or "",
        orcid=orcid, openalex_id=oa_id,
        google_scholar_id=short(ids.get("scholar")) if ids.get("scholar") else None,
        homepage_url=ids.get("homepage") or None,
        affiliation=inst.get("display_name"),
        affiliation_ror=short(inst.get("ror")) if inst.get("ror") else None,
        affiliation_country=inst.get("country_code"),
        works_count=works or None, cited_by_count=a.get("cited_by_count"),
        h_index=stats.get("h_index"), i10_index=stats.get("i10_index"),
        two_yr_mean_citedness=stats.get("2yr_mean_citedness"),
        lto_works_count=lw or None,
        lto_share=round(lw / works, 4) if works else None,
        first_pub_year=min(years) if years else None,
        recent_works=recent,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--min-works", type=int, default=10)
    ap.add_argument("--min-lto-works", type=int, default=3,
                    help="drop authors whose LTO-topic output is below this; "
                         "the topic filter matches anyone with a single "
                         "LTO-topic paper")
    ap.add_argument("--max-authors", type=int, default=0, help="0 = no cap")
    ap.add_argument("--per-topic-cap", type=int, default=0,
                    help="0 = single combined-filter sweep (upstream "
                         "behaviour); N pages each topic separately and "
                         "stops a topic after N kept authors — LTO's broad "
                         "topic set can blow the 10k req/day quota uncapped")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    openalex_auth.require_api_key()
    sess = openalex_auth.openalex_session()
    topics = lto_topic_ids()
    lto = set(topics)
    flt = f"topics.id:{'|'.join(topics)},works_count:>{args.min_works - 1}"

    r = sess.get(f"{API}/authors", params={"filter": flt, "per_page": 1}, timeout=60)
    total = (r.json().get("meta") or {}).get("count", 0)
    print(f"[harvest] {total:,} authors match {len(topics)} LTO topics "
          f"with >= {args.min_works} works")

    STATE.mkdir(parents=True, exist_ok=True)
    out_file = STATE / "authors.ndjson"
    cursor_file = STATE / "cursor.txt"
    done_file = STATE / "topics_done.txt"
    seen: set[str] = set()
    if args.resume and out_file.exists():
        for line in out_file.read_text().splitlines():
            if line.strip():
                seen.add(json.loads(line)["openalex_id"])
        print(f"[harvest] resumed {len(seen):,} author(s) from cache")
    # The cursor checkpoint is tagged with the batch it belongs to
    # ("__all__" for the combined sweep, else a topic id) so a resume never
    # replays a cursor against the wrong filter.
    saved_key, saved_cursor = None, None
    if args.resume and cursor_file.exists():
        parts = cursor_file.read_text().split("\t", 1)
        if len(parts) == 2:
            saved_key, saved_cursor = parts[0], parts[1].strip()
    done: set[str] = set()
    if args.resume and done_file.exists():
        done = {l.strip() for l in done_file.read_text().splitlines()
                if l.strip()}

    # One batch per topic when --per-topic-cap is set, else upstream's
    # single combined filter. Deduping via `seen` makes the per-topic
    # sweep safe: an author matching several LTO topics is kept once.
    if args.per_topic_cap:
        batches = [(t, f"topics.id:{t},works_count:>{args.min_works - 1}")
                   for t in topics]
    else:
        batches = [("__all__", flt)]

    kept = len(seen)
    pages = 0
    no_id = 0
    stop = False
    with out_file.open("a") as fh:
        for bi, (key, bflt) in enumerate(batches, 1):
            if key in done:
                continue
            if args.per_topic_cap:
                print(f"  [harvest] topic {key} ({bi}/{len(batches)})")
            cursor = saved_cursor if saved_key == key else "*"
            batch_kept = 0
            while cursor:
                r = sess.get(f"{API}/authors", params={
                    "filter": bflt, "sort": "cited_by_count:desc",
                    "select": SELECT, "per_page": PER_PAGE, "cursor": cursor},
                    timeout=90)
                if not r.ok:
                    print(f"[warn] HTTP {r.status_code}; stopping", file=sys.stderr)
                    stop = True
                    break
                j = r.json()
                for a in j.get("results", []):
                    row = flatten(a, lto)
                    if row is None:
                        no_id += 1
                        continue
                    if row["openalex_id"] in seen:
                        continue
                    if (row["lto_works_count"] or 0) < args.min_lto_works:
                        continue
                    seen.add(row["openalex_id"])
                    fh.write(json.dumps(row) + "\n")
                    kept += 1
                    batch_kept += 1
                pages += 1
                cursor = (j.get("meta") or {}).get("next_cursor")
                cursor_file.write_text(f"{key}\t{cursor or ''}")
                if pages % 10 == 0:
                    fh.flush()
                    print(f"  [harvest] page {pages}, {kept:,} kept")
                if args.max_authors and kept >= args.max_authors:
                    print(f"  [harvest] reached --max-authors {args.max_authors:,}")
                    stop = True
                    break
                if args.per_topic_cap and batch_kept >= args.per_topic_cap:
                    print(f"  [harvest] topic {key}: reached --per-topic-cap "
                          f"{args.per_topic_cap:,}")
                    break
                time.sleep(SLEEP)
            if stop:
                break
            # Batch exhausted its cursor (or hit its per-topic cap): record
            # it so a --resume run skips straight past it.
            with done_file.open("a") as dfh:
                dfh.write(key + "\n")

    if no_id:
        print(f"[warn] skipped {no_id:,} author record(s) lacking both ORCID "
              f"and OpenAlex id; lto never mints local ids for them",
              file=sys.stderr)
    print(f"[harvest] {kept:,} author(s) with >= {args.min_lto_works} "
          f"LTO-topic works cached to {out_file.relative_to(ROOT)}")
    if args.dry_run:
        return 0

    # ── load into person_registry as tier='archive' ────────────────────
    conn = duckdb.connect(str(args.db))
    existing = {r[0] for r in conn.execute(
        "SELECT openalex_id FROM person_registry "
        "WHERE openalex_id IS NOT NULL").fetchall()}
    existing_orcid = {r[0] for r in conn.execute(
        "SELECT orcid FROM person_registry WHERE orcid IS NOT NULL").fetchall()}

    cols = ["canonical_id", "display_name", "orcid", "openalex_id",
            "google_scholar_id", "homepage_url", "affiliation",
            "affiliation_ror", "affiliation_country", "works_count",
            "cited_by_count", "h_index", "i10_index", "two_yr_mean_citedness",
            "lto_works_count", "lto_share", "first_pub_year",
            "is_scholar", "tier", "source", "source_url", "confidence",
            "retrieved_at"]
    today = date.today().isoformat()
    new_rows, prov, skipped = [], [], 0
    for line in out_file.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        # Never duplicate a human already in the registry. Both identifier
        # spaces are checked: the existing row may have been keyed on ORCID
        # while the harvest keyed on OpenAlex id, or the reverse. Merges
        # happen ONLY on ORCID or openalex_id equality — name similarity
        # never merges (rule inherited from three wrong-person incidents in
        # upstream cod-kmap).
        if d["openalex_id"] in existing or (d["orcid"] and d["orcid"] in existing_orcid):
            skipped += 1
            continue
        existing.add(d["openalex_id"])
        if d["orcid"]:
            existing_orcid.add(d["orcid"])
        new_rows.append([
            d["canonical_id"], d["display_name"], d["orcid"], d["openalex_id"],
            d["google_scholar_id"], d["homepage_url"], d["affiliation"],
            d["affiliation_ror"], d["affiliation_country"], d["works_count"],
            d["cited_by_count"], d["h_index"], d["i10_index"],
            d["two_yr_mean_citedness"], d["lto_works_count"],
            d["lto_share"], d["first_pub_year"],
            True, "archive", "openalex-harvest",
            f"{API}/authors/{d['openalex_id']}", "high", today])
        prov.append([d["canonical_id"], "openalex_id", d["openalex_id"],
                     "openalex-topic-harvest",
                     f"matched {len(topics)} LTO topics with "
                     f"{d['lto_works_count']} LTO-topic works",
                     f"{API}/authors/{d['openalex_id']}", "high", today])

    if new_rows:
        conn.executemany(
            f"INSERT INTO person_registry ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})", new_rows)
        conn.executemany(
            "INSERT INTO person_identity_source (canonical_id, field, value, "
            "method, evidence, source_url, confidence, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?)", prov)
    n = conn.execute("SELECT COUNT(*) FROM person_registry").fetchone()[0]
    print(f"[db] +{len(new_rows):,} new archive-tier rows "
          f"({skipped:,} already in the registry); person_registry now {n:,}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
