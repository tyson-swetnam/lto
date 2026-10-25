#!/usr/bin/env python3
"""Enrich rows in `people` with OpenAlex metadata.

OpenAlex (openalex.org) requires an API key on every request; set
OPENALEX_API_KEY in the environment. (It used to be auth-less with an
OPENALEX_EMAIL "polite pool"; that no longer applies, and mailto must
not be sent alongside a key.) For each person we resolve to an OpenAlex
Author record via (in priority order):

  1. Existing openalex_id on the row
  2. ORCID (`/authors?filter=orcid:0000-…`)
  3. Name + institutional affiliation search
     (`/authors?search=<name>&filter=last_known_institution.display_name.search:<inst>`)

For each match we then fetch up to N publications, co-authors, and
concepts (research topics), writing into:

  * people.openalex_id                           (update)
  * people.research_interests                   (FILL-ONLY, see below)
  * publications                                (upsert by doi/openalex_id)
  * authorship                                  (link person ↔ pub)
  * person_areas                                (weighted links to
                                                 research_areas; we map
                                                 OpenAlex concepts to
                                                 our area_id slugs via
                                                 data/vocab_crosswalk/
                                                 openalex_to_area.csv
                                                 when present, else we
                                                 just skip topic writes)

research_interests is fill-only. It is written only when the stored
value is empty, or is itself an earlier OpenAlex-generated list (see
ri_overwritable). A value with a non-OpenAlex research_interests_source_url
or a hand-written value is never touched. The 2026-10-23 run overwrote 122
curated values (e.g. "scaling of watershed rainfall-runoff response; …")
with generic x_concepts ("Hydrology (agriculture), Environmental science,
Geology, …"); this rule exists so that cannot recur. When it writes, the
value is the author's top-5 OpenAlex topics by count (x_concepts only as a
fallback) and research_interests_source_url is the author's OpenAlex URL.

Adapted from the UNM knowledge-map enrichment pipeline pattern.

Usage::

    python scripts/enrich_people_openalex.py --dry-run           # no writes
    python scripts/enrich_people_openalex.py --limit 10          # small batch
    python scripts/enrich_people_openalex.py --people-csv data/seed/arid_people.csv
    python scripts/enrich_people_openalex.py --catalog /tmp/scratch/cat.sqlite

Environment:
    OPENALEX_API_KEY=…                    # required

Dependencies:
    pip install requests
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
import openalex_auth  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.openalex.org"
UA = "lto/0.2 (+https://github.com/tyson-swetnam/lto)"


def session() -> requests.Session:
    """Keyed OpenAlex session.

    OpenAlex requires an API key on every request now, so the old
    OPENALEX_EMAIL polite-pool convention no longer applies; the key
    handling lives in scripts/openalex_auth.py and is shared with the
    other five scripts that call the API.
    """
    openalex_auth.require_api_key()
    return openalex_auth.openalex_session(user_agent=UA)


# (person_id, openalex_id) pairs a review found to be the wrong person, or
# a person merged with others. The roster lives in
# wipe_misattributed_identifiers.py (BAD_BY_ID); an author on it is never
# attached to that person again, whichever route resolved it.
from wipe_misattributed_identifiers import bad_openalex_pairs  # noqa: E402

BAD_PAIRS = bad_openalex_pairs()


def _is_bad(person: dict, author: dict) -> bool:
    short = (author.get("id") or "").rstrip("/").split("/")[-1].upper()
    if (person["person_id"], short) in BAD_PAIRS:
        print(f"    [blocked] {person.get('name')}: {short} is on the "
              "misattribution roster (wipe_misattributed_identifiers.py)")
        return True
    return False


# --- research_interests: fill-only -------------------------------------
#
# Earlier runs stored ", ".join(x_concepts[:5]) with NO source URL, so a
# previous OpenAlex value cannot be told apart by provenance alone. It is
# recognised by shape instead: no source URL, an openalex_id on the row
# (this script always set both together; the wipe scripts NULL both), and
# 1-5 ", "-separated terms that are each, case-sensitively, an OpenAlex
# concept display name. Against lake snapshot 1 (before the 2026-10-23
# run) that matches 68 rows, all generic concept lists, and none of the
# 27 hand-written source-less values on rows with an openalex_id
# ("ichthyoplankton, SEAMAP, larval fish ecology Gulf of Mexico", …):
# curated keywords are lower-case phrases, concept names are
# capitalised. New writes carry the author's OpenAlex URL as their
# source, so from now on provenance alone identifies them.
OPENALEX_HOSTS = {"openalex.org", "api.openalex.org"}
# OpenAlex's 19 level-0 concepts: x_concepts always leads with these, so
# they are recognised even if publication_topics holds no concept rows.
LEVEL0_CONCEPTS = {
    "Art", "Biology", "Business", "Chemistry", "Computer science", "Economics",
    "Engineering", "Environmental science", "Geography", "Geology", "History",
    "Materials science", "Mathematics", "Medicine", "Philosophy", "Physics",
    "Political science", "Psychology", "Sociology",
}


def is_openalex_url(url: str | None) -> bool:
    from urllib.parse import urlparse                  # noqa: PLC0415
    host = (urlparse((url or "").strip()).hostname or "").lower()
    return host in OPENALEX_HOSTS


def load_concept_vocab(conn) -> set[str]:
    """Every OpenAlex concept display name the lake has seen."""
    rows = conn.execute(
        "SELECT DISTINCT concept_name FROM publication_topics "
        "WHERE kind = 'concept' AND concept_name IS NOT NULL").fetchall()
    return LEVEL0_CONCEPTS | {r[0] for r in rows}


def looks_like_concept_list(value: str, vocab: set[str]) -> bool:
    terms = value.split(", ")
    return 1 <= len(terms) <= 5 and all(t in vocab for t in terms)


def ri_overwritable(person: dict, vocab: set[str]) -> tuple[bool, str]:
    """May this run write research_interests for `person`? (ok, reason)."""
    value = (person.get("research_interests") or "").strip()
    src = (person.get("research_interests_source_url") or "").strip()
    if not value:
        return True, "empty"
    if src:
        if is_openalex_url(src):
            return True, "previous OpenAlex value (source URL)"
        return False, f"curated (source {src})"
    if (person.get("openalex_id") or "").strip() and looks_like_concept_list(value, vocab):
        return True, "previous OpenAlex concept list (no source URL)"
    return False, "curated (no source URL, not an OpenAlex concept list)"


def interests_from_author(author: dict) -> str | None:
    """Top-5 OpenAlex topics by count; legacy x_concepts only if the author
    record has no topics. x_concepts are level-0/1 concepts ("Biology,
    Environmental science, Geography") and say little about a person.
    Topics are joined with '; ' because a topic name may contain a comma."""
    topics = [t for t in (author.get("topics") or []) if t.get("display_name")]
    if topics:
        topics.sort(key=lambda t: -(t.get("count") or 0))  # stable on ties
        return "; ".join(t["display_name"] for t in topics[:5])
    names = [c.get("display_name") for c in (author.get("x_concepts") or [])[:5]
             if c.get("display_name")]
    return ", ".join(names) or None


def resolve_author(sess: requests.Session, person: dict) -> dict | None:
    """Try openalex_id → ORCID → name+institution. Returns the author JSON
    or None. An author on the misattribution roster for this person is
    never returned."""
    oa_id = (person.get("openalex_id") or "").strip()
    if oa_id:
        r = sess.get(f"{API}/authors/{oa_id}")
        if r.ok:
            return None if _is_bad(person, r.json()) else r.json()

    orcid = (person.get("orcid") or "").strip()
    if orcid:
        r = sess.get(f"{API}/authors",
                     params={"filter": f"orcid:{orcid}", "per_page": 1})
        if r.ok:
            hits = r.json().get("results", [])
            if hits:
                return None if _is_bad(person, hits[0]) else hits[0]

    # Name-only resolution is DELIBERATELY DISABLED. It used to fall back
    # to /authors?search=<name>&per_page=1, which returns the OpenAlex
    # author with that name who has the most publications globally —
    # almost always a prolific medical doctor when our coastal scientist
    # shares a name with one. That created the 2026-04-26 incident where
    # >50 cod-kmap people displayed "Medicine, Internal medicine" research
    # interests in the People view because their openalex_id pointed at
    # an MD instead. See scripts/wipe_medicine_attributions.py for the
    # cleanup that fixed it.
    #
    # If a person has no openalex_id and no ORCID, they stay un-enriched.
    # Add their openalex_id by hand to data/seed/openalex_institution_overrides.csv
    # (or to data/seed/orcid_resolution_log.csv with a verified ORCID) and
    # re-run this script.
    return None


def fetch_works(sess: requests.Session, author_oa_id: str,
                max_records: int = 100) -> list[dict]:
    """Fetch up to `max_records` publications for this OpenAlex author.
    Uses cursor pagination at OpenAlex's maximum page size (200): every
    list request costs one credit of the daily allowance whatever its
    size, so 50-record pages cost 4x the credits for the same works."""
    out: list[dict] = []
    cursor = "*"
    while cursor and len(out) < max_records:
        r = sess.get(f"{API}/works", params={
            "filter": f"authorships.author.id:{author_oa_id}",
            "per_page": min(200, max_records - len(out)),
            "cursor": cursor,
        })
        if not r.ok:
            print(f"[warn] works fetch {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        out.extend(data.get("results", []))
        cursor = data.get("meta", {}).get("next_cursor")
        time.sleep(0.1)   # be polite even in the polite pool
    return out[:max_records]


def _short_concept_id(raw: str) -> str | None:
    """OpenAlex returns full URLs (https://openalex.org/T10102) for ids.
    We strip the prefix so the same identifier is reusable in joins
    against the OpenAlex API and against analyst-edited crosswalk
    CSVs (which write the bare id, not the URL)."""
    if not raw:
        return None
    raw = str(raw)
    # Topics:   https://openalex.org/T10102           -> T10102
    # Concepts: https://openalex.org/C2778805511      -> C2778805511
    # Keywords: https://openalex.org/keywords/citation -> keywords/citation
    if "/" in raw:
        # take the last 1 or 2 segments; topics/concepts last 1, keywords last 2
        parts = raw.rstrip("/").split("/")
        if "keywords" in parts:
            i = parts.index("keywords")
            return "/".join(parts[i:i + 2])
        return parts[-1]
    return raw


# Writes are staged in TEMP tables while the loop talks to OpenAlex and
# land in the lake in one transaction at the end of the run (one
# snapshot). TEMP tables live outside the lake, so staging them is not a
# lake write. Lookups read the lake and the stage together, so a paper
# staged for one author is reused, not re-inserted, for a co-author.
STAGE_DDL = [
    # ri_before / ri_src_before: the values ri_overwritable() judged. The
    # write only lands if the row still holds them at commit time, so an
    # edit made while this run was talking to the API is not overwritten.
    "CREATE OR REPLACE TEMP TABLE _stage_people "
    "(person_id VARCHAR, openalex_id VARCHAR, research_interests VARCHAR, "
    "research_interests_source_url VARCHAR, ri_before VARCHAR, "
    "ri_src_before VARCHAR)",
]
# Only the columns staged below: merge_upsert inserts every column the
# stage shares with the target, so a staged created_at (NULL) would
# override the column's DEFAULT CURRENT_TIMESTAMP. Created through
# lto_db.create_temp_like (explicit DDL), never an empty CTAS.
STAGE_LIKE = [
    ("_stage_publications",
     "SELECT publication_id, doi, title, pub_year, pub_type, journal, cited_by_count, "
     "openalex_id, url, source, retrieved_at FROM publications"),
    ("_stage_authorship",
     "SELECT person_id, publication_id, raw_name, 0 AS _seq FROM authorship"),
    ("_stage_topics",
     "SELECT publication_id, concept_id, concept_name, score, level, kind, source, "
     "0 AS _seq FROM publication_topics"),
]
_seq = 0


def _next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def write_stage(conn) -> dict:
    """Apply the staged writes to the lake. Call inside transaction().

    ON CONFLICT DO NOTHING (authorship, publication_topics) becomes an
    insert-only MERGE where the first staged row wins, as before.
    """
    # research_interests is fill-only: a staged value is non-NULL only when
    # ri_overwritable() allowed it, and it lands only if the row still holds
    # the value that was judged.
    ri_ok = ("NULLIF(s.research_interests, '') IS NOT NULL "
             "AND people.research_interests IS NOT DISTINCT FROM s.ri_before "
             "AND people.research_interests_source_url IS NOT DISTINCT FROM s.ri_src_before")
    n_ri = lto_db.scalar(conn, f"SELECT count(*) FROM people JOIN _stage_people s "
                               f"ON people.person_id = s.person_id WHERE {ri_ok}")
    conn.execute(f"""
        UPDATE people SET openalex_id = s.openalex_id,
               research_interests = CASE WHEN {ri_ok} THEN s.research_interests
                                         ELSE people.research_interests END,
               research_interests_source_url =
                   CASE WHEN {ri_ok} THEN s.research_interests_source_url
                        ELSE people.research_interests_source_url END,
               updated_at = now()
        FROM   _stage_people s WHERE people.person_id = s.person_id
    """)
    out = {"people": lto_db.scalar(conn, "SELECT count(*) FROM _stage_people"),
           "research_interests": n_ri}
    out["publications"] = lto_db.merge_upsert(
        conn, "publications", ["publication_id"], "_stage_publications",
        insert_only=True)
    out["authorship"] = lto_db.merge_upsert(
        conn, "authorship", ["person_id", "publication_id"], "_stage_authorship",
        insert_only=True, order_by="_seq")
    out["publication_topics"] = lto_db.merge_upsert(
        conn, "publication_topics", ["publication_id", "concept_id"],
        "_stage_topics", insert_only=True, order_by="_seq")
    lto_db.assert_integrity(conn, ["people", "publications", "authorship",
                                   "publication_topics"])
    return out


def upsert_publication_topics(conn, pub_id: str, work: dict) -> int:
    """Stage OpenAlex concepts + topics + keywords for a publication.
    Idempotent: staged rows go in insert-only, so re-runs are cheap.
    Returns the number of rows staged."""
    rows: list[tuple] = []
    for c in (work.get("concepts") or []):
        cid = _short_concept_id(c.get("id"))
        name = c.get("display_name")
        if not (cid and name):
            continue
        rows.append((pub_id, cid, name, c.get("score"), c.get("level"),
                     "concept", "openalex"))
    for t in (work.get("topics") or []):
        tid = _short_concept_id(t.get("id"))
        name = t.get("display_name")
        if not (tid and name):
            continue
        rows.append((pub_id, tid, name, t.get("score"), None,
                     "topic", "openalex"))
    for k in (work.get("keywords") or []):
        kid = _short_concept_id(k.get("id"))
        name = k.get("display_name")
        if not (kid and name):
            continue
        rows.append((pub_id, kid, name, k.get("score"), None,
                     "keyword", "openalex"))
    if not rows:
        return 0
    written = 0
    for r in rows:
        try:
            conn.execute(
                """
                INSERT INTO _stage_topics (
                    publication_id, concept_id, concept_name,
                    score, level, kind, source, _seq
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [*r, _next_seq()],
            )
            written += 1
        except Exception as e:
            # A bad value (e.g. a score that won't cast). Log + skip so
            # one bad row doesn't kill the rest of the publication.
            print(f"[topics] skip {pub_id}/{r[1]}: {e}")
    return written


# OpenAlex work types that are not publications. "libguides" are library
# research-guide web pages; OpenAlex attaches them to whichever author
# shares the librarian's name (167 of them landed on one nursing
# professor's record), so they are never written.
SKIP_WORK_TYPES = {"libguides"}


def upsert_publication(conn, work: dict) -> str | None:
    if work.get("type") in SKIP_WORK_TYPES:
        return None
    oa = work.get("id", "")
    doi = (work.get("doi") or "").replace("https://doi.org/", "").strip() or None
    pub_id = (oa.split("/")[-1] if oa else (doi or ""))
    if not pub_id:
        return None
    # Look up an existing row by *either* publication_id OR doi. OpenAlex
    # regularly assigns two distinct Work ids to the same DOI (e.g. a
    # preprint and its peer-reviewed version, or two database snapshots
    # of the same paper). We use the first row we find and reuse its
    # publication_id for the authorship link so the second insert
    # doesn't trip publications.doi UNIQUE and crash the whole author's
    # enrichment run. Rows staged earlier in this run count as existing.
    # The row whose publication_id matches is preferred over a DOI hit.
    known = ("(SELECT publication_id, doi, cited_by_count FROM publications "
             "UNION ALL SELECT publication_id, doi, cited_by_count "
             "FROM _stage_publications)")
    if doi:
        hit = conn.execute(
            f"SELECT publication_id, cited_by_count FROM {known} "
            "WHERE publication_id = ? OR doi = ? "
            "ORDER BY publication_id = ? DESC LIMIT 1",
            [pub_id, doi, pub_id],
        ).fetchone()
    else:
        hit = conn.execute(
            f"SELECT publication_id, cited_by_count FROM {known} "
            "WHERE publication_id = ? LIMIT 1",
            [pub_id],
        ).fetchone()
    if hit and hit[0] != pub_id:
        # Existing row found via DOI; reuse its id for authorship.
        return hit[0]
    existing = (hit[1],) if hit else None
    title    = work.get("title")
    year     = work.get("publication_year")
    pub_type = work.get("type")
    journal  = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
    cbc      = work.get("cited_by_count") or 0
    url      = (work.get("primary_location") or {}).get("landing_page_url")
    if existing is None:
        conn.execute(
            """
            INSERT INTO _stage_publications (
                publication_id, doi, title, pub_year, pub_type,
                journal, cited_by_count, openalex_id, url, source, retrieved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_date)
            """,
            [pub_id, doi, title, year, pub_type, journal, cbc,
             oa or None, url, "openalex"],
        )
    # existing row case: skip the UPDATE.
    #
    # This was forced by the old native DuckDB file, which refused to
    # UPDATE a row any FK pointed at. The lake has no such block, but
    # the first write is already factually correct (same OpenAlex
    # data, minutes apart), so the refresh is still skipped and we
    # just fall through to the authorship INSERT.
    return pub_id


def enrich_person(conn, sess: requests.Session, person: dict,
                  max_pubs: int, dry: bool, vocab: set[str] | None = None) -> dict:
    result = {"person_id": person["person_id"], "works_found": 0, "upserted": 0}
    author = resolve_author(sess, person)
    if not author:
        return result
    author_oa = author["id"]
    author_oa_short = author_oa.split("/")[-1]
    interests = interests_from_author(author)
    ri_ok, why = ri_overwritable(person, vocab or LEVEL0_CONCEPTS)
    result["research_interests"] = "fill" if (ri_ok and interests) else "keep"
    if interests and ri_ok:
        print(f"    [interests] fill ({why}): {interests}")
    elif interests:
        print(f"    [interests] keep, {why}")
    staged_ri = interests if ri_ok else None
    if not dry:
        conn.execute(
            "INSERT INTO _stage_people VALUES (?, ?, ?, ?, ?, ?)",
            [person["person_id"], author_oa_short, staged_ri,
             f"https://openalex.org/{author_oa_short}" if staged_ri else None,
             person.get("research_interests"),
             person.get("research_interests_source_url")],
        )

    works = fetch_works(sess, author_oa, max_pubs)
    result["works_found"] = len(works)
    result["topics_written"] = 0
    if dry:
        return result
    for w in works:
        pid = upsert_publication(conn, w)
        if not pid:
            continue
        conn.execute(
            """
            INSERT INTO _stage_authorship (person_id, publication_id, raw_name, _seq)
            VALUES (?, ?, ?, ?)
            """,
            [person["person_id"], pid, person["name"], _next_seq()],
        )
        # Write OpenAlex topics/concepts/keywords for this work. We do
        # this *every* time we see the publication (not just on first
        # insert) because OpenAlex topic scores update over time and
        # we'd rather refresh than miss the new ones; the insert-only
        # merge keeps re-runs cheap when nothing has changed.
        result["topics_written"] += upsert_publication_topics(conn, pid, w)
        result["upserted"] += 1
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="Deprecated alias of --catalog.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Max people to process (0 = all)")
    ap.add_argument("--max-pubs", type=int, default=100,
                    help="Max publications per person")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--people-csv", type=Path, default=None,
                    help="Only process people whose name is in this CSV's `name` "
                         "column (e.g. data/seed/arid_people.csv). Without it every "
                         "person is re-fetched, which refreshes the whole catalogue.")
    args = ap.parse_args()

    try:
        conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    sess = session()
    if not args.dry_run:
        for ddl in STAGE_DDL:
            conn.execute(ddl)
        for name, like in STAGE_LIKE:
            lto_db.create_temp_like(conn, name, like)

    # .fetchall() + manual dict build is more portable across DuckDB
    # versions than .fetchdf() (pandas bridge varies) and avoids a
    # hard pandas dependency on the user's machine.
    rows = conn.execute(
        "SELECT person_id, name, orcid, openalex_id, research_interests, "
        "research_interests_source_url FROM people ORDER BY name"
    ).fetchall()
    people = [
        {"person_id": r[0], "name": r[1], "orcid": r[2], "openalex_id": r[3],
         "research_interests": r[4], "research_interests_source_url": r[5]}
        for r in rows
    ]
    vocab = load_concept_vocab(conn)
    if args.people_csv:
        import csv                                        # noqa: PLC0415
        with args.people_csv.open(newline="") as fh:
            wanted = {(r.get("name") or "").strip().lower() for r in csv.DictReader(fh)}
        people = [p for p in people if p["name"].strip().lower() in wanted]
    if args.limit:
        people = people[: args.limit]
    print(f"[enrich] processing {len(people)} people"
          f"{'  (dry-run)' if args.dry_run else ''}")

    totals = {"works_found": 0, "upserted": 0, "topics": 0, "skipped": 0,
              "ri_fill": 0}
    try:
        for i, p in enumerate(people, 1):
            try:
                r = enrich_person(conn, sess, p, args.max_pubs, args.dry_run, vocab)
                totals["ri_fill"] += r.get("research_interests") == "fill"
                totals["works_found"] += r["works_found"]
                totals["upserted"] += r["upserted"]
                totals["topics"] += r.get("topics_written", 0)
                if not r["works_found"]:
                    totals["skipped"] += 1
                print(f"  [{i}/{len(people)}] {p['name']}  "
                      f"works={r['works_found']}  wrote={r['upserted']}  "
                      f"topics+={r.get('topics_written', 0)}")
            except Exception as e:
                print(f"  [{i}/{len(people)}] {p['name']}  ERROR: {e}")
                totals["skipped"] += 1
    except KeyboardInterrupt:
        print("\n[interrupted] writing what was staged so far")

    print(f"[done] works_found={totals['works_found']}  "
          f"upserted={totals['upserted']}  topics={totals['topics']}  "
          f"skipped={totals['skipped']}  "
          f"research_interests_fill={totals['ri_fill']}")
    if not args.dry_run:
        with lto_db.transaction(
                conn, f"enrich_people_openalex: {len(people)} people, "
                      f"max-pubs {args.max_pubs}"
                      + (f", from {args.people_csv.name}" if args.people_csv else "")):
            out = write_stage(conn)
        print(f"[lake] people={out['people']}  "
              f"research_interests={out['research_interests']}  "
              + "  ".join(f"{t}={out[t]}" for t in
                          ("publications", "authorship", "publication_topics"))
              + "  (run export_parquet.py to publish)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
