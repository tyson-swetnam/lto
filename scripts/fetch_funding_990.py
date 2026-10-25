#!/usr/bin/env python3
"""Fetch IRS Form 990 totals for cod-kmap nonprofit facilities.

Pulls per-fiscal-year total revenue + total functional expenses from
ProPublica's Nonprofit Explorer API (free, auth-less). Each filing
becomes one funding_events row tagged with relation='annual-revenue-990'
and a self-funder identifier so it doesn't get summed alongside per-grant
rows when computing per-funder totals.

Why 990 totals matter:

Most cod-kmap "nonprofit" facilities are National Estuary Programs hosted
by state/local agencies — those don't file their own 990s. But ~10
facilities (Mote Marine Lab, New England Aquarium, Monterey Bay Aquarium,
Surfrider, EDF, TNC, Schmidt Ocean Inst, Packard Foundation, Moore
Foundation, ...) DO file 990s and the totals expose the orgs's *full*
revenue picture: federal grants + state grants + foundation gifts +
membership fees + admission + endowment income + investment returns.

We tag the 990 rows with `relation='annual-revenue-990'` so SQL queries
that compute per-funder totals can exclude them, but a "what's this org's
total annual budget?" query has the answer.

Resolution:

  1. AUTO: search ProPublica by facility canonical_name. Take the top
     hit when state matches the facility's state and rev > $100k.
  2. OVERRIDE: data/funding_overrides/propublica_ein_overrides.csv
     pins the exact EIN per facility — needed when:
       * the 990-filer is the foundation's parent org (Monterey Bay
         Aquarium → Monterey Bay Aquarium Foundation, EIN 944210123)
       * search returns multiple near-matches
       * the facility is part of a larger org's 990 (no separate filing)
  3. SKIP if neither yields a hit.

Usage::

    python scripts/fetch_funding_990.py
    python scripts/fetch_funding_990.py --limit 5
    python scripts/fetch_funding_990.py --facility-id <hash>
    python scripts/fetch_funding_990.py --start-fy 2015 --end-fy 2024
    python scripts/fetch_funding_990.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

try:
    import requests
except ImportError:
    print("[error] pip install requests --break-system-packages", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OVERRIDES = ROOT / "data" / "funding_overrides" / "propublica_ein_overrides.csv"
API_SEARCH = "https://projects.propublica.org/nonprofits/api/v2/search.json"
API_ORG = "https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"

FUNDER_NAME = "Self-reported (Form 990)"
FUNDER_TYPE = "self"
FUNDER_URL = "https://projects.propublica.org/nonprofits/"


def _hash(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=8).hexdigest()


def funder_id_990() -> str:
    return _hash(FUNDER_NAME.lower())


def event_id_for(funder_id: str, facility_id: str, ein: str,
                 fiscal_year: int) -> str:
    return _hash(f"{funder_id}|{facility_id}|{ein}|{fiscal_year}|990")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "cod-kmap/0.1 (github.com/tyson-swetnam/cod-kmap; "
        "mailto:tswetnam@arizona.edu)"
    )
    return s


# ---------------------------------------------------------------------------
# Lake writes. Rows are buffered in memory while the API is walked and land
# in one lake snapshot per FLUSH_EVERY facilities, plus a final one (also
# when the run dies), so a run that times out keeps what it fetched and
# --skip-done resumes from there. A dry run opens the lake read-only and
# never flushes.
# ---------------------------------------------------------------------------

FLUSH_EVERY = 25
EVENT_COLS = (
    "event_id", "funder_id", "facility_id", "amount_usd", "amount_currency",
    "fiscal_year", "period_start", "period_end", "award_id", "award_title",
    "program", "relation", "source", "source_url", "retrieved_at",
    "confidence", "notes",
)


class LakeBuffer:
    """funders and funding_events rows waiting for the next flush()."""

    def __init__(self) -> None:
        self.events: list[tuple] = []
        # funder_id -> (name, type, country, url)
        self.funders: dict[str, tuple] = {}

    def add_event(self, **cols) -> None:
        self.events.append(tuple(cols.get(c) for c in EVENT_COLS))


def flush(conn, buf: LakeBuffer, message: str) -> None:
    """Write the buffer as one snapshot; the old per-row INSERT ... ON
    CONFLICT (event_id) DO NOTHING is an insert-only MERGE (first row
    staged for a repeated event_id wins, as the first INSERT did)."""
    if not buf.events and not buf.funders:
        return
    stats = None
    with lto_db.transaction(conn, message):
        if buf.funders:
            conn.execute(
                "CREATE OR REPLACE TEMP TABLE _stage_funders (funder_id VARCHAR, "
                "name VARCHAR, type VARCHAR, country VARCHAR, url VARCHAR)")
            conn.executemany("INSERT INTO _stage_funders VALUES (?, ?, ?, ?, ?)",
                             [(fid, *v) for fid, v in buf.funders.items()])
            lto_db.merge_upsert(conn, "funders", ["funder_id"], "_stage_funders",
                                insert_only=True)
            conn.execute("DROP TABLE _stage_funders")
        if buf.events:
            lto_db.create_temp_like(
                conn, "_stage_events",
                f"SELECT {', '.join(EVENT_COLS)}, 0::BIGINT AS _seq FROM funding_events")
            conn.executemany(
                f"INSERT INTO _stage_events VALUES "
                f"({', '.join(['?'] * (len(EVENT_COLS) + 1))})",
                [(*e, i) for i, e in enumerate(buf.events)])
            stats = lto_db.merge_upsert(conn, "funding_events", ["event_id"],
                                        "_stage_events", insert_only=True,
                                        order_by="_seq")
            conn.execute("DROP TABLE _stage_events")
        lto_db.assert_integrity(conn, ["funders", "funding_events"])
    print(f"[lake] {message}"
          + (f"  (staged={stats['source_rows']} new={stats['inserted']} "
             f"already-present={stats['matched']})" if stats else ""))
    buf.events.clear()
    buf.funders.clear()


def load_overrides(path: Path) -> dict[str, dict]:
    """facility_id -> {ein: str, notes: str, skip: bool}."""
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
            ein = (row.get("ein") or "").strip()
            skip = (row.get("skip") or "").strip().lower() in ("1", "true", "yes", "y")
            out[fid] = {"ein": ein, "notes": (row.get("notes") or "").strip(),
                        "skip": skip}
    print(f"[overrides] loaded {len(out)} 990 EIN overrides "
          f"({sum(1 for v in out.values() if v['skip'])} marked skip)")
    return out


def search_by_name(sess: requests.Session, name: str,
                   state: str | None = None) -> list[dict]:
    """Search ProPublica by name. State match boosts confidence."""
    try:
        r = sess.get(API_SEARCH, params={"q": name}, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[warn] search failed for {name!r}: {e}")
        return []
    hits = r.json().get("organizations", [])
    if state:
        # Prefer same-state hits; keep others as fallback.
        same_state = [h for h in hits if (h.get("state") or "").upper() == state.upper()]
        if same_state:
            return same_state
    return hits


def fetch_org(sess: requests.Session, ein: str) -> dict | None:
    try:
        r = sess.get(API_ORG.format(ein=ein), timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[warn] org fetch failed for EIN {ein}: {e}")
        return None
    return r.json()


def ensure_self_funder(buf: LakeBuffer) -> str:
    """Queue the self-funder row; flush() inserts it only if absent."""
    fid = funder_id_990()
    buf.funders[fid] = (FUNDER_NAME, FUNDER_TYPE, "US", FUNDER_URL)
    return fid


def write_filings(buf: LakeBuffer, funder_id: str, facility: dict, ein: str,
                  filings: list[dict], start_fy: int, end_fy: int,
                  dry: bool) -> int:
    if dry or not filings:
        return 0
    fid = facility["facility_id"]
    inserted = 0
    src_url_template = (
        "https://projects.propublica.org/nonprofits/organizations/{ein}"
    )
    src_url = src_url_template.format(ein=ein)
    for f in filings:
        fy = f.get("tax_prd_yr")
        if not fy or fy < start_fy or fy > end_fy:
            continue
        rev = float(f.get("totrevenue") or 0)
        exp = float(f.get("totfuncexpns") or 0)
        if rev <= 0:
            continue
        eid = event_id_for(funder_id, fid, ein, fy)
        notes = (
            f"ein={ein}; total_expenses_usd={int(exp)}; "
            f"pdf={f.get('pdf_url') or ''}"
        )[:500]
        buf.add_event(
            event_id=eid, funder_id=funder_id, facility_id=fid,
            amount_usd=rev, amount_currency="USD", fiscal_year=fy,
            award_id=f"EIN-{ein}-FY{fy}",
            award_title="Form 990 total revenue",
            program="Form 990 (annual filing)",
            relation="annual-revenue-990",
            source="ProPublica Nonprofit Explorer",
            source_url=src_url, retrieved_at=date.today(),
            confidence="high", notes=notes)
        inserted += 1
    return inserted


def process_facility(buf: LakeBuffer, sess: requests.Session, funder_id: str,
                     facility: dict, overrides: dict,
                     start_fy: int, end_fy: int, dry: bool) -> dict:
    fid = facility["facility_id"]
    canonical = facility["canonical_name"]

    ov = overrides.get(fid, {})
    if ov.get("skip"):
        return {"hit": False, "filings": 0, "inserted": 0, "skipped": True}

    ein = ov.get("ein") or ""
    candidates: list[str] = []
    if ein:
        candidates = [ein]
    else:
        # Auto-search by name. We don't have facility.state — peek at
        # locations via SQL would be cleaner, but for now we trust the
        # top hit's state if it has revenue (>$100k). Skip if nothing.
        hits = search_by_name(sess, canonical, None)
        for h in hits[:5]:
            heid = (h.get("ein") or "")
            if isinstance(heid, int):
                heid = f"{heid:09d}"
            if heid:
                candidates.append(heid)

    org = None
    chosen_ein = None
    for c in candidates:
        # ProPublica EINs are usually 9 digits; ensure zero-padded.
        c_str = f"{int(c):09d}" if str(c).isdigit() else str(c)
        org = fetch_org(sess, c_str)
        if org and org.get("organization", {}).get("name"):
            chosen_ein = c_str
            break
    if not org or not chosen_ein:
        return {"hit": False, "filings": 0, "inserted": 0, "skipped": False}

    filings = org.get("filings_with_data", [])
    inserted = write_filings(buf, funder_id, facility, chosen_ein,
                             filings, start_fy, end_fy, dry)
    return {"hit": True, "ein": chosen_ein,
            "org_name": org.get("organization", {}).get("name"),
            "filings": len(filings), "inserted": inserted, "skipped": False}


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    ap.add_argument("--start-fy", type=int, default=2015)
    ap.add_argument("--end-fy",   type=int, default=2024)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--facility-id", type=str, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-done", action="store_true",
                    help="Skip facilities that already have a 990 row.")
    args = ap.parse_args()

    try:
        conn = lto_db.connect(read_only=args.dry_run, catalog=args.catalog,
                              data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    sess = session()
    buf = LakeBuffer()
    funder_id = ensure_self_funder(buf)
    overrides = load_overrides(args.overrides)

    rows = conn.execute("""
        SELECT facility_id, canonical_name, acronym, parent_org, country,
               facility_type
        FROM facilities
        WHERE country IN ('US','USA') OR country IS NULL
        ORDER BY canonical_name
    """).fetchall()
    facilities = [
        {"facility_id": r[0], "canonical_name": r[1], "acronym": r[2],
         "parent_org": r[3], "country": r[4], "facility_type": r[5]}
        for r in rows
    ]
    if args.facility_id:
        facilities = [f for f in facilities if f["facility_id"] == args.facility_id]
    else:
        # Default scope: nonprofits + foundations only. Other facility
        # types (federal, state, university-marine-lab) don't file 990s.
        facilities = [
            f for f in facilities
            if f["facility_type"] in ("nonprofit", "foundation")
        ]
    if args.skip_done:
        done = {r[0] for r in conn.execute(
            "SELECT DISTINCT facility_id FROM funding_events "
            "WHERE source = 'ProPublica Nonprofit Explorer'"
        ).fetchall()}
        before = len(facilities)
        facilities = [f for f in facilities if f["facility_id"] not in done]
        print(f"[skip-done] dropped {before - len(facilities)} already-fetched")
    if args.limit:
        facilities = facilities[: args.limit]
    print(f"[990] FY{args.start_fy}-FY{args.end_fy} for {len(facilities)} facilities"
          f"{'  (dry-run)' if args.dry_run else ''}")

    totals = {"hit": 0, "skipped": 0, "no_match": 0, "inserted": 0}
    # Checkpoint: one snapshot per FLUSH_EVERY facilities, plus the rest
    # in `finally` (a crash or Ctrl-C keeps what was fetched).
    span = f"FY{args.start_fy}-FY{args.end_fy}"
    first = 1
    try:
        for i, fac in enumerate(facilities, 1):
            if not args.dry_run and i > first and (i - 1) % FLUSH_EVERY == 0:
                flush(conn, buf, f"fetch_funding_990: {span}, facilities "
                                 f"{first}-{i - 1} of {len(facilities)}")
                first = i
            try:
                r = process_facility(buf, sess, funder_id, fac, overrides,
                                     args.start_fy, args.end_fy, args.dry_run)
            except Exception as e:
                print(f"  [{i}/{len(facilities)}] {(fac['acronym'] or ''):10s} "
                      f"{fac['canonical_name'][:50]:50s}  ERROR: {e}")
                continue
            if r.get("skipped"):
                totals["skipped"] += 1
                print(f"  [{i}/{len(facilities)}] {(fac['acronym'] or ''):10s} "
                      f"{fac['canonical_name'][:50]:50s}  SKIPPED (override)")
                continue
            if not r.get("hit"):
                totals["no_match"] += 1
                print(f"  [{i}/{len(facilities)}] {(fac['acronym'] or ''):10s} "
                      f"{fac['canonical_name'][:50]:50s}  no 990 match")
                continue
            totals["hit"] += 1
            totals["inserted"] += r["inserted"]
            print(f"  [{i}/{len(facilities)}] {(fac['acronym'] or ''):10s} "
                  f"{fac['canonical_name'][:50]:50s}  EIN={r['ein']}  "
                  f"filings={r['filings']:2d}  wrote={r['inserted']:2d}")
            time.sleep(0.1)
    finally:
        if not args.dry_run:
            flush(conn, buf, f"fetch_funding_990: {span}, facilities "
                             f"{first}-{len(facilities)} of {len(facilities)}")

    print(f"[done] hit={totals['hit']}  no_match={totals['no_match']}  "
          f"skipped={totals['skipped']}  inserted={totals['inserted']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
