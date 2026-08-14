#!/usr/bin/env python3
"""Co-publication edges over the unified person_registry node set.

`collaborations` is keyed on people(person_id), so it can only express an
edge between two facility-directory rows. It structurally cannot represent
a site-personnel↔scholar link, which is exactly the question this table
answers: who staffing a catalogued facility publishes with the wider
field-wide scholar cohort.

Method
------
Every registry member with an openalex_id is queried once against
/works, and the authorship lists of the returned works are intersected
with the registry node set. An edge is written for each co-authoring pair
that both sit in the registry.

Two authors are the same person only when their OpenAlex author id
matches. Nothing here compares names.

Edges are undirected and stored once with canonical_id_a < canonical_id_b,
which qa.py asserts — storing both directions would double every
co-publication count.

Shared context on each edge:
  * shared_areas      — research_areas both members are linked to via
                        person_areas (through their people rows)
  * shared_facilities — facilities both members staff, via facility_personnel

Usage::

    python scripts/compute_registry_collaborations.py --dry-run
    python scripts/compute_registry_collaborations.py --export-parquet
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openalex_auth  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]
CACHE = ROOT / "data" / "raw" / "registry_collab" / "_state"
API = "https://api.openalex.org"
SLEEP = 0.05
PER_PAGE = 200
# Truncating an author's work list silently undercounts their strongest
# edges, and the authors who exceed a low cap are exactly the high-degree
# nodes whose centrality the blind-spot analysis depends on. Validating the
# highest-degree pairs against OpenAlex's own two-author filter in upstream
# cod-kmap, the ones whose endpoints exceeded a 600-work cap came back short
# while those under it were already exact; the worst measured case was
# Jeppesen<->Søndergaard, which read 212 against a true 261. (An earlier
# version of this comment gave a "4-23%" spread over "four of the top six"
# edges. The 261 figure is from upstream's validation run and stands; the
# spread is not reproducible from anything recorded, and its lower bound
# looks like a post-fix residual mixed in with pre-fix undercounts.
# Re-measure before quoting a range.) 6,000 covered every member of upstream
# cod-kmap's registry (most prolific: 5,177 works); re-check against this
# registry before trusting the cap if the harvest grows.
MAX_WORKS_PER_AUTHOR = 6000


def short(v) -> str | None:
    if not v:
        return None
    return str(v).rstrip("/").rsplit("/", 1)[-1] or None


def fetch_works(sess, oa_id: str) -> list[dict]:
    """All works for one author, as (year, [co-author ids]) tuples."""
    out, cursor = [], "*"
    while cursor and len(out) < MAX_WORKS_PER_AUTHOR:
        r = sess.get(f"{API}/works", params={
            "filter": f"author.id:{oa_id}",
            "select": "id,publication_year,authorships",
            "per_page": PER_PAGE, "cursor": cursor}, timeout=90)
        if not r.ok:
            print(f"  [warn] works {r.status_code} for {oa_id}", file=sys.stderr)
            break
        j = r.json()
        for w in j.get("results", []):
            ids = [short((a.get("author") or {}).get("id"))
                   for a in (w.get("authorships") or [])]
            out.append({"y": w.get("publication_year"),
                        "a": [i for i in ids if i]})
        cursor = (j.get("meta") or {}).get("next_cursor")
        time.sleep(SLEEP)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", action="store_true", default=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--export-parquet", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    openalex_auth.require_api_key()
    sess = openalex_auth.openalex_session()
    conn = duckdb.connect(str(args.db))

    members = conn.execute(
        "SELECT canonical_id, openalex_id, display_name FROM person_registry "
        "WHERE openalex_id IS NOT NULL AND openalex_id <> '' "
        "ORDER BY display_name").fetchall()
    by_oa = {oa: cid for cid, oa, _ in members}
    print(f"[graph] {len(members)} registry member(s) with an OpenAlex id")
    if args.limit:
        members = members[:args.limit]

    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / "author_works.ndjson"
    done: dict[str, list] = {}
    if args.resume and cache_file.exists():
        for line in cache_file.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["oa"]] = rec["w"]
        print(f"[graph] resumed {len(done)} author(s) from cache")

    todo = [m for m in members if m[1] not in done]
    with cache_file.open("a") as fh:
        for i, (cid, oa, name) in enumerate(todo, 1):
            works = fetch_works(sess, oa)
            done[oa] = works
            fh.write(json.dumps({"oa": oa, "w": works}) + "\n")
            fh.flush()
            if i % 25 == 0 or i == len(todo):
                print(f"  [graph] {i}/{len(todo)} authors fetched")

    # ── build edges ────────────────────────────────────────────────────
    edges: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"n": 0, "first": None, "last": None})
    for oa, works in done.items():
        cid_a = by_oa.get(oa)
        if not cid_a:
            continue
        for w in works:
            partners = {by_oa[i] for i in w["a"] if i in by_oa and by_oa[i] != cid_a}
            for cid_b in partners:
                key = (cid_a, cid_b) if cid_a < cid_b else (cid_b, cid_a)
                e = edges[key]
                e["n"] += 1
                y = w.get("y")
                if y:
                    e["first"] = y if e["first"] is None else min(e["first"], y)
                    e["last"] = y if e["last"] is None else max(e["last"], y)
    # Each shared work is seen once from each endpoint's own work list, so
    # the raw tally double-counts every edge whose both endpoints were
    # fetched. Halve it, rounding up for the case where only one endpoint
    # was in `done` (a --limit run).
    for e in edges.values():
        e["n"] = max(1, round(e["n"] / 2))

    print(f"[graph] {len(edges)} distinct co-publication edge(s)")

    # ── shared context ─────────────────────────────────────────────────
    areas = defaultdict(set)
    for cid, aid in conn.execute("""
            SELECT r.canonical_id, pa.area_id FROM person_registry r
            JOIN person_areas pa ON pa.person_id = r.person_id""").fetchall():
        areas[cid].add(aid)
    facs = defaultdict(set)
    for cid, fid in conn.execute("""
            SELECT r.canonical_id, fp.facility_id FROM person_registry r
            JOIN facility_personnel fp ON fp.person_id = r.person_id""").fetchall():
        facs[cid].add(fid)

    rows = []
    for (a, b), e in sorted(edges.items(), key=lambda kv: -kv[1]["n"]):
        sa = sorted(areas.get(a, set()) & areas.get(b, set()))
        sf = sorted(facs.get(a, set()) & facs.get(b, set()))
        rows.append([a, b, e["n"], e["first"], e["last"],
                     ",".join(sa) or None, ",".join(sf) or None])

    if rows:
        top = conn.execute("""
            SELECT ra.display_name, rb.display_name, ? AS n
            FROM person_registry ra, person_registry rb
            WHERE ra.canonical_id = ? AND rb.canonical_id = ?""",
            [rows[0][2], rows[0][0], rows[0][1]]).fetchone()
        if top:
            print(f"[graph] strongest edge: {top[0]} <-> {top[1]}  {top[2]} co-pubs")

    if args.dry_run:
        conn.close()
        return 0

    conn.execute("DELETE FROM registry_collaborations")
    if rows:
        conn.executemany(
            "INSERT INTO registry_collaborations (canonical_id_a, canonical_id_b, "
            "co_pub_count, first_year, last_year, shared_areas, shared_facilities) "
            "VALUES (?,?,?,?,?,?,?)", rows)
    print(f"[db] registry_collaborations {len(rows)} rows")

    if args.export_parquet:
        for base in PARQUET_OUT:
            base.mkdir(parents=True, exist_ok=True)
            out = base / "registry_collaborations.parquet"
            conn.execute(f"COPY registry_collaborations TO '{out}' (FORMAT PARQUET)")
            print(f"[parquet] wrote {out}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
