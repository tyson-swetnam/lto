#!/usr/bin/env python3
"""Probe each facility's homepage for a staff/people/leadership page and
extract candidate (name, role) pairs for manual review.

This is a conservative crawler — it fetches at most a handful of URLs
per facility, applies a shallow regex-plus-BeautifulSoup heuristic to
identify name-role pairs, and writes candidates to a CSV. It never
writes directly to the DB; a human should eyeball the output and copy
verified rows into `data/seed/facility_personnel_seed.csv`.

Strategy per facility:

  1. GET facility.url. Skip if 4xx/5xx/timeout.
  2. Look for links labelled "people", "staff", "leadership",
     "directory", "team", "about us". Dedupe, follow each (at most 3).
  3. On each page, scan for patterns like::

       <h2>John Doe</h2>
       <p class="title">Director</p>

     or::

       <tr><td>John Doe</td><td>Director</td></tr>

     via tag-adjacency heuristics. Only keep name-lines that contain a
     plausible human-name pattern (capitalised first word + second word)
     AND a keyword-matching role in the nearby text (Director, Chief
     Scientist, PI, Manager, etc.).
  4. Write (facility_acronym, facility_name_like, person_name, role,
     title, source_url, confidence='low') rows to
     `data/seed/scraped_personnel_candidates.csv`.

Confidence is deliberately 'low' on every output row — the scraper
makes mistakes on complex layouts and you should review before
loading. Use it as a first draft.

Dependencies::

    pip install requests beautifulsoup4

Usage::

    python scripts/scrape_facility_personnel.py
    python scripts/scrape_facility_personnel.py --limit 10
    python scripts/scrape_facility_personnel.py --unresolved-only
        # skip facilities that already have an openalex-seeded person
    python scripts/scrape_facility_personnel.py --out data/seed/scraped_personnel_candidates.csv

A progress checkpoint at data/seed/.scrape_progress.json lets
interrupted runs resume.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[error] pip install requests beautifulsoup4 --break-system-packages",
          file=sys.stderr)
    raise

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
DEFAULT_OUT = ROOT / "data" / "seed" / "scraped_personnel_candidates.csv"
PROGRESS = ROOT / "data" / "seed" / ".scrape_progress.json"

# Link-text patterns that point at a staff / people / leadership page.
STAFF_LINK_PATTERNS = re.compile(
    r"\b(people|staff|leadership|directory|team|faculty|"
    r"administration|our[\s\-]?people|about[\s\-]?us|contact[\s\-]?us|"
    r"researchers?|scientists?|members?)\b",
    re.IGNORECASE,
)

# Role keywords we'll accept as valid `role` values. Order matters —
# longer / more-specific matches win.
ROLE_KEYWORDS = [
    ("President & CEO", r"\b(president\s*&\s*ceo|president\s+and\s+ceo)\b"),
    ("President & Director", r"\b(president\s*&\s*director|president\s+and\s+director)\b"),
    ("Executive Director", r"\bexecutive\s+director\b"),
    ("Deputy Director", r"\bdeputy\s+director\b"),
    ("Associate Director", r"\bassociate\s+director\b"),
    ("Assistant Director", r"\bassistant\s+director\b"),
    ("Research Coordinator", r"\bresearch\s+coordinator\b"),
    ("Education Coordinator", r"\beducation\s+coordinator\b"),
    ("Stewardship Coordinator", r"\bstewardship\s+coordinator\b"),
    ("Chief Scientist", r"\bchief\s+scientist\b"),
    ("Principal Investigator", r"\b(principal\s+investigator|lead\s+pi|co[-\s]?pi)\b"),
    ("Program Manager", r"\bprogram\s+manager\b"),
    ("Reserve Manager", r"\breserve\s+manager\b"),
    ("Superintendent", r"\bsuperintendent\b"),
    ("Dean", r"\bdean\b"),
    ("Director", r"\bdirector\b"),
    ("Head Administrator", r"\bhead\s+administrator\b"),
    ("Professor", r"\bprofessor\b"),
    ("Research Scientist", r"\bresearch\s+scientist\b"),
    ("Staff Scientist", r"\bstaff\s+scientist\b"),
    ("Senior Scientist", r"\bsenior\s+scientist\b"),
    ("Postdoctoral Researcher", r"\bpost[-\s]?doctoral?\s+researcher\b"),
]

# Loose "looks like a name" regex: two capitalised tokens, optionally
# with a middle initial or accented characters.
NAME_RE = re.compile(
    r"\b([A-Z][\w\.\-']{1,30}\s+"           # first name
    r"(?:[A-Z]\.\s+|[A-Z]\w{0,20}\s+)?"     # optional middle name / initial
    r"[A-Z][\w\.\-']{1,30})\b"              # last name
)


def ua(email: str = "") -> dict:
    return {
        "User-Agent": (
            "cod-kmap-scraper/0.1 "
            f"(github.com/tyson-swetnam/cod-kmap; mailto:{email or 'unset'})"
        )
    }


def fetch(url: str, sess: requests.Session, timeout: int = 15) -> str | None:
    try:
        r = sess.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ct = r.headers.get("content-type", "")
        if "text/html" not in ct and "application/xhtml" not in ct:
            return None
        return r.text
    except requests.RequestException:
        return None


def find_staff_links(base_url: str, html: str, limit: int = 3) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        text = (a.get_text(" ", strip=True) or "") + " " + (a["href"] or "")
        if STAFF_LINK_PATTERNS.search(text):
            u = urljoin(base_url, a["href"])
            # Skip anchors and mailto: / javascript: links
            if u.startswith(("mailto:", "javascript:", "#")):
                continue
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
            if len(out) >= limit:
                break
    return out


def classify_role(context: str) -> str | None:
    for canonical, pattern in ROLE_KEYWORDS:
        if re.search(pattern, context, re.IGNORECASE):
            return canonical
    return None


def extract_candidates(html: str, url: str) -> list[dict]:
    """Return a list of {name, role, title, context} candidates. Every
    candidate is a name that appeared in text adjacent to a role
    keyword in the same block-level element."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    # Remove script/style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    out: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    # Scan "card-like" blocks: li / dt / figure / div / article / tr
    for block in soup.find_all(["li", "dt", "dd", "figure", "div", "article",
                                 "section", "tr", "p"]):
        text = block.get_text(" ", strip=True)
        if not text or len(text) > 600:
            continue
        role = classify_role(text)
        if not role:
            continue
        name_match = NAME_RE.search(text)
        if not name_match:
            continue
        name = name_match.group(1)
        # Skip suspicious matches — these are common false positives.
        if any(bad in name.lower() for bad in (
            "united states", "national science", "ocean science",
            "national park", "marine laboratory", "institute of",
        )):
            continue
        key = (name.lower(), role.lower())
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        # Grab the surrounding text as the 'title' if it contains
        # more detail than just the role word.
        title = re.sub(r"\s+", " ", text).strip()
        if len(title) > 180:
            title = title[:177] + "…"
        out.append({"name": name, "role": role,
                    "title": title, "source_url": url})
    return out


def load_progress() -> dict:
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_progress(data: dict) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(data, indent=2, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--unresolved-only", action="store_true",
                    help="Skip facilities that already have 2+ seeded people")
    ap.add_argument("--force-refresh", action="store_true")
    ap.add_argument("--email", default="",
                    help="Your contact email for the polite User-Agent header")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    # read_only=True avoids taking the exclusive lock so the scraper
    # can run alongside an in-flight enrichment or seed pass. If an
    # older DuckDB still complains about the flag, fall back to the
    # regular connect() after catching the error.
    try:
        conn = duckdb.connect(str(args.db), read_only=True)
    except (TypeError, duckdb.Error):
        conn = duckdb.connect(str(args.db))
    facilities = conn.execute("""
        SELECT f.facility_id, f.canonical_name, f.acronym, f.url,
               (SELECT COUNT(*) FROM facility_personnel fp
                WHERE fp.facility_id = f.facility_id) AS n_existing
        FROM facilities f
        WHERE f.url IS NOT NULL AND f.url != ''
        ORDER BY f.canonical_name
    """).fetchall()
    rows = [{"facility_id": r[0], "canonical_name": r[1], "acronym": r[2],
             "url": r[3], "n_existing": r[4]} for r in facilities]
    if args.unresolved_only:
        rows = [r for r in rows if r["n_existing"] < 2]
    if args.limit:
        rows = rows[: args.limit]

    progress = {} if args.force_refresh else load_progress()
    sess = requests.Session()
    sess.headers.update(ua(args.email))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Append mode — the CSV can grow across multiple runs.
    new_file = not args.out.exists()
    with args.out.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow([
                "facility_acronym", "facility_name_like", "person_name",
                "role", "title", "is_key_personnel", "source",
                "source_url", "confidence", "notes",
            ])

        found = 0
        for i, f in enumerate(rows, 1):
            fid = f["facility_id"]
            if fid in progress and progress[fid].get("status") == "done":
                continue
            print(f"[{i}/{len(rows)}] {f['canonical_name'][:56]:<56} {f['url']}")
            home_html = fetch(f["url"], sess)
            if not home_html:
                print("    [miss: homepage unreachable]")
                progress[fid] = {"status": "home-miss"}
                continue
            links = [f["url"]] + find_staff_links(f["url"], home_html)
            seen_url = set()
            cands = []
            for url in links:
                if url in seen_url:
                    continue
                seen_url.add(url)
                html = home_html if url == f["url"] else fetch(url, sess)
                if not html:
                    continue
                cands.extend(extract_candidates(html, url))
                time.sleep(0.3)  # be polite
            print(f"    candidates={len(cands)}")
            # Write rows — always low confidence; reviewer promotes to
            # 'medium'/'high' after verification.
            key_roles = {"Director", "Deputy Director", "Associate Director",
                         "Chief Scientist", "President & CEO",
                         "Executive Director", "Dean"}
            for c in cands:
                facility_key_acr = f["acronym"] or ""
                # LTER/NERR acronyms are ambiguous — use name_like fallback
                if facility_key_acr in ("LTER", "NERR", "NEP"):
                    facility_key_acr = ""
                    name_like = f["canonical_name"]
                else:
                    name_like = ""
                w.writerow([
                    facility_key_acr, name_like, c["name"], c["role"],
                    c["title"], str(c["role"] in key_roles).lower(),
                    "facility-scrape", c["source_url"], "low",
                    "scraped — verify before loading",
                ])
                found += 1
            progress[fid] = {"status": "done", "candidates": len(cands)}
            if i % 10 == 0:
                save_progress(progress)

        save_progress(progress)
        print(f"\n[done] wrote {found} candidate rows to {args.out}")
        print("       review the CSV, copy verified rows into "
              "data/seed/facility_personnel_seed.csv, "
              "then `python scripts/load_facility_personnel.py "
              "--csv data/seed/facility_personnel_seed.csv`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
