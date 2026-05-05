#!/usr/bin/env python3
"""Find Google Scholar profile IDs for people in cod-kmap.

Tiered approach (see docs/google_scholar_enrichment_plan.md):

  --source openalex  (default)
      For each person with an openalex_id, GET
      https://api.openalex.org/authors/<id>, read ids.scholar from the
      response, and write the user_id segment to
      people.google_scholar_id.
  --source orcid
      For each person with an orcid, GET
      https://pub.orcid.org/v3.0/<orcid>/external-identifiers, look
      for type=Scholar / 'Google Scholar' rows, write the user_id.
  --source scholarly
      Use the scholarly package to scrape Google Scholar's author
      search with the person's name + affiliation. FRAGILE — Google
      blocks aggressive scraping; use proxies if scaling beyond ~40
      lookups. Not recommended for default runs.

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

import duckdb
try:
    import requests
except ImportError:
    print("[error] pip install requests --break-system-packages", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]

OA_AUTHOR = "https://api.openalex.org/authors/{id}"
ORCID_EID = "https://pub.orcid.org/v3.0/{orcid}/external-identifiers"


def session(accept_json=True) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "cod-kmap/0.1 (github.com/tyson-swetnam/cod-kmap; "
        "mailto:tswetnam@arizona.edu)"
    )
    if accept_json:
        s.headers["Accept"] = "application/json"
    return s


def parse_scholar_user_id(url_or_id: str | None) -> str | None:
    """Accept either a full Scholar URL or a bare user_id; return user_id."""
    if not url_or_id:
        return None
    s = str(url_or_id).strip()
    m = re.search(r"[?&]user=([^&]+)", s)
    if m:
        return m.group(1)
    # Bare ids are 12 alphanumerics ending in AAAA-ish; we don't
    # over-validate, just return the trimmed string.
    return s if len(s) <= 50 else None


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
    return None


def export_parquet(conn):
    for base in PARQUET_OUT:
        base.mkdir(parents=True, exist_ok=True)
        out = base / "people.parquet"
        conn.execute(f"COPY people TO '{out}' (FORMAT PARQUET)")
        print(f"[parquet] wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--source", choices=("openalex", "orcid", "scholarly"),
                    default="openalex")
    ap.add_argument("--batch", type=int, default=0,
                    help="Max people to process this run (0 = all)")
    ap.add_argument("--reverify", action="store_true",
                    help="Re-check people who already have google_scholar_id.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))
    sess = session()

    where = "TRUE" if args.reverify else \
            "(google_scholar_id IS NULL OR length(google_scholar_id) = 0)"
    if args.source == "openalex":
        where += " AND openalex_id IS NOT NULL AND length(openalex_id) > 0"
    elif args.source == "orcid":
        where += " AND orcid IS NOT NULL AND length(orcid) > 0"

    rows = conn.execute(f"""
        SELECT person_id, name, openalex_id, orcid, google_scholar_id
        FROM   people
        WHERE  {where}
        ORDER  BY name
    """).fetchall()
    if args.batch:
        rows = rows[: args.batch]
    print(f"[gscholar] processing {len(rows)} people via {args.source}"
          f"{'  (dry-run)' if args.dry_run else ''}")

    totals = {"hit": 0, "miss": 0, "errors": 0}
    for i, (pid, name, oa, orcid, _existing) in enumerate(rows, 1):
        try:
            if args.source == "openalex":
                gs = fetch_from_openalex(sess, oa)
            elif args.source == "orcid":
                gs = fetch_from_orcid(sess, orcid)
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
        if gs:
            totals["hit"] += 1
            print(f"  [{i}/{len(rows)}] {name[:30]:30s}  ✓ {gs}")
            if not args.dry_run:
                conn.execute(
                    "UPDATE people SET google_scholar_id = ?, "
                    "updated_at = now() WHERE person_id = ?",
                    [gs, pid],
                )
        else:
            totals["miss"] += 1
            print(f"  [{i}/{len(rows)}] {name[:30]:30s}  no scholar id")
        time.sleep(0.05)

    print(f"[done] hit={totals['hit']}  miss={totals['miss']}  "
          f"errors={totals['errors']}")
    if not args.dry_run:
        export_parquet(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
