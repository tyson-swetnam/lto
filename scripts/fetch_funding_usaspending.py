#!/usr/bin/env python3
"""Fetch USAspending.gov grants for cod-kmap facilities.

Captures the federal funders NSF Awards API misses: NOAA, EPA, USGS,
USFWS, NIH, BOEM, ONR, DOE, NASA earth-science. Federal contracts are
included via a separate award-type-code group (see --include-contracts).

Pipeline per facility:

  1. Search awards via POST /api/v2/search/spending_by_award/ with
     recipient_search_text=<recipient> + time_period=[FY15-FY24].
     Returns lifetime award snapshots — no per-FY breakdown yet.
  2. For each award, POST /api/v2/transactions/ with award_id =
     generated_internal_id. Each transaction has an action_date and
     federal_action_obligation. Sum by fiscal_year (FY = Oct 1 – Sep 30).
  3. Write one funding_events row per (award, fiscal_year) with the
     sum of that FY's obligations. Idempotent via
     event_id = hash(funder|facility|award|fy).

Recipient resolution:

  * AUTO mode: use facility.parent_org as recipient_search_text when
    it looks like a real institution name (university / research
    institute / aquarium / lab). Skipped for generic parents
    ("EPA National Estuary Program", "Independent 501(c)(3)").
  * OVERRIDE: data/funding_overrides/usaspending_recipient_overrides.csv
    pins the exact recipient string and (optionally) award-id whitelist
    or description-substring filter for facilities whose USAspending
    name differs from their canonical name.

Funder identity:

  Each award's `Awarding Agency` is captured into a separate funder row
  (NSF, NOAA, EPA, USGS, NIH, etc.) with type='federal'. Funders are
  upserted by hash(lower(name)) — same identity scheme as NSF script.

Confidence:

  * 'high' for obligations matching against generated_internal_id
    (primary federal source, audit-trail back to USAspending).

Usage::

    python scripts/fetch_funding_usaspending.py
    python scripts/fetch_funding_usaspending.py --limit 10
    python scripts/fetch_funding_usaspending.py --facility-id <hash>
    python scripts/fetch_funding_usaspending.py --start-fy 2015 --end-fy 2024
    python scripts/fetch_funding_usaspending.py --include-contracts
    python scripts/fetch_funding_usaspending.py --skip-done
    python scripts/fetch_funding_usaspending.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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
DEFAULT_OVERRIDES = ROOT / "data" / "funding_overrides" / "usaspending_recipient_overrides.csv"
API_SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
API_TRANSACTIONS = "https://api.usaspending.gov/api/v2/transactions/"
API_TXN_SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_transaction/"
SEARCH_FIELDS = [
    "Award ID", "Recipient Name", "Award Amount", "Description",
    "Awarding Agency", "Awarding Sub Agency", "Funding Agency",
    "generated_internal_id", "CFDA Number",
]
TXN_SEARCH_FIELDS = [
    "Transaction Amount", "Action Date", "Award ID",
    "Awarding Agency", "Awarding Sub Agency",
    "Recipient Name",
]
GRANT_TYPE_CODES = ["02", "03", "04", "05"]
CONTRACT_TYPE_CODES = ["A", "B", "C", "D"]
PER_PAGE = 100  # USAspending caps at 100/page
SAFETY_PAGE_CAP = 100  # 10000 awards per facility — far beyond any real recipient
RETRY_MAX = 3

AUTO_RECIPIENT_HINTS = (
    "university", "college", "institut", "laborator", "observatory",
    "school of", "research center", "aquarium", "marine center",
    "consortium",
)
AUTO_RECIPIENT_BLOCKLIST = (
    "epa national estuary program", "independent 501(c)(3)",
    "national park service", "national marine sanctuary",
    "u.s. environmental protection agency",
    "u.s. geological survey", "u.s. fish and wildlife service",
    "u.s. department of the interior",
    "noaa", "nsf", "epa region",
)
# Matched against the facility's own name, as fetch_funding_nsf does: a reserve
# or estuary program whose parent_org is its lead agency or host (a university,
# per NOAA or the program's homepage) is not that university's federal portfolio.
# One list for both fetchers.
from fetch_funding_nsf import AUTO_AWARDEE_NAME_BLOCKLIST as AUTO_RECIPIENT_NAME_BLOCKLIST  # noqa: E402


def _hash(s: str) -> str:
    return hashlib.blake2b(s.encode("utf-8"), digest_size=8).hexdigest()


def funder_id_for(name: str) -> str:
    return _hash((name or "").lower().strip())


def event_id_for(funder_id: str, facility_id: str, award_id: str,
                 fiscal_year: int | None) -> str:
    return _hash(f"{funder_id}|{facility_id}|{award_id}|{fiscal_year or ''}")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "cod-kmap/0.1 (github.com/tyson-swetnam/cod-kmap; "
        "mailto:tswetnam@arizona.edu)"
    )
    s.headers["Content-Type"] = "application/json"
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
            # Existing funder: fill only its NULL type/country/url (the old
            # UPDATE ... SET x = COALESCE(x, ?)); new funder: insert.
            conn.execute("""
                MERGE INTO funders t USING _stage_funders s
                  ON t.funder_id = s.funder_id
                WHEN MATCHED AND (t.type IS NULL OR t.country IS NULL
                                  OR (t.url IS NULL AND s.url IS NOT NULL))
                  THEN UPDATE SET type = COALESCE(t.type, s.type),
                                  country = COALESCE(t.country, s.country),
                                  url = COALESCE(t.url, s.url)
                WHEN NOT MATCHED THEN INSERT (funder_id, name, type, country, url)
                  VALUES (s.funder_id, s.name, s.type, s.country, s.url)""")
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
    """facility_id -> {recipients: [...], award_ids: [...],
                       description_matches: [...]}."""
    out: dict[str, dict] = {}
    if not path.exists():
        print(f"[overrides] none found at {path} (this is fine)")
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(
            (line for line in fh if not line.lstrip().startswith("#")),
        )
        for row in reader:
            # A facility merged away (merge_facilities.py) keeps its
            # overrides under the facility it was kept as.
            fid = lto_db.canonical_facility_id((row.get("facility_id") or "").strip())
            if not fid:
                continue
            entry = out.setdefault(fid, {
                "recipients": [], "award_ids": [], "description_matches": [],
            })
            for col, key in (
                ("recipient_search_text", "recipients"),
                ("award_id", "award_ids"),
                ("description_match", "description_matches"),
            ):
                v = (row.get(col) or "").strip()
                if v and v not in entry[key]:
                    entry[key].append(v)
    print(f"[overrides] loaded {len(out)} facility-specific overrides")
    return out


def search_transactions(sess: requests.Session, recipient: str,
                        start_fy: int, end_fy: int,
                        type_codes: list[str]) -> list[dict]:
    """Paginate every transaction matching recipient + FY window + type
    codes. This is the *fast path* — one API hit per page (100 txns)
    gives us the per-FY truth that would otherwise require N per-award
    /transactions/ lookups (which USAspending throttles aggressively).

    Sort by action_date so transactions within an award arrive in
    chronological order — easier to debug logs.
    """
    out: list[dict] = []
    page = 1
    safety = 0
    payload_filters = {
        "recipient_search_text": [recipient],
        "time_period": [{
            "start_date": f"{start_fy - 1}-10-01",
            "end_date":   f"{end_fy}-09-30",
        }],
        "award_type_codes": type_codes,
    }
    while True:
        safety += 1
        if safety > SAFETY_PAGE_CAP:
            print(f"[warn] hit safety page cap (txns) for recipient={recipient}")
            break
        body = {
            "limit": PER_PAGE,
            "page": page,
            "sort": "Action Date",
            "order": "asc",
            "filters": payload_filters,
            "fields": TXN_SEARCH_FIELDS,
        }
        data = None
        for attempt in range(RETRY_MAX):
            try:
                r = sess.post(API_TXN_SEARCH, json=body, timeout=30)
                if r.status_code == 429:
                    time.sleep(2 + attempt * 2)
                    continue
                if not r.ok:
                    print(f"[warn] txn search {r.status_code}: {r.text[:200]}")
                    return out
                data = r.json()
                break
            except Exception as e:
                if attempt == RETRY_MAX - 1:
                    print(f"[warn] txn search failed for {recipient}: {e}")
                    return out
                time.sleep(0.5 + attempt)
        if data is None:
            return out
        results = data.get("results", [])
        out.extend(results)
        if not data.get("page_metadata", {}).get("hasNext"):
            break
        if not results:
            break
        page += 1
        time.sleep(0.05)
    return out


def search_awards(sess: requests.Session, recipient: str,
                  start_fy: int, end_fy: int,
                  type_codes: list[str]) -> list[dict]:
    """Page through every award matching the recipient+time+type filters."""
    out: list[dict] = []
    page = 1
    safety = 0
    payload_filters = {
        "recipient_search_text": [recipient],
        "time_period": [{
            "start_date": f"{start_fy - 1}-10-01",
            "end_date":   f"{end_fy}-09-30",
        }],
        "award_type_codes": type_codes,
    }
    while True:
        safety += 1
        if safety > SAFETY_PAGE_CAP:
            print(f"[warn] hit safety page cap for recipient={recipient}")
            break
        body = {
            "subawards": False,
            "limit": PER_PAGE,
            "page": page,
            "filters": payload_filters,
            "fields": SEARCH_FIELDS,
        }
        for attempt in range(RETRY_MAX):
            try:
                r = sess.post(API_SEARCH, json=body, timeout=30)
                if r.status_code == 429:
                    time.sleep(3 + attempt * 2)
                    continue
                if not r.ok:
                    print(f"[warn] USAspending search {r.status_code}: "
                          f"{r.text[:200]}")
                    return out
                data = r.json()
                break
            except Exception as e:
                print(f"[warn] USAspending search failed ({attempt+1}/{RETRY_MAX}): {e}")
                time.sleep(1 + attempt)
        else:
            return out
        results = data.get("results", [])
        out.extend(results)
        if not data.get("page_metadata", {}).get("hasNext"):
            break
        if not results:
            break
        page += 1
        time.sleep(0.05)
    return out


def fetch_transactions(sess: requests.Session, internal_id: str
                       ) -> list[dict]:
    """All transaction modifications for an award. Retries on
    connection drops (USAspending closes idle connections aggressively
    and the threadpool can race past its keep-alive)."""
    out: list[dict] = []
    page = 1
    safety = 0
    while True:
        safety += 1
        if safety > 50:
            break
        body = {"award_id": internal_id, "limit": 100, "page": page}
        data = None
        for attempt in range(RETRY_MAX):
            try:
                r = sess.post(API_TRANSACTIONS, json=body, timeout=30)
                if r.status_code == 429:
                    time.sleep(2 + attempt)
                    continue
                if not r.ok:
                    return out
                data = r.json()
                break
            except Exception as e:
                if attempt == RETRY_MAX - 1:
                    print(f"[warn] transactions {internal_id} failed after "
                          f"{RETRY_MAX} retries: {e}")
                    return out
                time.sleep(0.5 + attempt)
        if data is None:
            return out
        out.extend(data.get("results", []))
        if not data.get("page_metadata", {}).get("hasNext"):
            break
        page += 1
    return out


def fy_for_date(iso: str | None) -> int | None:
    """US fiscal year = Oct 1 of (year-1) through Sep 30 of (year)."""
    if not iso:
        return None
    m = re.match(r"(\d{4})-(\d{2})-\d{2}$", iso[:10])
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    return y if mo < 10 else y + 1


def ensure_funder(buf: LakeBuffer, name: str, kind: str = "federal") -> str:
    """Queue a funder row; flush() inserts it, or fills its NULL
    type/country if it already exists. The first name seen for an id wins."""
    fid = funder_id_for(name)
    buf.funders.setdefault(fid, (name, kind, "US", None))
    return fid


def _summarise_transactions(award: dict, txs: list[dict],
                            start_fy: int, end_fy: int
                            ) -> tuple[dict[int, float], str | None, str | None]:
    """Roll a transaction list up to per-FY totals + period bounds."""
    fy_totals: dict[int, float] = defaultdict(float)
    period_start = period_end = None
    for tx in txs:
        amt = float(tx.get("federal_action_obligation") or 0)
        fy = fy_for_date(tx.get("action_date"))
        if fy is None:
            continue
        if fy < start_fy or fy > end_fy:
            continue
        fy_totals[fy] += amt
        d = tx.get("action_date")
        if d:
            if period_start is None or d < period_start:
                period_start = d
            if period_end is None or d > period_end:
                period_end = d
    return fy_totals, period_start, period_end


def fetch_and_summarise(award: dict, sess: requests.Session,
                        start_fy: int, end_fy: int
                        ) -> tuple[dict, dict[int, float], str | None, str | None]:
    """Worker for the threadpool: fetch transactions, summarise."""
    internal_id = award.get("generated_internal_id") or ""
    txs = fetch_transactions(sess, internal_id) if internal_id else []
    fy_totals, ps, pe = _summarise_transactions(award, txs, start_fy, end_fy)
    return award, fy_totals, ps, pe


def write_award_rows(buf: LakeBuffer, facility_id: str, award: dict,
                     fy_totals: dict[int, float],
                     period_start: str | None,
                     period_end: str | None,
                     confidence: str = "high") -> int:
    internal_id = award.get("generated_internal_id") or ""
    award_id = (award.get("Award ID") or "")[:60]
    title = (award.get("Description") or "")[:500]
    funder_name = (award.get("Awarding Agency") or "Unknown federal").strip()
    sub_agency = (award.get("Awarding Sub Agency") or "").strip()
    cfda = (award.get("CFDA Number") or "").strip() or None
    src_url = f"https://www.usaspending.gov/award/{internal_id}/"
    funder_id = ensure_funder(buf, funder_name, "federal")
    program = (sub_agency or cfda or "")[:200]
    inserted = 0
    for fy, total in fy_totals.items():
        if total == 0:
            continue
        eid = event_id_for(funder_id, facility_id, award_id or internal_id, fy)
        buf.add_event(
            event_id=eid, funder_id=funder_id, facility_id=facility_id,
            amount_usd=total, amount_currency="USD", fiscal_year=fy,
            period_start=period_start, period_end=period_end,
            award_id=award_id or internal_id, award_title=title,
            program=program, relation=_relation_for_type(award),
            source="USAspending.gov", source_url=src_url,
            retrieved_at=date.today(), confidence=confidence,
            notes=f"awarding_subagency={sub_agency}; cfda={cfda or ''}")
        inserted += 1
    return inserted


def _relation_for_type(award: dict) -> str:
    """Map USAspending award_type_code to funding_events.relation."""
    # USAspending search results don't include type_code by default —
    # we infer from the Award ID prefix when we can.
    aid = (award.get("Award ID") or "").strip()
    if not aid:
        return "grant"
    # Cooperative agreements often have NA prefixes (NOAA), R/U/F NIH
    # grants use letter+digit, contracts use long alphanumeric DOD codes.
    # This is a best-effort label, not authoritative.
    if re.match(r"^N[A-Z]\d", aid):     # NOAA award
        return "cooperative-agreement"
    if re.match(r"^[A-Z]\d{2}", aid):    # NIH R01, R21, K99...
        return "grant"
    return "grant"


def _auto_recipient(parent: str, name: str = "") -> str | None:
    if not parent:
        return None
    p = parent.lower()
    if any(b in p for b in AUTO_RECIPIENT_BLOCKLIST):
        return None
    if any(b in (name or "").lower() for b in AUTO_RECIPIENT_NAME_BLOCKLIST):
        return None
    if any(h in p for h in AUTO_RECIPIENT_HINTS):
        return parent
    return None


def _award_matches_filters(award: dict, ov: dict) -> bool:
    if ov.get("award_ids") and award.get("Award ID") in ov["award_ids"]:
        return True
    dm = [m.lower() for m in (ov.get("description_matches") or [])]
    if dm:
        desc = (award.get("Description") or "").lower()
        if not any(d in desc for d in dm):
            return False
    return True


def _signed_fy(award: dict) -> int | None:
    """Date the award was first signed → US FY. Best-effort proxy for
    no-transactions mode. The search endpoint doesn't return signing
    date directly, but the Award ID often encodes year (NA21..., NSF
    awards start with 2-digit FY). Falls back to None if we can't tell."""
    aid = (award.get("Award ID") or "").strip()
    # NOAA: NA<YY>OAR... or NA<YY>NOS...
    m = re.match(r"^NA(\d{2})", aid)
    if m:
        yy = int(m.group(1))
        return 2000 + yy
    # NSF (e.g. 2436033 → first digit '2', then 3 digits indicate fiscal year context)
    # NSF award IDs have an embedded year approximation: 2436033 awarded ~FY24
    m = re.match(r"^(\d{7})$", aid)
    if m:
        # NSF award numbers start FY-encoded: 2#####, 1#####, 0#####
        # 24XXXXX = FY24 (started FY24); fiscal year of first action.
        s = aid
        if s.startswith("2") or s.startswith("1") or s.startswith("0"):
            yy = int(s[:2])
            return 2000 + yy
    # NIH grants: R01ESxxxxx, R21ESxxxxx — no FY in number directly.
    return None


def process_facility(buf: LakeBuffer, sess: requests.Session, facility: dict,
                     overrides: dict, start_fy: int, end_fy: int,
                     include_contracts: bool, no_transactions: bool,
                     dry: bool) -> dict:
    fid = facility["facility_id"]
    parent = facility.get("parent_org") or ""

    ov = overrides.get(fid, {})
    recipients: list[str] = list(ov.get("recipients") or [])
    if not recipients:
        auto = _auto_recipient(parent, facility.get("canonical_name") or "")
        if auto:
            recipients = [auto]
    if not recipients and not ov.get("award_ids"):
        return {"awards": 0, "candidates": 0, "inserted": 0,
                "queries": 0, "skipped": True}

    type_groups = [GRANT_TYPE_CODES]
    if include_contracts:
        type_groups.append(CONTRACT_TYPE_CODES)

    # FAST PATH (default): query spending_by_transaction directly per
    # recipient × type-group. Each transaction already has Action Date
    # + Transaction Amount + Award ID + Awarding Agency; we group by
    # (Award ID, FY) and emit one funding_events row per group with
    # SUM(Transaction Amount). This avoids the per-award /transactions/
    # endpoint entirely — for WHOI it cuts ~600 API calls down to ~20.
    queries = 0
    txn_rows: list[dict] = []
    for rec in recipients:
        for type_codes in type_groups:
            queries += 1
            txn_rows.extend(
                search_transactions(sess, rec, start_fy, end_fy, type_codes)
            )

    # description_match isn't applicable to transaction rows (they
    # don't carry the Description field), so we only honor award_id
    # whitelists in this code path. Description filters still apply
    # in the slow legacy path below.
    if ov.get("award_ids"):
        whitelist = set(ov["award_ids"])
        txn_rows = [t for t in txn_rows if t.get("Award ID") in whitelist]

    # Group by (Award ID, fiscal_year). Track the agency / sub-agency
    # of the FIRST transaction we see for each award (consistent
    # within an award, agencies almost never change funder mid-grant).
    by_award_fy: dict[tuple[str, int], dict] = {}
    for t in txn_rows:
        award_id = (t.get("Award ID") or "").strip()
        fy = fy_for_date(t.get("Action Date"))
        if not award_id or fy is None:
            continue
        if fy < start_fy or fy > end_fy:
            continue
        amt = float(t.get("Transaction Amount") or 0)
        key = (award_id, fy)
        if key not in by_award_fy:
            by_award_fy[key] = {
                "award_id": award_id,
                "fy": fy,
                "amount": 0.0,
                "agency": (t.get("Awarding Agency") or "Unknown federal").strip(),
                "sub_agency": (t.get("Awarding Sub Agency") or "").strip(),
                "internal_id": t.get("generated_internal_id") or "",
                "first_action": t.get("Action Date"),
                "last_action": t.get("Action Date"),
            }
        g = by_award_fy[key]
        g["amount"] += amt
        if t.get("Action Date") and t["Action Date"] < g["first_action"]:
            g["first_action"] = t["Action Date"]
        if t.get("Action Date") and t["Action Date"] > g["last_action"]:
            g["last_action"] = t["Action Date"]

    inserted = 0
    if not dry:
        for grp in by_award_fy.values():
            if grp["amount"] == 0:
                continue
            funder_id = ensure_funder(buf, grp["agency"], "federal")
            program = (grp["sub_agency"] or "")[:200]
            src_url = (
                f"https://www.usaspending.gov/award/{grp['internal_id']}/"
                if grp["internal_id"] else None
            )
            eid = event_id_for(funder_id, fid, grp["award_id"], grp["fy"])
            buf.add_event(
                event_id=eid, funder_id=funder_id, facility_id=fid,
                amount_usd=grp["amount"], amount_currency="USD",
                fiscal_year=grp["fy"], period_start=grp["first_action"],
                period_end=grp["last_action"], award_id=grp["award_id"],
                award_title=None, program=program, relation="grant",
                source="USAspending.gov", source_url=src_url,
                retrieved_at=date.today(), confidence="high",
                notes=f"awarding_subagency={grp['sub_agency']}")
            inserted += 1
    matched_n = len(by_award_fy)
    candidates_n = len(txn_rows)

    if False and not dry and []:  # legacy slow path retained for reference
        if no_transactions:
            # FAST mode: skip the per-award transactions endpoint
            # (which is rate-limited / drops connections under any
            # parallelism). The search endpoint already filtered by
            # time_period overlap with the requested FY range; we
            # synthesise a single funding_events row per (award, fy)
            # using `Award Amount` as a per-FY proxy for awards whose
            # period_start_year matches that fy. Coarse but reliable.
            for a in matched:
                fy_proxy = _signed_fy(a) or end_fy
                if fy_proxy < start_fy or fy_proxy > end_fy:
                    continue
                amt = float(a.get("Award Amount") or 0)
                if amt == 0:
                    continue
                inserted += write_award_rows(
                    buf, fid, a,
                    {fy_proxy: amt}, None, None,
                    confidence="medium",  # FY proxy, not transactions truth
                )
        else:
            # Slow but accurate mode (default OFF for the default run):
            # parallelise per-award /transactions/ calls. Recommended
            # only when the script is run in --facility-id mode for a
            # single facility you really want exact-FY data on.
            def _worker(award):
                local_sess = session()
                return fetch_and_summarise(award, local_sess, start_fy, end_fy)

            results: list[tuple] = []
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(_worker, a) for a in matched]
                for fut in as_completed(futures):
                    try:
                        results.append(fut.result())
                    except Exception as e:
                        print(f"[warn] worker failed: {e}")
            for award, fy_totals, ps, pe in results:
                inserted += write_award_rows(buf, fid, award, fy_totals, ps, pe)
    return {
        "awards": matched_n,
        "candidates": candidates_n,
        "inserted": inserted,
        "queries": queries,
        "skipped": False,
    }


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
    ap.add_argument("--include-contracts", action="store_true",
                    help="Also pull federal contracts (codes A/B/C/D). "
                         "Off by default — most science money is in "
                         "grants + cooperative agreements.")
    ap.add_argument("--no-transactions", action="store_true",
                    help="Skip the per-award /transactions/ endpoint "
                         "(which is rate-limited / unreliable for big "
                         "recipients). Uses Award Amount + signing-FY "
                         "proxy. Faster, less precise (confidence=medium).")
    ap.add_argument("--skip-done", action="store_true",
                    help="Skip facilities that already have at least one "
                         "USAspending row in funding_events.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        conn = lto_db.connect(read_only=args.dry_run, catalog=args.catalog,
                              data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    sess = session()
    buf = LakeBuffer()
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
            "WHERE source = 'USAspending.gov'"
        ).fetchall()}
        before = len(facilities)
        facilities = [f for f in facilities if f["facility_id"] not in done]
        print(f"[skip-done] dropped {before - len(facilities)} already-fetched facilities")
    if args.limit:
        facilities = facilities[: args.limit]
    print(f"[usaspending] FY{args.start_fy}-FY{args.end_fy}  "
          f"{len(facilities)} facilities  "
          f"{'(grants+contracts)' if args.include_contracts else '(grants only)'}"
          f"{'  (dry-run)' if args.dry_run else ''}")

    totals = {"awards": 0, "inserted": 0, "queries": 0,
              "processed": 0, "skipped": 0}
    # Checkpoint: one snapshot per FLUSH_EVERY facilities, plus the rest
    # in `finally` (a crash or Ctrl-C keeps what was fetched).
    span = f"FY{args.start_fy}-FY{args.end_fy}"
    first = 1
    try:
        for i, fac in enumerate(facilities, 1):
            if not args.dry_run and i > first and (i - 1) % FLUSH_EVERY == 0:
                flush(conn, buf, f"fetch_funding_usaspending: {span}, facilities "
                                 f"{first}-{i - 1} of {len(facilities)}")
                first = i
            try:
                r = process_facility(buf, sess, fac, overrides,
                                     args.start_fy, args.end_fy,
                                     args.include_contracts,
                                     args.no_transactions, args.dry_run)
            except Exception as e:
                print(f"  [{i}/{len(facilities)}] {(fac['acronym'] or ''):10s} "
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
    finally:
        if not args.dry_run:
            flush(conn, buf, f"fetch_funding_usaspending: {span}, facilities "
                             f"{first}-{len(facilities)} of {len(facilities)}")

    print(f"[done] processed={totals['processed']}  "
          f"skipped={totals['skipped']}  queries={totals['queries']}  "
          f"matched_awards={totals['awards']}  inserted={totals['inserted']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
