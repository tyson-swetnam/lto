#!/usr/bin/env python3
"""Fetch NSF awards for cod-kmap facilities and write to funding_events.

Uses NSF's Awards API (https://api.nsf.gov/services/v1/awards.json),
which is free, auth-less, and returns clean per-FY allocation breakdowns
in `fundsObligated` (e.g. ["FY 2020 = $1,200,000.00", ...]).

Resolution model
================

Each facility maps to ZERO OR MORE NSF awardee profiles. Two paths:

  * AUTO: if the facility's `parent_org` looks like an NSF awardee
    (university or independent research institute), we use it as the
    structured `awardeeName=` filter on the API. This handles:
      - WHOI, MBL, SIO, MBARI, Mote, Bigelow, etc. (parent_org IS the awardee)
      - University-hosted labs whose parent_org is the host university
        (BUT: this over-attributes — every NSF award to UCSB, not just SBC LTER's)

  * OVERRIDES (data/funding_overrides/nsf_recipient_overrides.csv):
    explicit per-facility filters. CSV columns:
        facility_id      — required
        awardee_name     — exact NSF awardeeName (multiple rows OK)
        program_match    — substring of fundProgramName (case-insensitive,
                           OR-combined across rows)
        title_match      — substring of title (case-insensitive)
        award_id         — exact award_id whitelist (skips API search)
        notes
    The script returns awards matching:
        (awardee in [overrides.awardee_name…])
        AND (overrides.program_match empty OR program contains any of them)
        AND (overrides.title_match empty OR title contains any of them)
        OR  (award_id in overrides.award_id_whitelist)

  * SKIP if neither AUTO nor OVERRIDES yields any candidate awardee.
    Federal units (sanctuaries, NPS, EPA NEP) usually have no NSF
    presence — they'll be picked up by the NOAA / agency-budget paths.

For each matching award we write one funding_events row per fiscal_year
listed in `fundsObligated`. event_id = hash(funder|facility|award|fy)
makes re-runs idempotent.

Usage::

    python scripts/fetch_funding_nsf.py
    python scripts/fetch_funding_nsf.py --limit 10
    python scripts/fetch_funding_nsf.py --facility-id <hash>
    python scripts/fetch_funding_nsf.py --start-fy 2015 --end-fy 2024
    python scripts/fetch_funding_nsf.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import hashlib
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
DEFAULT_OVERRIDES = ROOT / "data" / "funding_overrides" / "nsf_recipient_overrides.csv"
API = "https://api.nsf.gov/services/v1/awards.json"
PER_PAGE = 25  # NSF API caps at 25 per request

PRINT_FIELDS = ",".join([
    "id", "title", "fundsObligatedAmt", "estimatedTotalAmt",
    "startDate", "expDate", "awardeeName", "awardeeStateCode",
    "agency", "dirAbbr", "divAbbr", "fundProgramName", "primaryProgram",
    "piFirstName", "piLastName", "fundsObligated", "cfdaNumber",
])

NSF_FUNDER_NAME = "National Science Foundation"
NSF_FUNDER_TYPE = "federal"
NSF_FUNDER_COUNTRY = "US"
NSF_FUNDER_URL = "https://www.nsf.gov"

# Heuristic: which parent_org strings should we treat as auto-awardees?
# We're conservative — generic "Network" / "Consortium" / "Sanctuary"
# names rarely match NSF awardees and would explode the API.
AUTO_AWARDEE_HINTS = (
    "university", "college", "institut", "laborator", "observatory",
    "school of", "research center",
)
AUTO_AWARDEE_BLOCKLIST = (
    "lter network", "ioos", "neon", "ocean observatories initiative",
    "national park", "marine sanctuary", "estuarine research reserve",
    "national estuary program", "epa region", "noaa fisheries",
    "geological survey",  # "U.S. Geological Survey" never NSF-funded as awardee
)


def _hash(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=8).hexdigest()


def funder_id_for_nsf() -> str:
    return _hash(NSF_FUNDER_NAME.lower())


def event_id_for(funder_id: str, facility_id: str, award_id: str,
                 fiscal_year: int | None) -> str:
    return _hash(f"{funder_id}|{facility_id}|{award_id}|{fiscal_year or ''}")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "cod-kmap/0.1 (github.com/tyson-swetnam/cod-kmap; "
        "mailto:tswetnam@arizona.edu)"
    )
    return s


def load_overrides(path: Path) -> dict[str, dict]:
    """facility_id -> {awardees: [...], program_matches: [...],
                       title_matches: [...], award_ids: [...]}."""
    out: dict[str, dict] = {}
    if not path.exists():
        print(f"[overrides] none found at {path} (this is fine)")
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(
            (line for line in fh if not line.lstrip().startswith("#")),
        )
        for row in reader:
            fid = (row.get("facility_id") or "").strip()
            if not fid:
                continue
            entry = out.setdefault(fid, {
                "awardees": [], "program_matches": [],
                "title_matches": [], "award_ids": [],
            })
            for col, key in (("awardee_name", "awardees"),
                             ("program_match", "program_matches"),
                             ("title_match", "title_matches"),
                             ("award_id", "award_ids")):
                v = (row.get(col) or "").strip()
                if v and v not in entry[key]:
                    entry[key].append(v)
    print(f"[overrides] loaded {len(out)} facility-specific overrides")
    return out


def fetch_awards_by_awardee(sess: requests.Session, awardee: str,
                            start_fy: int, end_fy: int,
                            program_filter: str | None = None,
                            keyword_filter: str | None = None) -> list[dict]:
    """Page through NSF awards matching awardeeName (and optionally
    fundProgramName + keyword) — pushed as API filters so a noisy awardee
    like a major university doesn't return 1000+ off-topic awards.

    `keyword_filter` does a free-text search across title + abstract
    and is used to scope by sub-program when no exact fundProgramName
    is available (e.g. 'Bodega' inside UC Davis's portfolio)."""
    out: list[dict] = []
    offset = 1
    safety = 0
    while True:
        safety += 1
        if safety > 80:
            print(f"[warn] aborting fetch after 80 pages for awardee={awardee}")
            break
        # NSF Awards API quirk: multi-word values for awardeeName /
        # fundProgramName are silently ignored unless wrapped in
        # double quotes. Without the quotes the API returns 1000s of
        # off-topic awards (whichever happens to match the first
        # space-separated token), and `requests`'s default URL
        # encoding strips quotes only if you forget to embed them.
        params: dict[str, str | int] = {
            "printFields": PRINT_FIELDS,
            "rpp": PER_PAGE,
            "agency": "NSF",
            "awardeeName": f'"{awardee}"',
            "offset": offset,
        }
        if program_filter:
            params["fundProgramName"] = f'"{program_filter}"'
        if keyword_filter:
            params["keyword"] = f'"{keyword_filter}"'
        try:
            r = sess.get(API, params=params, timeout=30)
        except Exception as e:
            print(f"[warn] NSF fetch failed: {e}; retry once")
            time.sleep(2)
            try:
                r = sess.get(API, params=params, timeout=30)
            except Exception as e2:
                print(f"[error] NSF fetch failed twice: {e2}")
                return out
        if r.status_code == 429:
            time.sleep(5)
            continue
        if not r.ok:
            print(f"[warn] NSF {r.status_code} for awardee={awardee}: "
                  f"{r.text[:200]}")
            break
        try:
            page = r.json().get("response", {}).get("award", [])
        except Exception as e:
            print(f"[warn] NSF JSON decode failed: {e}")
            break
        if not page:
            break
        out.extend(page)
        if len(page) < PER_PAGE:
            break
        offset += PER_PAGE
        time.sleep(0.05)
    # Drop awards entirely outside [start_fy, end_fy].
    return [a for a in out if _award_overlaps_fy(a, start_fy, end_fy)]


def fetch_award_by_id(sess: requests.Session, award_id: str) -> dict | None:
    """Direct lookup when the override CSV pins a specific award_id."""
    params = {"printFields": PRINT_FIELDS, "id": award_id, "agency": "NSF"}
    try:
        r = sess.get(API, params=params, timeout=30)
    except Exception as e:
        print(f"[warn] NSF id lookup failed for {award_id}: {e}")
        return None
    if not r.ok:
        return None
    hits = r.json().get("response", {}).get("award", [])
    return hits[0] if hits else None


def _award_overlaps_fy(award: dict, start_fy: int, end_fy: int) -> bool:
    sy = _parse_year(award.get("startDate", ""))
    ey = _parse_year(award.get("expDate", ""))
    if sy is None and ey is None:
        return True  # keep ambiguous; per-FY filter applied later
    return (sy or 1900) <= end_fy and (ey or 2100) >= start_fy


def _parse_year(s: str) -> int | None:
    if not s:
        return None
    m = re.search(r"/(\d{4})$", s)
    return int(m.group(1)) if m else None


_FUNDS_RE = re.compile(r"FY\s*(\d{4})\s*=\s*\$?([\d,]+(?:\.\d+)?)")


def parse_funds_obligated(funds: list[str] | None) -> list[tuple[int, float]]:
    if not funds:
        return []
    out: list[tuple[int, float]] = []
    for entry in funds:
        m = _FUNDS_RE.search(str(entry))
        if not m:
            continue
        out.append((int(m.group(1)), float(m.group(2).replace(",", ""))))
    return out


def ensure_nsf_funder(conn) -> str:
    fid = funder_id_for_nsf()
    hit = conn.execute(
        "SELECT funder_id FROM funders WHERE funder_id = ?", [fid]
    ).fetchone()
    if hit:
        conn.execute(
            "UPDATE funders SET type = COALESCE(type, ?), "
            "country = COALESCE(country, ?), url = COALESCE(url, ?) "
            "WHERE funder_id = ?",
            [NSF_FUNDER_TYPE, NSF_FUNDER_COUNTRY, NSF_FUNDER_URL, fid],
        )
        return fid
    conn.execute(
        "INSERT INTO funders (funder_id, name, type, country, url) "
        "VALUES (?, ?, ?, ?, ?)",
        [fid, NSF_FUNDER_NAME, NSF_FUNDER_TYPE, NSF_FUNDER_COUNTRY, NSF_FUNDER_URL],
    )
    return fid


def _to_iso(mdy: str) -> str | None:
    if not mdy:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", mdy.strip())
    if not m:
        return None
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"


def write_award(conn, funder_id: str, facility_id: str, award: dict,
                start_fy: int, end_fy: int) -> int:
    award_id = (award.get("id") or "").strip()
    if not award_id:
        return 0
    title = (award.get("title") or "")[:500]
    program = (award.get("fundProgramName") or award.get("primaryProgram") or "")[:200]
    src_url = f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={award_id}"
    sd = award.get("startDate", "")
    ed = award.get("expDate", "")
    sy = _parse_year(sd)
    period_start = _to_iso(sd)
    period_end = _to_iso(ed)
    fy_amounts = parse_funds_obligated(award.get("fundsObligated"))
    if not fy_amounts:
        amt = float(award.get("fundsObligatedAmt") or 0)
        if amt and sy:
            fy_amounts = [(sy, amt)]
    if not fy_amounts:
        return 0

    inserted = 0
    for fy, amt in fy_amounts:
        if fy < start_fy or fy > end_fy:
            continue
        eid = event_id_for(funder_id, facility_id, award_id, fy)
        try:
            conn.execute("""
                INSERT INTO funding_events (
                    event_id, funder_id, facility_id,
                    amount_usd, amount_currency,
                    fiscal_year, period_start, period_end,
                    award_id, award_title, program, relation,
                    source, source_url, retrieved_at, confidence, notes
                )
                VALUES (?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?,
                        'grant', 'NSF Award Search', ?, current_date,
                        'high', NULL)
                ON CONFLICT (event_id) DO NOTHING
            """, [eid, funder_id, facility_id, amt, fy,
                  period_start, period_end, award_id, title, program, src_url])
            inserted += 1
        except Exception as e:
            print(f"[warn] insert {award_id}/{fy} failed: {e}")
    return inserted


def _auto_awardee(parent: str) -> str | None:
    """Decide whether to treat parent_org as an NSF awardee."""
    if not parent:
        return None
    p = parent.lower()
    if any(b in p for b in AUTO_AWARDEE_BLOCKLIST):
        return None
    if any(h in p for h in AUTO_AWARDEE_HINTS):
        return parent
    return None


def _award_matches_filters(award: dict, ov: dict) -> bool:
    if ov.get("award_ids") and award.get("id") in ov["award_ids"]:
        return True
    pm = [m.lower() for m in (ov.get("program_matches") or [])]
    tm = [m.lower() for m in (ov.get("title_matches") or [])]
    if pm:
        prog = (award.get("fundProgramName") or
                award.get("primaryProgram") or "").lower()
        if not any(p in prog for p in pm):
            return False
    if tm:
        title = (award.get("title") or "").lower()
        if not any(t in title for t in tm):
            return False
    return True


def process_facility(conn, sess: requests.Session, funder_id: str,
                     facility: dict, overrides: dict, start_fy: int,
                     end_fy: int, dry: bool) -> dict:
    fid = facility["facility_id"]
    parent = facility.get("parent_org") or ""

    ov = overrides.get(fid, {})
    awardees: list[str] = list(ov.get("awardees") or [])
    if not awardees:
        auto = _auto_awardee(parent)
        if auto:
            awardees = [auto]
    if not awardees and not ov.get("award_ids"):
        return {"awards": 0, "inserted": 0, "queries": 0, "skipped": True}

    seen_award_ids: set[str] = set()
    candidate_awards: list[dict] = []

    # Direct award_id whitelist (skips API search).
    for awid in (ov.get("award_ids") or []):
        a = fetch_award_by_id(sess, awid)
        if a and a.get("id") not in seen_award_ids:
            seen_award_ids.add(a["id"])
            candidate_awards.append(a)

    # Awardee-name pulls. If overrides provided program_match or
    # title_match strings we push them to the API (one query per
    # awardee × program × keyword combination) so we don't drag back
    # every award from a 1000-award university.
    program_filters = list(ov.get("program_matches") or [None])
    keyword_filters = list(ov.get("title_matches") or [None])
    queries = 0
    for aw in awardees:
        for prog in program_filters:
            for kw in keyword_filters:
                queries += 1
                for a in fetch_awards_by_awardee(
                    sess, aw, start_fy, end_fy, prog, kw,
                ):
                    if a.get("id") and a["id"] not in seen_award_ids:
                        seen_award_ids.add(a["id"])
                        candidate_awards.append(a)

    # Apply program/title filters from override CSV.
    matched = [a for a in candidate_awards if _award_matches_filters(a, ov)]

    inserted = 0
    if not dry:
        for a in matched:
            inserted += write_award(conn, funder_id, fid, a, start_fy, end_fy)
    return {
        "awards": len(matched),
        "candidates": len(candidate_awards),
        "inserted": inserted,
        "queries": queries,
        "skipped": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    ap.add_argument("--start-fy", type=int, default=2015)
    ap.add_argument("--end-fy",   type=int, default=2024)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--facility-id", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-done", action="store_true",
                    help="Skip facilities that already have at least one "
                         "NSF Award Search row in funding_events. Lets a "
                         "pipeline that timed out resume cheaply.")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))
    sess = session()
    funder_id = ensure_nsf_funder(conn)
    overrides = load_overrides(args.overrides)

    rows = conn.execute("""
        SELECT facility_id, canonical_name, acronym, parent_org, country
        FROM facilities
        WHERE country IN ('US','USA') OR country IS NULL
        ORDER BY canonical_name
    """).fetchall()
    facilities = [
        {"facility_id": r[0], "canonical_name": r[1], "acronym": r[2],
         "parent_org": r[3], "country": r[4]}
        for r in rows
    ]
    if args.facility_id:
        facilities = [f for f in facilities if f["facility_id"] == args.facility_id]
    if args.skip_done:
        done = {r[0] for r in conn.execute(
            "SELECT DISTINCT facility_id FROM funding_events "
            "WHERE source = 'NSF Award Search'"
        ).fetchall()}
        before = len(facilities)
        facilities = [f for f in facilities if f["facility_id"] not in done]
        print(f"[skip-done] dropped {before - len(facilities)} already-fetched facilities")
    if args.limit:
        facilities = facilities[: args.limit]
    print(f"[nsf] FY{args.start_fy}-FY{args.end_fy} for {len(facilities)} facilities"
          f"{'  (dry-run)' if args.dry_run else ''}")

    totals = {"awards": 0, "inserted": 0, "queries": 0, "processed": 0,
              "skipped": 0}
    for i, fac in enumerate(facilities, 1):
        try:
            r = process_facility(conn, sess, funder_id, fac, overrides,
                                 args.start_fy, args.end_fy, args.dry_run)
        except Exception as e:
            print(f"  [{i}/{len(facilities)}] {fac['acronym']:10s} "
                  f"{fac['canonical_name'][:50]:50s}  ERROR: {e}")
            continue
        if r.get("skipped"):
            totals["skipped"] += 1
            continue
        totals["awards"] += r["awards"]
        totals["inserted"] += r["inserted"]
        totals["queries"] += r["queries"]
        totals["processed"] += 1
        print(f"  [{i}/{len(facilities)}] {(fac['acronym'] or ''):10s} "
              f"{fac['canonical_name'][:50]:50s}  q={r['queries']:2d}  "
              f"matched={r['awards']:4d}  wrote={r['inserted']:4d}")

    print(f"[done] processed={totals['processed']}  "
          f"skipped={totals['skipped']}  queries={totals['queries']}  "
          f"matched_awards={totals['awards']}  inserted={totals['inserted']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
