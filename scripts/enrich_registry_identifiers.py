#!/usr/bin/env python3
"""Give every registry row a persistent identifier, and hydrate the ones that have one.

Two jobs:

**Hydrate** — for a registry row that already carries an ORCID or an
OpenAlex id, pull the OpenAlex author record and fill in homepage, ROR-bearing
affiliation, Scholar id, `summary_stats` (h-index, i10, 2-yr citedness) and
the LTO-topic work count. The last one comes from `topics[].count` summed over
the LTO topic set, so it costs no extra requests — upstream cod-kmap's
earlier harvest spent three calls per author to compute the same number.

**Resolve** — for a row with neither identifier, find one. This is the
dangerous half, so it is gated hard. Note what resolution does and does not
do: it attaches an identifier to a *source* row (people) with confidence
'medium'; the registry merge itself still happens only on ORCID/openalex_id
equality inside build_person_registry.py. Name similarity never merges, and
a source row that ends this script still lacking both identifiers is skipped
by the registry build with a counted warning — never minted a local id.

Resolution rules (ALL must hold)
--------------------------------
  1. Family name matches exactly, case- and diacritic-insensitive.
  2. Given names are compatible position by position: at each position an
     initial matches a spelled-out name with the same first letter, but two
     spelled-out names must be equal. "Randall Hughes" vs "Randall A.
     Hughes" is compatible; "Y. Stacy Zhang" vs "Y. Joseph Zhang" is not —
     that exact pair merged wrongly once already in upstream cod-kmap.

     This comparison is positional, so it also rejects a *dropped* given
     name: "A. Randall Hughes" and "Randall Hughes" are refused, because
     position 0 compares "A." against "Randall". That is stricter than
     necessary for the person who publishes under a middle name, and it
     costs some true matches. It is deliberate — the failure it avoids is
     merging two people, and the failure it causes is leaving a row
     unresolved for a human to curate.
  3. The candidate's institution shares a DISTINCTIVE token with the
     affiliation on file — a proper noun or domain word, never "research",
     "university" or "national". distinctive_tokens() exists because a
     character-similarity matcher in upstream cod-kmap once accepted
     Electric Power Research Institute as a NERR.
  4. Surviving candidates must not disagree. OpenAlex frequently holds
     several author records for one human — A. Randall Hughes has three,
     sharing one ORCID and holding 167, 2 and 1 works. Candidates sharing
     an ORCID collapse to the one with the most works. If two survivors
     carry DIFFERENT ORCIDs, that is genuine ambiguity and the row is left
     unresolved.

  5. The winner must not be a stub. An OpenAlex record with no ORCID and
     fewer than MIN_STUB_WORKS works is a disambiguation shard, not a
     person: "Andrew G. Dickson" resolved to a 2-work record named
     "A. DICKSON" in upstream cod-kmap before this rule existed, which
     would have attached two papers to a researcher with hundreds.

A row resolved this way is written with confidence 'medium', never 'high':
rules 1-3 are strong evidence, but they are not an identifier the source
itself asserted. Rows resolved from an identifier already on file stay
'high'.

Usage::

    python scripts/enrich_registry_identifiers.py --dry-run
    python scripts/enrich_registry_identifiers.py --hydrate-only
    python scripts/enrich_registry_identifiers.py --export-parquet
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openalex_auth  # noqa: E402
from enrich_people_orcid import normalize_facility_name  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]
TOPICS_CSV = ROOT / "schema" / "vocab" / "lto_openalex_topics.csv"
API = "https://api.openalex.org"
SLEEP = 0.05
# An OpenAlex author record with no ORCID and fewer than this many works is
# treated as a shard rather than a person (see rule 5 in
# resolve_by_name_and_institution).
MIN_STUB_WORKS = 5

AUTHOR_SELECT = ("id,display_name,orcid,ids,works_count,cited_by_count,"
                 "summary_stats,last_known_institutions,topics")

# Tokens that appear in so many organisation names that sharing one
# carries no evidence of being the same place. In upstream cod-kmap,
# "research" alone matched Electric Power Research Institute to a National
# Estuarine Research Reserve; "university" matched Minnesota to the Virgin
# Islands. Defined here (rather than imported) because this repo's
# enrich_people_orcid.py predates the distinctive-token matcher that fix
# produced upstream.
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
}


def distinctive_tokens(s: str) -> set[str]:
    """Tokens from a normalised org name that actually identify a place.

    Drops the generic vocabulary above and anything shorter than three
    characters, so what remains is proper nouns and domain-specific
    words: 'apalachicola', 'smithsonian', 'oceanography', 'chesapeake'.
    """
    return {t for t in normalize_facility_name(s).split()
            if len(t) >= 3 and t not in GENERIC_ORG_TOKENS}


def lto_topic_ids() -> set[str]:
    """The OpenAlex topic ids that define "output on the LTO topic set".

    Fails loudly when the vocabulary is missing or empty: every metric this
    script writes (lto_works_count, lto_share) is meaningless without it,
    and a silently-empty set would zero those columns across the registry.
    """
    if not TOPICS_CSV.exists():
        raise SystemExit(
            f"[error] LTO topic vocabulary not found: {TOPICS_CSV}\n"
            "        Expected a CSV with columns topic_id,label,notes. "
            "Create it before running this script.")
    with TOPICS_CSV.open() as fh:
        rows = csv.DictReader(l for l in fh if not l.startswith("#"))
        ids = {(r.get("topic_id") or "").strip() for r in rows
               if (r.get("topic_id") or "").strip()}
    if not ids:
        raise SystemExit(
            f"[error] LTO topic vocabulary is empty: {TOPICS_CSV}\n"
            "        lto_works_count / lto_share cannot be computed from "
            "an empty topic set.")
    return ids


def norm(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(s or "").replace("‐", "-"))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def split_name(full: str) -> tuple[list[str], str]:
    parts = [p for p in re.split(r"\s+", norm(full)) if p and p not in {"jr", "iii", "ii"}]
    if len(parts) < 2:
        return [], (parts[0] if parts else "")
    return parts[:-1], parts[-1]


def given_compatible(a_given: list[str], b_given: list[str]) -> bool:
    """True when two given-name lists could name the same person.

    Compares position by position; an initial matches a spelled-out name
    with the same first letter, but two spelled-out names must be equal.
    That is what keeps 'Y. Stacy Zhang' and 'Y. Joseph Zhang' apart.
    """
    if not a_given or not b_given:
        return False
    for x, y in zip(a_given, b_given):
        x, y = x.rstrip("."), y.rstrip(".")
        if not x or not y:
            return False
        if len(x) == 1 or len(y) == 1:
            if x[0] != y[0]:
                return False
        elif x != y:
            return False
    return True


def short_id(v) -> str | None:
    if not v:
        return None
    return str(v).rstrip("/").rsplit("/", 1)[-1] or None


def author_fields(a: dict, lto_topics: set[str]) -> dict:
    """Flatten an OpenAlex author payload into registry columns."""
    stats = a.get("summary_stats") or {}
    insts = a.get("last_known_institutions") or []
    inst = insts[0] if insts else {}
    topics = a.get("topics") or []
    # OpenAlex lists a work under every topic it carries, so this sum
    # counts a multi-topic paper once per LTO topic (first noted in
    # upstream cod-kmap's harvest_coastal_authors.flatten()). Clamp to
    # works_count so the derived share cannot exceed 1.0.
    lw_topic_hits = sum(t.get("count", 0) for t in topics
                        if short_id(t.get("id")) in lto_topics)
    works = a.get("works_count") or 0
    lw = min(lw_topic_hits, works) if works else lw_topic_hits
    ids = a.get("ids") or {}
    return dict(
        openalex_id=short_id(a.get("id")),
        orcid=short_id(a.get("orcid")),
        google_scholar_id=short_id(ids.get("scholar")) if ids.get("scholar") else None,
        homepage_url=ids.get("homepage") or None,
        affiliation=inst.get("display_name"),
        affiliation_ror=short_id(inst.get("ror")) if inst.get("ror") else None,
        affiliation_country=inst.get("country_code"),
        works_count=works or None,
        cited_by_count=a.get("cited_by_count"),
        h_index=stats.get("h_index"),
        i10_index=stats.get("i10_index"),
        two_yr_mean_citedness=stats.get("2yr_mean_citedness"),
        lto_works_count=lw or None,
        lto_share=round(lw / works, 4) if works else None,
    )


def fetch_author(sess, *, oa_id=None, orcid=None) -> dict | None:
    if oa_id:
        r = sess.get(f"{API}/authors/{oa_id}", params={"select": AUTHOR_SELECT},
                     timeout=40)
        if r.ok:
            return r.json()
    if orcid:
        r = sess.get(f"{API}/authors",
                     params={"filter": f"orcid:{orcid}", "per_page": 1,
                             "select": AUTHOR_SELECT}, timeout=40)
        if r.ok:
            hits = r.json().get("results") or []
            if hits:
                return hits[0]
    return None


def resolve_by_name_and_institution(sess, name: str, affiliation: str,
                                    ) -> tuple[dict | None, str]:
    """Rules 1-4. Returns (author_json_or_None, decision)."""
    if not affiliation:
        return None, "no-affiliation"
    aff_tokens = distinctive_tokens(affiliation)
    if not aff_tokens:
        return None, "affiliation-too-generic"

    r = sess.get(f"{API}/authors",
                 params={"search": name, "per_page": 25,
                         "select": AUTHOR_SELECT}, timeout=40)
    if not r.ok:
        return None, f"http-{r.status_code}"
    cands = r.json().get("results") or []
    if not cands:
        return None, "no-candidates"

    want_given, want_family = split_name(name)
    verified = []
    for a in cands:
        got_given, got_family = split_name(a.get("display_name") or "")
        if got_family != want_family:
            continue                                    # rule 1
        if not given_compatible(want_given, got_given):
            continue                                    # rule 2
        insts = [i.get("display_name", "")
                 for i in (a.get("last_known_institutions") or [])]
        if not any(distinctive_tokens(i) & aff_tokens for i in insts):
            continue                                    # rule 3
        verified.append(a)

    if not verified:
        return None, "no-institution-match"

    # Rule 4. Collapse OpenAlex's duplicate records for one human: same
    # ORCID means same person, so keep the fullest record.
    orcids = {short_id(a.get("orcid")) for a in verified if a.get("orcid")}
    if len(orcids) > 1:
        return None, "ambiguous-conflicting-orcids"
    if len(verified) > 1 and not orcids:
        # Several institution-verified records, none with an ORCID to prove
        # they are the same person. Could be one human split across records,
        # could be two colleagues who share a name at one institution.
        return None, "ambiguous-no-orcid"
    verified.sort(key=lambda a: a.get("works_count") or 0, reverse=True)
    best = verified[0]

    # Rule 5: reject a stub. OpenAlex holds sparse duplicate records — a
    # one- or two-work shard of a real author's output, sometimes under an
    # initialised name. 'Andrew G. Dickson' resolved to a record named
    # 'A. DICKSON' with 2 works this way in upstream cod-kmap, which would
    # have attached two papers to a researcher with hundreds and then
    # ranked him near the bottom of the roster. A record too thin to have
    # earned an ORCID and too thin to be the person's real output is not
    # evidence of identity.
    if not best.get("orcid") and (best.get("works_count") or 0) < MIN_STUB_WORKS:
        return None, "stub-record"
    return best, "resolved"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--hydrate-only", action="store_true",
                    help="skip name+institution resolution of unidentified rows")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--export-parquet", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    openalex_auth.require_api_key()
    sess = openalex_auth.openalex_session()
    conn = duckdb.connect(str(args.db))
    lto_topics = lto_topic_ids()
    today = date.today().isoformat()
    prov: list[list] = []

    # ── hydrate rows that already have an identifier ───────────────────
    rows = conn.execute(
        "SELECT canonical_id, display_name, orcid, openalex_id "
        "FROM person_registry "
        "WHERE (orcid IS NOT NULL AND orcid <> '') "
        "   OR (openalex_id IS NOT NULL AND openalex_id <> '') "
        "ORDER BY display_name").fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"[hydrate] {len(rows)} registry row(s) with an identifier")
    hydrated = 0
    for i, (cid, name, orcid, oa_id) in enumerate(rows, 1):
        a = fetch_author(sess, oa_id=oa_id, orcid=orcid)
        time.sleep(SLEEP)
        if not a:
            continue
        f = author_fields(a, lto_topics)
        # Never let hydration overwrite an ORCID already on file — if
        # OpenAlex disagrees, that is a finding to inspect, not to apply.
        if orcid and f["orcid"] and f["orcid"] != orcid:
            prov.append([cid, "orcid-conflict", f["orcid"], "openalex-author-record",
                         f"OpenAlex author {f['openalex_id']} reports ORCID "
                         f"{f['orcid']} but the registry holds {orcid}; not applied",
                         f"{API}/authors/{f['openalex_id']}", "low", today])
            f.pop("orcid")
        sets, vals = [], []
        for k, v in f.items():
            if v is None:
                continue
            sets.append(f"{k} = COALESCE({k}, ?)" if k in
                        ("orcid", "openalex_id", "google_scholar_id", "homepage_url")
                        else f"{k} = ?")
            vals.append(v)
        if not sets:
            continue
        if not args.dry_run:
            conn.execute(f"UPDATE person_registry SET {', '.join(sets)} "
                         f"WHERE canonical_id = ?", vals + [cid])
        hydrated += 1
        prov.append([cid, "hydrate", f.get("openalex_id"), "openalex-author-record",
                     f"metrics + affiliation from OpenAlex author record",
                     f"{API}/authors/{f.get('openalex_id')}", "high", today])
        if i % 50 == 0:
            print(f"  [hydrate] {i}/{len(rows)}")
    print(f"[hydrate] filled {hydrated} row(s)")

    if args.hydrate_only:
        _finish(conn, prov, args)
        return 0

    # ── resolve the rows that have no identifier at all ────────────────
    # These never entered person_registry (it requires an identifier), so
    # they are read back from the source table. lto has one such source —
    # `people`, the facility-staff cohort (is_site_personnel); the
    # field-wide scholar harvest arrives with identifiers by construction.
    unresolved = conn.execute("""
        SELECT 'people' AS src, p.person_id AS sid, p.name,
               (SELECT string_agg(DISTINCT f.canonical_name, '; ')
                  FROM facility_personnel fp JOIN facilities f USING (facility_id)
                 WHERE fp.person_id = p.person_id) AS affiliation
        FROM people p
        WHERE (p.orcid IS NULL OR p.orcid = '') AND (p.openalex_id IS NULL OR p.openalex_id = '')
        ORDER BY 3
    """).fetchall()
    if args.limit:
        unresolved = unresolved[:args.limit]
    print(f"\n[resolve] {len(unresolved)} row(s) with no persistent identifier")

    decisions: dict[str, int] = {}
    found: list[tuple] = []
    for i, (src, sid, name, aff) in enumerate(unresolved, 1):
        a, decision = resolve_by_name_and_institution(sess, name, aff or "")
        time.sleep(SLEEP)
        decisions[decision] = decisions.get(decision, 0) + 1
        if decision == "resolved" and a:
            f = author_fields(a, lto_topics)
            found.append((src, sid, name, aff, f))
        if i % 50 == 0:
            print(f"  [resolve] {i}/{len(unresolved)}  {decisions}")

    print(f"[resolve] {decisions}")
    print(f"[resolve] {len(found)} row(s) gained an identifier")

    if not args.dry_run and found:
        for src, sid, name, aff, f in found:
            conn.execute(
                "UPDATE people SET orcid = COALESCE(orcid, ?), "
                "openalex_id = COALESCE(openalex_id, ?) WHERE person_id = ?",
                [f.get("orcid"), f.get("openalex_id"), sid])
            cid = (f"orcid:{f['orcid']}" if f.get("orcid")
                   else f"openalex:{f['openalex_id']}")
            prov.append([cid, "resolve", f.get("openalex_id"),
                         "name+institution-verified",
                         f"{src} row '{name}' matched OpenAlex author "
                         f"'{f.get('openalex_id')}' on exact family name, "
                         f"compatible given names, and a shared distinctive "
                         f"institution token against '{(aff or '')[:60]}'",
                         f"{API}/authors/{f.get('openalex_id')}", "medium", today])
        print("[resolve] wrote identifiers back to the source table — "
              "re-run scripts/build_person_registry.py to fold them in")

    _finish(conn, prov, args)
    return 0


def _finish(conn, prov, args) -> None:
    if prov and not args.dry_run:
        conn.executemany(
            "INSERT INTO person_identity_source (canonical_id, field, value, "
            "method, evidence, source_url, confidence, retrieved_at) "
            "VALUES (?,?,?,?,?,?,?,?)", prov)
        print(f"[provenance] +{len(prov)} assertion(s)")
    if args.export_parquet and not args.dry_run:
        for base in PARQUET_OUT:
            base.mkdir(parents=True, exist_ok=True)
            for t in ("person_registry", "person_identity_source", "people"):
                conn.execute(f"COPY {t} TO '{base / (t + '.parquet')}' (FORMAT PARQUET)")
            print(f"[parquet] refreshed {base}")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
