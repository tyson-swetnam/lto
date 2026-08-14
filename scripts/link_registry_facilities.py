#!/usr/bin/env python3
"""Give facilities a ROR, then link registry members to the sites they work at.

Two passes.

**Pass 1 — facilities.ror.** `facilities` has no persistent organisation
identifier, so a researcher's OpenAlex affiliation (which always carries a
ROR) has nothing to join to. This resolves each facility against the
OpenAlex /institutions endpoint and stores the ROR.

Only research organisations are attempted. Of 445 catalogued facilities,
158 are places rather than organisations — experimental forests, streamgage
networks, flux towers, protected areas. A designated wilderness or a
gauging station is not a research organisation and will never hold a ROR
(its operator might); asking OpenAlex for one invites exactly the false
match upstream cod-kmap has cleaned up three times. Those rows are skipped
and their ror stays null by design, not by failure.

A candidate is accepted only when the OpenAlex institution name shares a
distinctive token with the facility name — the same generic-token-stripped
test used by the ORCID matcher, for the same reason.

**Pass 2 — registry_facilities.** With ROR on both sides the link is an
equality join: a registry member whose affiliation_ror matches a
facility's ror works at that site. No name comparison is involved.

Usage::

    python scripts/link_registry_facilities.py --dry-run
    python scripts/link_registry_facilities.py --export-parquet
    python scripts/link_registry_facilities.py --include-type flux-tower
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openalex_auth  # noqa: E402
from enrich_people_orcid import normalize_facility_name  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]
API = "https://api.openalex.org"
SLEEP = 0.25

# Tokens too generic to identify an organisation on their own. In upstream
# cod-kmap this vocabulary lives beside the ORCID matcher; lto's ORCID
# matcher predates the helper, so it lives here instead. "research" alone
# matched Electric Power Research Institute to a National Estuarine Research
# Reserve upstream; "university" matched Minnesota to the Virgin Islands.
GENERIC_ORG_TOKENS = {
    "national", "international", "state", "federal", "center", "centre",
    "research", "science", "sciences", "scientific", "laboratory", "lab",
    "laboratories", "university", "universidad", "universite", "college",
    "school", "program", "programme", "project", "service", "services",
    "agency", "office", "bureau", "division", "unit", "group", "society",
    "association", "council", "committee", "commission", "authority",
    "organization", "organisation", "corporation", "company", "trust",
    "network", "consortium", "partnership", "alliance", "system",
    "systems", "studies", "study", "environmental", "environment",
    "natural", "resources", "management", "development", "technology",
    "technologies", "engineering", "academy", "museum",
    "long", "term", "ecological", "estuarine",
    # lto additions: the long-term-observatory catalogue is full of
    # "<Somewhere> Experimental Forest" / "<Somewhere> Field Station"
    # names where only the place-name token is distinctive.
    "experimental", "forest", "range", "station", "field", "observatory",
    "monitoring", "watershed",
}


def distinctive_tokens(s: str) -> set[str]:
    """Tokens from a normalised org name that actually identify a place.

    Drops the generic vocabulary above and anything shorter than three
    characters, so what remains is proper nouns and domain-specific
    words: 'hubbard', 'smithsonian', 'oceanography', 'andrews'.
    """
    return {t for t in normalize_facility_name(s).split()
            if len(t) >= 3 and t not in GENERIC_ORG_TOKENS}


# Facility types that can plausibly hold a ROR. Everything else in the
# catalogue is a place, not an organisation.
#
# In upstream cod-kmap, 'observatory' was missing from the first version of
# this set, which silently excluded Ocean Networks Canada — a research
# organisation that does hold a ROR — from resolution entirely. The omission
# was invisible in the run output because the skip count read as if it were
# just the protected areas. Any type added to the catalogue that names an
# organisation rather than a place belongs here (or pass --include-type for
# a one-off run).
RESEARCH_TYPES = {
    "federal", "state", "local-gov", "nonprofit", "foundation", "network",
    "international-federal", "international-university",
    "international-nonprofit", "industry", "university-marine-lab",
    "university-institute", "university-field-station", "field-station",
    "observatory", "virtual",
}

# Types skipped by design: places (or vessels), not organisations. Kept as
# an explicit set — rather than "everything not in RESEARCH_TYPES" — so a
# new vocab slug that lands in neither set gets flagged in the run output
# instead of silently repeating the Ocean Networks Canada omission.
PLACE_TYPES = {
    "protected-area-federal", "protected-area-state",
    "protected-area-private", "experimental-forest-range", "ltar-site",
    "flux-tower", "glacier-monitoring", "atmospheric-baseline",
    "streamgage-network", "vessel",
}


def ensure_ror_column(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info('facilities')").fetchall()}
    if "ror" not in cols:
        conn.execute("ALTER TABLE facilities ADD COLUMN ror VARCHAR")
        print("[schema] added facilities.ror")


def ensure_link_table(conn) -> None:
    # Mirrors registry_facilities in schema/schema.sql — guard for DBs
    # rebuilt from parquet snapshots that predate the registry tables.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registry_facilities (
            canonical_id  VARCHAR NOT NULL,
            facility_id   VARCHAR NOT NULL,
            method        VARCHAR NOT NULL,
            ror           VARCHAR,
            source_url    VARCHAR,
            retrieved_at  VARCHAR,
            confidence    VARCHAR,
            PRIMARY KEY (canonical_id, facility_id))""")


def short(v) -> str | None:
    if not v:
        return None
    return str(v).rstrip("/").rsplit("/", 1)[-1] or None


def resolve_ror(sess, name: str, acronym: str | None) -> tuple[str | None, str]:
    want = distinctive_tokens(name)
    if not want:
        return None, "name-too-generic"
    r = sess.get(f"{API}/institutions",
                 params={"search": name, "per_page": 5,
                         "select": "id,display_name,ror,works_count,"
                                   "display_name_acronyms"}, timeout=40)
    if not r.ok:
        return None, f"http-{r.status_code}"
    for inst in r.json().get("results", []):
        got = distinctive_tokens(inst.get("display_name") or "")
        if got & want:
            return short(inst.get("ror")), "name-token-match"
        if acronym and acronym.upper() in [
                a.upper() for a in (inst.get("display_name_acronyms") or [])]:
            return short(inst.get("ror")), "acronym-match"
    return None, "no-match"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--export-parquet", action="store_true")
    ap.add_argument("--include-type", action="append", default=[],
                    metavar="SLUG",
                    help="treat this facility_type as a research organisation "
                         "for this run (repeatable; overrides the "
                         "conservative place-type skip)")
    ap.add_argument("--link-only", action="store_true",
                    help="skip pass 1 and run only the ROR equality join — "
                         "no OpenAlex calls and no API key needed. Use after "
                         "scripts/backfill_facility_ror.py has done the ROR "
                         "resolution against ROR's own API.")
    args = ap.parse_args()

    sess = None
    if not args.link_only:
        openalex_auth.require_api_key()
        sess = openalex_auth.openalex_session()
    conn = duckdb.connect(str(args.db))
    ensure_ror_column(conn)
    ensure_link_table(conn)
    today = date.today().isoformat()

    research_types = RESEARCH_TYPES | set(args.include_type)
    types = ",".join(f"'{t}'" for t in sorted(research_types))
    targets = [] if args.link_only else conn.execute(f"""
        SELECT facility_id, canonical_name, acronym, facility_type
        FROM facilities
        WHERE facility_type IN ({types}) AND (ror IS NULL OR ror = '')
        ORDER BY canonical_name""").fetchall()
    # Report the skipped set BY TYPE, not as a single number. A bare count
    # reads as "the places" and hides a research organisation that fell
    # outside RESEARCH_TYPES by omission — which is exactly how Ocean
    # Networks Canada went unresolved in upstream cod-kmap without anyone
    # noticing.
    skipped_by_type = conn.execute(f"""
        SELECT facility_type, COUNT(*) FROM facilities
        WHERE facility_type NOT IN ({types})
        GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    skipped = sum(n for _, n in skipped_by_type)
    unclassified = [(t, n) for t, n in skipped_by_type if t not in PLACE_TYPES]
    if args.link_only:
        print("[ror] pass 1 skipped (--link-only); facilities.ror is taken as "
              "given — scripts/backfill_facility_ror.py owns it")
    else:
        print(f"[ror] {len(targets)} research-organisation facility/ies to resolve "
              f"({skipped:,} skipped by design)")
    if unclassified and not args.link_only:
        print(f"[ror] NOTE: skipped types not in PLACE_TYPES: "
              f"{unclassified} — if any of these name an organisation rather "
              f"than a place, add them to RESEARCH_TYPES (or run with "
              f"--include-type)")
    if args.limit:
        targets = targets[:args.limit]

    found, decisions = [], {}
    for i, (fid, name, acro, ftype) in enumerate(targets, 1):
        ror, why = resolve_ror(sess, name, acro)
        decisions[why] = decisions.get(why, 0) + 1
        if ror:
            found.append((ror, fid))
        time.sleep(SLEEP)
        if i % 25 == 0:
            print(f"  [ror] {i}/{len(targets)}  {decisions}")
    if targets:
        print(f"[ror] {decisions}")
        print(f"[ror] resolved {len(found)} facility ROR(s)")

    # A ROR identifies ONE organisation, so two facilities claiming the same
    # one means at least one is wrong. In upstream cod-kmap, "Monterey Bay
    # Aquarium" matched MBARI's ROR (02nb3aq72) on the shared "Monterey Bay"
    # tokens — they are separate institutions, and accepting both would have
    # attached 90 MBARI researchers to the public aquarium. Keep no claimant
    # rather than guess which is right; the collision is reported for
    # curation.
    already = {r[0]: r[1] for r in conn.execute(
        "SELECT ror, canonical_name FROM facilities "
        "WHERE ror IS NOT NULL AND ror <> ''").fetchall()}
    claims: dict[str, list[str]] = {}
    for ror, fid in found:
        claims.setdefault(ror, []).append(fid)
    contested = {r for r, fids in claims.items()
                 if len(fids) > 1 or (r in already and fids)}
    if contested:
        for r in sorted(contested):
            names = conn.execute(
                "SELECT canonical_name FROM facilities WHERE facility_id IN "
                f"({','.join('?' * len(claims[r]))})", claims[r]).fetchall()
            other = f" (already on '{already[r]}')" if r in already else ""
            print(f"[ror] CONTESTED {r}: {[n[0] for n in names]}{other} "
                  f"— left unset, needs curation")
        found = [(r, fid) for r, fid in found if r not in contested]
        print(f"[ror] {len(found)} uncontested ROR(s) will be written")

    if not args.dry_run and found:
        conn.executemany("UPDATE facilities SET ror = ? WHERE facility_id = ?", found)

    # ── pass 2: equality join on ROR ───────────────────────────────────
    # Rebuild only the rows this pass owns. It used to clear the whole
    # table, which was safe while this script was the sole writer and
    # became destructive the moment import_codkmap_registry.py started
    # contributing edges it cannot re-derive (those come from upstream's
    # own ROR join, against RORs LTO may not carry).
    if not args.dry_run:
        conn.execute("DELETE FROM registry_facilities WHERE method = 'ror-equality'")
        # OR IGNORE: an imported edge already claims some (person, site)
        # pairs, and its provenance is the more specific of the two.
        conn.execute("""
            INSERT OR IGNORE INTO registry_facilities
                (canonical_id, facility_id, method, ror,
                 source_url, retrieved_at, confidence)
            SELECT DISTINCT r.canonical_id, f.facility_id, 'ror-equality',
                   f.ror, 'https://ror.org/' || f.ror, ?, 'high'
            FROM person_registry r
            JOIN facilities f ON f.ror = r.affiliation_ror
            WHERE r.affiliation_ror IS NOT NULL AND r.affiliation_ror <> ''
              AND f.ror IS NOT NULL AND f.ror <> ''""", [today])
    n = conn.execute("SELECT COUNT(*) FROM registry_facilities").fetchone()[0]
    people = conn.execute(
        "SELECT COUNT(DISTINCT canonical_id) FROM registry_facilities").fetchone()[0]
    sites = conn.execute(
        "SELECT COUNT(DISTINCT facility_id) FROM registry_facilities").fetchone()[0]
    print(f"[link] {n:,} registry↔facility link(s): "
          f"{people:,} researcher(s) across {sites} site(s)")

    if args.export_parquet and not args.dry_run:
        db_base, site_base = PARQUET_OUT
        for base in PARQUET_OUT:
            base.mkdir(parents=True, exist_ok=True)
        # facilities ships whole — every site is a map feature regardless of
        # whether any of its researchers made the core tier.
        for base in PARQUET_OUT:
            conn.execute(f"COPY facilities TO "
                         f"'{base / 'facilities.parquet'}' (FORMAT PARQUET)")
        conn.execute(f"COPY registry_facilities TO "
                     f"'{db_base / 'registry_facilities.parquet'}' (FORMAT PARQUET)")
        # The browser only holds the core tier of person_registry, so a link
        # to an archive-tier researcher would render as a reference to a row
        # that isn't there. In upstream cod-kmap, 1,204 of 1,467 links were
        # in that state before this filter was added. Same rule the edge
        # export uses in scripts/rank_person_registry.py.
        conn.execute(f"""COPY (SELECT rf.* FROM registry_facilities rf
                         JOIN person_registry r USING (canonical_id)
                         WHERE r.tier = 'core')
                         TO '{site_base / 'registry_facilities.parquet'}'
                         (FORMAT PARQUET)""")
        shipped = conn.execute(
            "SELECT COUNT(*) FROM registry_facilities rf "
            "JOIN person_registry r USING (canonical_id) "
            "WHERE r.tier = 'core'").fetchone()[0]
        print(f"[parquet] db/parquet: all {n:,} link(s); "
              f"public/parquet: {shipped:,} core-tier link(s)")
        print("[note] db/parquet is gitignored (stage with `git add -f`); "
              "public/parquet is committed")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
