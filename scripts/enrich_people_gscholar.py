#!/usr/bin/env python3
"""Find Google Scholar profile IDs for people in lto.

Tiered approach (see docs/google_scholar_enrichment_plan.md):

  --source openalex  (default)
      For each person with an openalex_id, GET
      https://api.openalex.org/authors/<id>, read ids.scholar from the
      response, and write the user_id segment to
      people.google_scholar_id.
  --source orcid
      For each person with an orcid, GET
      https://pub.orcid.org/v3.0/<orcid>/external-identifiers, look
      for type=Scholar / 'Google Scholar' rows, then the record's
      researcher-urls ("Websites & social links", where most people put
      it) for a scholar.google.*/citations?user= link; write the user_id.
  --source homepage
      For each person with a homepage_url (their own profile or lab page,
      checked by the people loaders), fetch it and take the Scholar user
      id it links. Accepted only when the page links exactly one distinct
      Scholar id and names the person's family name; a lab or staff page
      linking several members' profiles is skipped. Review the hits
      (--dry-run) before writing: a page can link a co-author's profile.
  --source scholarly
      Use the scholarly package to scrape Google Scholar's author
      search with the person's name + affiliation. FRAGILE — Google
      blocks aggressive scraping; use proxies if scaling beyond ~40
      lookups. Not recommended for default runs.

Each id is written with google_scholar_source_url, the OpenAlex author or
ORCID record it was read from. An id that is not a 12-character Scholar
user id, or that another person already carries, is reported and skipped.

Idempotent: only writes when google_scholar_id is currently NULL,
unless --reverify is set. Re-run with the same source to fill in
people who acquired the upstream id since the last pass.

Usage::
    python scripts/enrich_people_gscholar.py --source openalex
    python scripts/enrich_people_gscholar.py --source orcid --batch 50
    python scripts/enrich_people_gscholar.py --source openalex --dry-run
"""
from __future__ import annotations

import argparse
import re
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

OA_AUTHOR = "https://api.openalex.org/authors/{id}"
SCHOLAR_ID = re.compile(r"^[A-Za-z0-9_-]{12}$")
ORCID_EID = "https://pub.orcid.org/v3.0/{orcid}/external-identifiers"
ORCID_URLS = "https://pub.orcid.org/v3.0/{orcid}/researcher-urls"
SCHOLAR_LINK = re.compile(r"scholar\.google\.[a-z.]+/citations\?(?:[^\"'<>\s]*?&(?:amp;)?)?user=([A-Za-z0-9_-]{12})")


def session(accept_json=True) -> requests.Session:
    """One session for both hosts.

    OpenAlex needs an API key; ORCID must not see it. The session from
    scripts/openalex_auth.py attaches the key only to api.openalex.org
    requests, so pub.orcid.org calls made through the same object stay
    unauthenticated.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import openalex_auth

    openalex_auth.require_api_key()
    return openalex_auth.openalex_session(accept_json=accept_json)


def parse_scholar_user_id(url_or_id: str | None) -> str | None:
    """Accept either a full Scholar URL or a bare user_id; return user_id."""
    if not url_or_id:
        return None
    s = str(url_or_id).strip()
    m = re.search(r"[?&]user=([^&#]+)", s)
    if m:
        return m.group(1) if SCHOLAR_ID.match(m.group(1)) else None
    # A bare id is the 12-character user= value.
    return s if SCHOLAR_ID.match(s) else None


def fetch_from_openalex(sess: requests.Session, openalex_id: str
                        ) -> str | None:
    short = openalex_id.split("/")[-1] if openalex_id else ""
    if not short:
        return None
    try:
        r = sess.get(OA_AUTHOR.format(id=short), timeout=20)
    except Exception as e:
        print(f"[warn] OpenAlex fetch failed for {short}: {e}")
        return None
    if r.status_code == 429:
        time.sleep(2)
        r = sess.get(OA_AUTHOR.format(id=short), timeout=20)
    if not r.ok:
        return None
    j = r.json()
    ids = (j.get("ids") or {})
    return parse_scholar_user_id(ids.get("scholar"))


def fetch_from_orcid(sess: requests.Session, orcid: str) -> str | None:
    try:
        r = sess.get(ORCID_EID.format(orcid=orcid), timeout=20)
    except Exception as e:
        print(f"[warn] ORCID fetch failed for {orcid}: {e}")
        return None
    if r.status_code == 429:
        time.sleep(2)
        r = sess.get(ORCID_EID.format(orcid=orcid), timeout=20)
    if not r.ok:
        return None
    j = r.json()
    eids = j.get("external-identifier", []) or []
    for e in eids:
        etype = (e.get("external-id-type") or "").lower()
        if etype in ("scholar", "google scholar"):
            url = (e.get("external-id-url") or {}).get("value") \
                or e.get("external-id-value")
            uid = parse_scholar_user_id(url)
            if uid:
                return uid
    r = sess.get(ORCID_URLS.format(orcid=orcid), timeout=20)
    if r.ok:
        for u in r.json().get("researcher-url", []) or []:
            url = (u.get("url") or {}).get("value") or ""
            if "scholar.google." in url:
                uid = parse_scholar_user_id(url)
                if uid:
                    return uid
    return None


def fetch_from_homepage(sess: requests.Session, url: str, name: str) -> str | None:
    """The one Scholar user id a person's own page links, or None."""
    try:
        r = sess.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (lto-catalogue)"})
    except Exception as e:
        print(f"[warn] homepage fetch failed for {url}: {e}")
        return None
    if not r.ok:
        return None
    ids = set(SCHOLAR_LINK.findall(r.text))
    family = (name or "").split()[-1].lower() if name else ""
    if len(ids) != 1 or not family or family not in r.text.lower():
        return None
    return ids.pop()


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="Deprecated alias of --catalog.")
    ap.add_argument("--source", choices=("openalex", "orcid", "homepage", "scholarly"),
                    default="openalex")
    ap.add_argument("--batch", type=int, default=0,
                    help="Max people to process this run (0 = all)")
    ap.add_argument("--reverify", action="store_true",
                    help="Re-check people who already have google_scholar_id.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        conn = lto_db.connect(read_only=args.dry_run, catalog=args.catalog,
                              data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    sess = session()

    where = "TRUE" if args.reverify else \
            "(google_scholar_id IS NULL OR length(google_scholar_id) = 0)"
    if args.source == "openalex":
        where += " AND openalex_id IS NOT NULL AND length(openalex_id) > 0"
    elif args.source == "orcid":
        where += " AND orcid IS NOT NULL AND length(orcid) > 0"
    elif args.source == "homepage":
        where += " AND homepage_url IS NOT NULL AND length(homepage_url) > 0"

    rows = conn.execute(f"""
        SELECT person_id, name, openalex_id, orcid, google_scholar_id, homepage_url
        FROM   people
        WHERE  {where}
        ORDER  BY name
    """).fetchall()
    if args.batch:
        rows = rows[: args.batch]
    print(f"[gscholar] processing {len(rows)} people via {args.source}"
          f"{'  (dry-run)' if args.dry_run else ''}")

    totals = {"hit": 0, "miss": 0, "errors": 0}
    # Hits are collected and written in one transaction after the loop,
    # so a run is one lake snapshot and no write waits on the network.
    found: list[tuple[str, str, str]] = []
    taken = {gs: pid for pid, gs in conn.execute(
        "SELECT person_id, google_scholar_id FROM people "
        "WHERE google_scholar_id IS NOT NULL").fetchall()}
    try:
        for i, (pid, name, oa, orcid, _existing, home) in enumerate(rows, 1):
            try:
                if args.source == "openalex":
                    gs = fetch_from_openalex(sess, oa)
                elif args.source == "orcid":
                    gs = fetch_from_orcid(sess, orcid)
                elif args.source == "homepage":
                    gs = fetch_from_homepage(sess, home, name)
                else:
                    # Tier 3 stub — see plan doc. We don't run scholarly
                    # by default because of Google rate-limit fragility.
                    print("[error] --source scholarly not implemented yet",
                          file=sys.stderr)
                    return 3
            except Exception as e:
                print(f"  [{i}/{len(rows)}] {name[:30]:30s}  ERROR: {e}")
                totals["errors"] += 1
                continue
            if gs and taken.get(gs, pid) != pid:
                print(f"  [{i}/{len(rows)}] {name[:30]:30s}  {gs} is already on "
                      f"{taken[gs]} — skipped (merge the two?)")
                totals["miss"] += 1
            elif gs:
                totals["hit"] += 1
                print(f"  [{i}/{len(rows)}] {name[:30]:30s}  ✓ {gs}")
                src = {"openalex": f"https://openalex.org/{(oa or '').split('/')[-1]}",
                       "orcid": f"https://orcid.org/{orcid}",
                       "homepage": home}[args.source]
                found.append((pid, gs, src))
                taken[gs] = pid
            else:
                totals["miss"] += 1
                print(f"  [{i}/{len(rows)}] {name[:30]:30s}  no scholar id")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print(f"\n[interrupted] after {len(found)} hits; writing those")

    print(f"[done] hit={totals['hit']}  miss={totals['miss']}  "
          f"errors={totals['errors']}")
    if found and not args.dry_run:
        with lto_db.transaction(
                conn, f"enrich_people_gscholar: {len(found)} Google Scholar "
                      f"ids via {args.source}"):
            lto_db.ensure_schema(conn)
            conn.execute("CREATE OR REPLACE TEMP TABLE _gs (person_id VARCHAR, "
                         "google_scholar_id VARCHAR, src VARCHAR)")
            conn.executemany("INSERT INTO _gs VALUES (?, ?, ?)", found)
            conn.execute("""
                UPDATE people SET google_scholar_id = s.google_scholar_id,
                                  google_scholar_source_url = s.src,
                                  updated_at = now()
                FROM   _gs s WHERE people.person_id = s.person_id
            """)
            lto_db.assert_integrity(conn, ["people"])
        print(f"[lake] wrote {len(found)} google_scholar_id values "
              f"(run export_parquet.py to publish)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
