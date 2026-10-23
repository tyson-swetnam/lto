#!/usr/bin/env python3
"""URL hygiene pass — pattern-based broken-URL cleanup.

Runs against the LTO lake (scripts/lto_db.py) and:

  1. NULLs homepage_url, facilities.url, facilities.data_portal_url
     where the URL matches a "definitely junk" pattern (root-domain
     only, deprecated landing pages, broken templates).
  2. Migrates known-deprecated hosts to their current canonical form
     (e.g. nrs.fs.fed.us → research.fs.usda.gov/nrs).
  3. Logs every decision to data/seed/url_hygiene_log.csv for audit.

Steps 1-2 land as one lake snapshot (commit message ``url_hygiene: …``).
--dry-run opens the lake read-only; it still appends the decision log.

This pass is sandbox-safe (no network). The companion
scripts/check_url_health.py does HTTP HEAD verification in CI where
the network is unrestricted.

Usage::

    python scripts/url_hygiene.py
    python scripts/url_hygiene.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "seed" / "url_hygiene_log.csv"


# Patterns: regex → action ("null" | replacement-template).
# Order matters: first match wins.
HOMEPAGE_PATTERNS = [
    # Deprecated NRS host migrated to research.fs.usda.gov/nrs in 2023.
    (re.compile(r"^https?://(?:www\.)?nrs\.fs\.fed\.us/people/([^/?]+)/?$"),
     r"https://research.fs.usda.gov/nrs/people/\1"),
    # Generic /about/staff or /staff/profile/ (without a per-person path).
    (re.compile(r"^https?://[^/]+/about/staff\.(?:html|php|aspx)/?$"), "null"),
    (re.compile(r"^https?://[^/]+/about/staff/?$"), "null"),
    (re.compile(r"^https?://[^/]+/staff/profile/?$"), "null"),
    (re.compile(r"^https?://[^/]+/staff/?$"), "null"),
    (re.compile(r"^https?://[^/]+/staff-profiles/?$"), "null"),
    (re.compile(r"^https?://[^/]+/about/?$"), "null"),
    (re.compile(r"^https?://[^/]+/about-us/staff/?$"), "null"),
    (re.compile(r"^https?://[^/]+/contact/?$"), "null"),
    (re.compile(r"^https?://[^/]+/contact-us/?$"), "null"),
    (re.compile(r"^https?://[^/]+/contactus\.htm$"), "null"),
    (re.compile(r"^https?://[^/]+/leadership/?$"), "null"),
    (re.compile(r"^https?://[^/]+/About/Leadership/?$"), "null"),
    # NPS unit /im/<network>/contact[us].htm and /<unit>/learn/nature/index.htm
    # are facility-listing pages, not individual profiles. Null so the UI
    # cascade falls back to facility URL.
    (re.compile(r"^https?://www\.nps\.gov/im/[a-z]+/contact(?:us)?\.htm$"), "null"),
    (re.compile(r"^https?://www\.nps\.gov/im/contactus\.htm$"), "null"),
    (re.compile(r"^https?://www\.nps\.gov/[a-z]+/learn/nature/index\.htm$"), "null"),
    # NGO/foundation generic team pages.
    (re.compile(r"^https?://[^/]+/our-team/?$"), "null"),
    (re.compile(r"^https?://[^/]+/our-people/?$"), "null"),
    (re.compile(r"^https?://[^/]+/our-staff/?$"), "null"),
    (re.compile(r"^https?://[^/]+/our-scientists/?$"), "null"),
    # Generic listing pages where the URL ends at /people/ or /faculty/
    # with no person slug. The UI cascade still gets the user to the
    # facility, so nulling these is a strict improvement.
    (re.compile(r"^https?://[^/]+/people/?$"), "null"),
    (re.compile(r"^https?://[^/]+/faculty/?$"), "null"),
    (re.compile(r"^https?://[^/]+/researchers/?$"), "null"),
    (re.compile(r"^https?://[^/]+/scientists/?$"), "null"),
    # ARS region/location/lab people listing without a final slug.
    (re.compile(r"^https?://www\.ars\.usda\.gov/[a-z-]+/[a-z-]+/[a-z-]+/people/?$"),
     "null"),
    # USFS bare-region pages (www.fs.usda.gov/srs/ etc) that pretend to
    # be a person but are the regional landing page.
    (re.compile(r"^https?://www\.fs\.usda\.gov/[a-z]+/?$"), "null"),
    # Bare root with no path at all.
    (re.compile(r"^https?://[^/]+/?$"), "null"),
    # Specific known-dead URLs from cod-kmap heritage that 404 today.
    # (add more as the CI HTTP-HEAD checker discovers them)
]

# Facility-URL hygiene is more conservative — root URLs ARE often the
# intended landing page for a facility, unlike a person's homepage.
FACILITY_URL_PATTERNS = [
    # Deprecated nrs.fs.fed.us migration applies here too.
    (re.compile(r"^https?://(?:www\.)?nrs\.fs\.fed\.us/ef/locations/([^/?]+)/([^/?]+)/?$"),
     r"https://research.fs.usda.gov/nrs/ef/locations/\1/\2"),
    (re.compile(r"^https?://(?:www\.)?nrs\.fs\.fed\.us/ef/?$"),
     "https://research.fs.usda.gov/nrs/ef"),
]


def apply_patterns(url: str | None, patterns) -> tuple[str | None, str | None]:
    """Returns (new_url_or_None_to_null, decision_label_or_None)."""
    if not url:
        return url, None
    s = url.strip()
    for rx, action in patterns:
        m = rx.match(s)
        if not m:
            continue
        if action == "null":
            return None, "null:" + rx.pattern
        # Replacement template
        return rx.sub(action, s), "rewrite:" + rx.pattern
    return url, None


def apply_updates(conn, table: str, key: str, field: str,
                  updates: list[tuple[str, str | None]]) -> None:
    """One staged UPDATE per field (a per-row UPDATE costs ~10 ms on a lake)."""
    if not updates:
        return
    conn.execute("CREATE OR REPLACE TEMP TABLE _url_fix (k VARCHAR, v VARCHAR)")
    conn.executemany("INSERT INTO _url_fix VALUES (?, ?)", updates)
    conn.execute(f"UPDATE {table} SET {field} = _url_fix.v FROM _url_fix "
                 f"WHERE {table}.{key} = _url_fix.k")
    conn.execute("DROP TABLE _url_fix")


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_rows = []
    people_updates: list[tuple[str, str | None]] = []
    facility_updates: list[tuple[str, str | None]] = []

    with lto_db.connect(read_only=args.dry_run, catalog=args.catalog,
                        data=args.lake_data) as conn:
        # 1. people.homepage_url
        rows = conn.execute(
            "SELECT person_id, name, homepage_url FROM people "
            "WHERE homepage_url IS NOT NULL"
        ).fetchall()
        nulled, rewritten = 0, 0
        for pid, name, url in rows:
            new, decision = apply_patterns(url, HOMEPAGE_PATTERNS)
            if decision is None:
                continue
            log_rows.append({
                "table": "people", "id": pid, "name": name,
                "field": "homepage_url", "old": url, "new": new or "",
                "decision": decision, "checked_at": date.today().isoformat(),
            })
            people_updates.append((pid, new))
            if new is None:
                nulled += 1
            else:
                rewritten += 1
        print(f"[url_hygiene] people.homepage_url — nulled {nulled}, rewrote {rewritten}, "
              f"audited {len(rows)}")

        # 2. facilities.url
        rows = conn.execute(
            "SELECT facility_id, canonical_name, url FROM facilities "
            "WHERE url IS NOT NULL"
        ).fetchall()
        nulled, rewritten = 0, 0
        for fid, name, url in rows:
            new, decision = apply_patterns(url, FACILITY_URL_PATTERNS)
            if decision is None:
                continue
            log_rows.append({
                "table": "facilities", "id": fid, "name": name,
                "field": "url", "old": url, "new": new or "",
                "decision": decision, "checked_at": date.today().isoformat(),
            })
            facility_updates.append((fid, new))
            if new is None:
                nulled += 1
            else:
                rewritten += 1
        print(f"[url_hygiene] facilities.url — nulled {nulled}, rewrote {rewritten}, "
              f"audited {len(rows)}")

        if not args.dry_run and (people_updates or facility_updates):
            with lto_db.transaction(
                    conn, f"url_hygiene: {len(people_updates)} people.homepage_url, "
                          f"{len(facility_updates)} facilities.url"):
                apply_updates(conn, "people", "person_id", "homepage_url",
                              people_updates)
                apply_updates(conn, "facilities", "facility_id", "url",
                              facility_updates)
                lto_db.assert_integrity(conn, ["people", "facilities"])

    # Append the decision log (CSV).
    write_header = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "table", "id", "name", "field", "old", "new", "decision", "checked_at",
        ])
        if write_header:
            w.writeheader()
        for row in log_rows:
            w.writerow(row)
    print(f"[url_hygiene] log appended → {LOG_PATH.relative_to(ROOT)} (+{len(log_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
