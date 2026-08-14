#!/usr/bin/env python3
"""Resolve facilities.ror against api.ror.org — the H10 backfill step.

`link_registry_facilities.py` pass 1 already resolves facility RORs, but
through OpenAlex /institutions, which needs OPENALEX_API_KEY and spends
the daily harvest quota on it. ROR's own API needs no credential and is
the authoritative source for the identifier, so it runs first; whatever
it cannot resolve is left for the OpenAlex fallback in that script.

Matching is deliberately strict — a wrong ROR silently mis-joins every
researcher at that site, which is worse than a null. A candidate must
first clear two gates: the ROR record status is 'active' (withdrawn
records keep resolving) and its country_code equals the facility's ISO-2
country. It is then scored on distinctive tokens (the same
generic-token-stripped vocabulary the ORCID matcher uses — see
GENERIC_ORG_TOKENS in link_registry_facilities.py) shared with the
facility name, across the record's display name AND its aliases: ROR
files Hubbard Brook under 'Hubbard Brook Long Term Ecological Research',
which an exact-name test would miss.

Each successive rule here was bought with a false positive from a real
run of the previous version, which is why they look over-specified:

  1. **≥2 shared tokens** (or full coverage, or a declared-acronym match
     plus one). One was enough to match 'ACE Basin NERR' to 'Arkansas
     Department of Career Education' via the alias 'ACE'.
  2. **Acronym-shaped name values excluded** from the token test —
     see (1) — and the facility acronym may only meet a record's
     *declared* acronym. Even then it is corroboration, not proof:
     'Beaufort Lagoon LTER' matched the LTER Network on 'LTER' alone.
  3. **Head-token rule**: the facility's leading distinctive token must
     be among the shared ones, or the match is a parent that shares the
     tail — 'Cape Lisburne Coast Guard / NSIDC Sea-Ice Site' shares
     'coast' and 'guard' with the United States Coast Guard.
  4. **No extra distinctive token on the ROR display name.** This is the
     symmetric test, and the one that catches a *different organisation
     at the same place*: Wells NERR → Wells Fargo, Point Reyes National
     Seashore → Point Blue Conservation Science, Great Bay NERR → Great
     Bay Stewards, and every regional USDA Climate Hub → the California
     hub. Aliases are exempt — they exist to catch old and local names.
  5. **Parent-org rule**: a facility that names a role (station, site,
     reserve, forest, …) needs a candidate that names one too, or
     'University of Kansas Field Station' resolves to the University of
     Kansas and mis-joins every KU researcher to the field station.

Ties are broken by coverage; two candidates at the same best coverage is
an ambiguity, recorded and written nowhere. Rules 4 and 5 cost real
recall — Konza Prairie and Bonanza Creek both have correct RORs that
rule 5 declines — and that is the intended trade: everything that clears
the gates but not the bar is recorded as 'review-<reason>' WITH its best
candidate, so a near miss is a row a human can promote from the log
rather than a silent no-match.

Only research organisations are attempted; places (protected areas,
streamgages, flux towers) hold no ROR by design. Both type sets are
imported from link_registry_facilities so the two steps can never drift
apart, and --include-type overrides the skip for a one-off run.

Every decision — match, no-match, ambiguity — lands in
data/seed/facility_ror_decisions.csv, which is the reviewable artifact;
the DB write is just the accepted subset. Idempotent: facilities that
already carry a ROR are never re-queried or overwritten.

Usage::

    python scripts/backfill_facility_ror.py --dry-run
    python scripts/backfill_facility_ror.py
    python scripts/backfill_facility_ror.py --include-type experimental-forest-range
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import date
from pathlib import Path

import duckdb
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from link_registry_facilities import (  # noqa: E402
    PLACE_TYPES, RESEARCH_TYPES, distinctive_tokens, normalize_facility_name,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
DECISION_LOG = ROOT / "data" / "seed" / "facility_ror_decisions.csv"
API = "https://api.ror.org/v2/organizations"
UA = "lto/0.2 (+https://github.com/tyson-swetnam/lto)"
SLEEP = 0.3          # ROR asks for a courteous rate; 2000 req/5 min is the cap
MAX_CANDIDATES = 5

# Words that name what a site IS. They carry no identifying force on their
# own — all of them are in GENERIC_ORG_TOKENS and get stripped before the
# token test — but their ABSENCE on the ROR side is informative: a record
# that names no role while the facility names one is usually the parent
# organisation rather than the site (see the parent-org gate in resolve()).
ROLE_WORDS = {
    "station", "site", "reserve", "refuge", "sanctuary", "monument",
    "seashore", "preserve", "forest", "farm", "park", "observatory",
    "laboratory", "lab", "institute", "center", "centre", "hub",
}

# Words that name a *legal form*, and the one place where the shared
# normalizer actively works against us: normalize_facility_name() drops
# 'institute' and 'foundation' outright and GENERIC_ORG_TOKENS treats
# 'association' as noise, so the friends-of nonprofit beside a reserve
# normalises to the same string as the reserve. That is how Elkhorn
# Slough NERR resolved to the Elkhorn Slough Foundation, the NERR System
# to the NERR Association, and the San Francisco Estuary Partnership to
# the San Francisco Estuary Institute — three different organisations,
# three RORs that would have carried other people's researchers. This
# test therefore runs on the RAW names, not the normalised ones.
ORG_FORM_WORDS = {
    "foundation", "institute", "association", "society", "coalition",
    "alliance", "trust", "fund", "friends", "stewards", "conservancy",
    "partnership", "commission", "council", "corporation", "company",
    "university", "college", "aquarium", "museum", "hospital",
}


def names_by_type(item: dict) -> tuple[str, set[str], set[str]]:
    """(display name, all name values, acronyms) from a ROR v2 record.

    v2 has no `name` field: names[] entries carry a types[] list, and the
    display name is the entry typed 'ror_display'. Do not "simplify" this
    to item['name'] — that is v1 and returns None.
    """
    display, values, acronyms = "", set(), set()
    for n in item.get("names") or []:
        val = (n.get("value") or "").strip()
        if not val:
            continue
        types = n.get("types") or []
        values.add(val)
        if "ror_display" in types:
            display = val
        if "acronym" in types:
            acronyms.add(val.upper())
    return display or next(iter(values), ""), values, acronyms


def country_of(item: dict) -> str | None:
    for loc in item.get("locations") or []:
        cc = (loc.get("geonames_details") or {}).get("country_code")
        if cc:
            return cc.upper()
    return None


def record_tokens(values: set[str]) -> set[str]:
    """Distinctive tokens over a record's names, acronym forms excluded.

    'ACE' as an alias of Arkansas Dept of Career Education is a token
    collision waiting to happen with ACE Basin NERR; an acronym only
    identifies an organisation when it is compared against another
    declared acronym, which is what the acronym gate below does.
    """
    out: set[str] = set()
    for v in values:
        if len(v) < 4 or v.isupper():
            continue
        out |= distinctive_tokens(v)
    return out


def raw_words(s: str) -> set[str]:
    """Lowercased words, punctuation dropped, nothing else removed.

    Deliberately not normalize_facility_name(): the whole point of the
    org-form test is to see the words that normalizer throws away.
    """
    return set(re.findall(r"[a-z]+", (s or "").lower()))


def head_token(name: str) -> str | None:
    """The facility name's leading distinctive token, or None.

    In this catalogue the head noun is what identifies the site —
    'Bonanza' in Bonanza Creek LTER, 'Cedar' in Cedar Creek Ecosystem
    Science Reserve. Requiring it among the shared tokens is what
    separates a real match from a parent organisation that happens to
    share the tail: 'Cape Lisburne Coast Guard / NSIDC Sea-Ice Site'
    shares 'coast' and 'guard' with the United States Coast Guard — two
    tokens, enough for the count test, and a ROR that would mis-join
    every USCG researcher to an Alaskan sea-ice site.
    """
    want = distinctive_tokens(name)
    for t in normalize_facility_name(name).split():
        if t in want:
            return t
    return None


def search_query(name: str) -> str:
    """Facility name reshaped into something ROR's query parser accepts.

    '/' and '#' make the endpoint answer 500 ('Blandy Experimental Farm /
    State Arboretum of Virginia'), and a parenthetical is a second name
    rather than more of the first, so it only dilutes the search.
    """
    q = re.sub(r"\([^)]*\)", " ", name)
    q = re.sub(r"[/#\"]", " ", q)
    return re.sub(r"\s+", " ", q).strip() or name


def resolve(sess, name: str, acronym: str | None, country: str | None):
    """→ (ror_id | None, matched_display_name, decision)."""
    want = distinctive_tokens(name)
    if not want and not acronym:
        return None, "", "name-too-generic"
    query = search_query(name)
    # ROR answers a small fraction of queries with a 500 (seen on names
    # carrying '/'); one retry clears it and keeps the row out of the
    # log as a spurious failure.
    r = None
    for attempt in (1, 2):
        try:
            r = sess.get(API, params={"query": query}, timeout=40)
        except requests.RequestException as e:
            if attempt == 2:
                return None, "", f"error-{type(e).__name__}"
            time.sleep(2)
            continue
        if r.ok or r.status_code < 500 or attempt == 2:
            break
        time.sleep(2)
    if not r.ok:
        return None, "", f"http-{r.status_code}"
    return judge(name, acronym, country, r.json().get("items") or [])


def judge(name: str, acronym: str | None, country: str | None, items: list):
    """Decide a facility's ROR from ROR's candidate records.

    Split out from the fetch so every rule above is exercisable without a
    network — see scripts/test_backfill_facility_ror.py, which pins each
    false positive that bought a rule.
    """
    want = distinctive_tokens(name)
    # (ror, display, shared tokens, why) for every candidate past the gates.
    scored: list[tuple[str, str, set[str], str]] = []
    for item in items[:MAX_CANDIDATES]:
        if (item.get("status") or "active") != "active":
            continue
        cc = country_of(item)
        # Country equality is the cheapest guard against the classic
        # false match (a same-named institute on another continent).
        if country and cc and cc != country.upper():
            continue
        rid = (item.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
        if not rid:
            continue
        display, values, acronyms = names_by_type(item)
        shared = record_tokens(values) & want
        if acronym and acronym.upper() in acronyms:
            scored.append((rid, display, shared, "acronym-match"))
        elif shared:
            scored.append((rid, display, shared, "name-token-match"))

    if not scored:
        return None, "", "no-match"

    def strength(c):
        rid, display, shared, why = c
        return (shared == want, len(shared), why == "acronym-match")

    scored.sort(key=strength, reverse=True)
    rid, display, shared, why = scored[0]
    # A declared-acronym hit is corroboration, never proof on its own:
    # 'Beaufort Lagoon LTER' matched the *LTER Network* record on the
    # acronym 'LTER' while sharing not one distinctive token with it.
    head = head_token(name)
    if head is not None and head not in shared:
        return None, display, "review-head-token-missing"
    if not (shared == want or len(shared) >= 2
            or (why == "acronym-match" and len(shared) >= 1)):
        reason = ("acronym-only" if why == "acronym-match"
                  else f"weak-{len(shared)}-token")
        return None, display, f"review-{reason}"
    # Symmetric gate. Everything above asks "does the ROR record cover the
    # facility name?", which a *different organisation at the same place*
    # passes trivially: Wells NERR → Wells Fargo, Point Reyes National
    # Seashore → Point Blue Conservation Science, Great Bay NERR → Great
    # Bay Stewards, and every regional USDA Climate Hub → the California
    # hub. What separates those from a true match is a distinctive token
    # on the ROR side that the facility name never mentions ('fargo',
    # 'blue', 'stewards', 'california'), so the candidate's distinctive
    # tokens must all be accounted for by the facility's.
    # Aliases are allowed to be noisy (they exist to catch old and local
    # names); it is the display name that states what the record IS, so
    # the extra-token test runs on that alone.
    extra = distinctive_tokens(display) - want
    if extra:
        return None, display, "review-extra-token-" + "-".join(sorted(extra)[:2])
    # The mirror-image failure: the candidate covers nothing the facility
    # says beyond its place name, because it IS the parent organisation —
    # 'University of Kansas Field Station' → University of Kansas, whose
    # ROR would mis-join every KU researcher to the field station. A
    # facility that names a role (station, site, reserve, forest, …) needs
    # a candidate that names one too.
    fac_roles = ROLE_WORDS & set(normalize_facility_name(name).split())
    cand_roles = ROLE_WORDS & set(normalize_facility_name(display).split())
    if fac_roles and not cand_roles:
        return None, display, "review-parent-org"
    form = (ORG_FORM_WORDS & raw_words(display)) - raw_words(name)
    if form:
        return None, display, "review-org-form-" + "-".join(sorted(form))
    rivals = [c for c in scored[1:] if strength(c) == strength(scored[0])]
    if rivals:
        return None, "; ".join([display] + [c[1] for c in rivals]), "ambiguous"
    return rid, display, why


def apply_log(conn, dry_run: bool) -> int:
    """Write the RORs a reviewer promoted in the decision log.

    The matcher's job is to propose; a human's job is to decide the ones
    it declined. Editing a row's `decision` to 'accept' (its `ror` column
    filled in, by hand if the matcher left it empty) and re-running with
    --apply-log is that decision. Facilities that already carry a ROR are
    still never overwritten — clear the column first if a stored ROR is
    the thing being corrected.
    """
    if not DECISION_LOG.exists():
        print(f"[ror] no decision log at {DECISION_LOG}", file=sys.stderr)
        return 2
    with DECISION_LOG.open(encoding="utf-8") as fh:
        promoted = [(r["ror"].rstrip("/").rsplit("/", 1)[-1], r["facility_id"],
                     r["canonical_name"])
                    for r in csv.DictReader(fh)
                    if r.get("decision", "").strip().lower() == "accept"
                    and r.get("ror", "").strip()]
    if not promoted:
        print("[ror] no rows marked 'accept' in the decision log")
        return 0
    for rid, fid, name in promoted:
        print(f"[ror] accept {name[:50]:50s} → {rid}")
    if not dry_run:
        conn.executemany(
            "UPDATE facilities SET ror = ? WHERE facility_id = ? "
            "AND (ror IS NULL OR ror = '')",
            [(rid, fid) for rid, fid, _ in promoted])
    print(f"[ror] {len(promoted)} promoted ROR(s) applied"
          + (" (dry run — nothing written)" if dry_run else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-type", action="append", default=[],
                    metavar="SLUG",
                    help="treat this facility_type as a research organisation "
                         "for this run (repeatable)")
    ap.add_argument("--apply-log", action="store_true",
                    help="write the RORs a human promoted in the decision "
                         "log (decision edited to 'accept') and make no API "
                         "calls; this is how a review-* row lands")
    args = ap.parse_args()

    conn = duckdb.connect(str(args.db))
    if args.apply_log:
        return apply_log(conn, args.dry_run)
    research_types = RESEARCH_TYPES | set(args.include_type)
    types = ",".join(f"'{t}'" for t in sorted(research_types))
    targets = conn.execute(f"""
        SELECT facility_id, canonical_name, acronym, facility_type, country
        FROM facilities
        WHERE facility_type IN ({types}) AND (ror IS NULL OR ror = '')
        ORDER BY canonical_name""").fetchall()
    have = conn.execute(
        "SELECT count(*) FROM facilities WHERE ror IS NOT NULL AND ror <> ''"
    ).fetchone()[0]

    # Report the skip BY TYPE, never as a bare number: a research
    # organisation missing from RESEARCH_TYPES reads exactly like "the
    # protected areas" in a single count. (That is how Ocean Networks
    # Canada went unresolved upstream.)
    skipped_by_type = conn.execute(f"""
        SELECT facility_type, COUNT(*) FROM facilities
        WHERE facility_type NOT IN ({types}) AND (ror IS NULL OR ror = '')
        GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    unclassified = [(t, n) for t, n in skipped_by_type if t not in PLACE_TYPES]
    print(f"[ror] {len(targets)} facility/ies to resolve; {have} already have a ROR; "
          f"{sum(n for _, n in skipped_by_type):,} skipped as places")
    if unclassified:
        print(f"[ror] NOTE: skipped types not in PLACE_TYPES: {unclassified} — "
              "if any names an organisation rather than a place, add it to "
              "RESEARCH_TYPES (or pass --include-type)")
    if args.limit:
        targets = targets[:args.limit]

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    today = date.today().isoformat()
    rows, accepted, decisions = [], [], {}
    name_of = {fid: name for fid, name, *_ in targets}
    # RORs already on other facilities count as claimants too — an
    # imported ROR and a freshly resolved one can collide.
    for stored_ror, stored_name in conn.execute(
            "SELECT ror, canonical_name FROM facilities "
            "WHERE ror IS NOT NULL AND ror <> ''").fetchall():
        name_of.setdefault(f"stored:{stored_ror}", stored_name)

    for i, (fid, name, acro, ftype, country) in enumerate(targets, 1):
        rid, matched, why = resolve(sess, name, acro, country)
        decisions[why] = decisions.get(why, 0) + 1
        rows.append({
            "facility_id": fid, "canonical_name": name,
            "facility_type": ftype, "country": country,
            "ror": rid or "", "matched_name": matched,
            "decision": why, "retrieved_at": today,
        })
        if rid:
            accepted.append((rid, fid))
        if i % 25 == 0 or i == len(targets):
            print(f"[ror] {i}/{len(targets)}", flush=True)
        time.sleep(SLEEP)

    # A ROR names ONE organisation, so two facilities claiming the same one
    # is either two catalogue rows for the same place ('Jones Center at
    # Ichauway' and its NEON site) or a false match. Head-token equality
    # separates them: same head noun, same place — anything else is the
    # Monterey-Bay-Aquarium-vs-MBARI collision the sibling script was
    # burned by, and neither claimant is written.
    by_ror: dict[str, list[tuple[str, str]]] = {}
    for rid, fid in accepted:
        by_ror.setdefault(rid, []).append((fid, name_of[fid]))
    for key, nm in name_of.items():
        if key.startswith("stored:") and key[7:] in by_ror:
            by_ror[key[7:]].append((key, nm))
    dropped: set[tuple[str, str]] = set()
    for rid, claims in by_ror.items():
        if len(claims) < 2:
            continue
        heads = {head_token(n) for _, n in claims}
        same_place = len(heads) == 1 and None not in heads
        print(f"[ror] COLLISION {rid}: {[n for _, n in claims]} — "
              + ("same place, both kept" if same_place
                 else "different places, neither written"))
        if not same_place:
            dropped |= {(rid, fid) for fid, _ in claims}
    if dropped:
        accepted = [c for c in accepted if c not in dropped]
        for row in rows:
            if (row["ror"], row["facility_id"]) in dropped:
                row["decision"] = "review-ror-collision"
                row["ror"] = ""

    if not args.dry_run and accepted:
        conn.executemany(
            "UPDATE facilities SET ror = ? WHERE facility_id = ? "
            "AND (ror IS NULL OR ror = '')", accepted)

    # The decision log is append-only across runs: a facility that failed
    # to resolve last month and resolves today should show both, so the
    # reviewer can see what changed rather than only the current answer.
    if not args.dry_run and rows:
        DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        exists = DECISION_LOG.exists()
        with DECISION_LOG.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            if not exists:
                w.writeheader()
            w.writerows(rows)
        print(f"[ror] decisions → {DECISION_LOG.relative_to(ROOT)}")

    print(f"[ror] {len(accepted)} ROR(s) resolved "
          + ("(dry run — nothing written)" if args.dry_run else "")
          + f"\n[ror] decisions: {dict(sorted(decisions.items(), key=lambda kv: -kv[1]))}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
