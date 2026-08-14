#!/usr/bin/env python3
"""Search ORCID public API for each person and attach the match.

Strict resolver — ANY mismatch means we leave orcid NULL rather than
risk the OpenAlex name-only debacle. See docs/orcid_enrichment_plan.md
for design rationale.

Acceptance rules (ALL must hold):
  1. Family name matches exactly (case + diacritic-insensitive).
  2. Given names match the first one (handles "Sarah" vs "Sarah J.").
  3. Candidate's employment list contains an organisation that shares at
     least one DISTINCTIVE token with one of the person's facilities
     (proper nouns and domain words — never "research", "university",
     "national"), scoring >= --min-conf on that shared-token overlap.

When the person has no facility on file, rule 3 cannot be applied and a
match is accepted only if the name resolves to exactly one ORCID; two or
more namesakes are logged `ambiguous-name-only` and left null.

Logs every decision to data/seed/orcid_resolution_log.csv for audit.

Usage::
    python scripts/enrich_people_orcid.py --db db/lto.duckdb
    python scripts/enrich_people_orcid.py --batch 25
    python scripts/enrich_people_orcid.py --min-conf 0.80
    python scripts/enrich_people_orcid.py --dry-run
    python scripts/enrich_people_orcid.py --only-missing  (default)
    python scripts/enrich_people_orcid.py --reverify      (re-check existing orcids)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import duckdb
try:
    import requests
except ImportError:
    print("[error] pip install requests --break-system-packages", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
LOG_CSV = ROOT / "data" / "seed" / "orcid_resolution_log.csv"

API_SEARCH = "https://pub.orcid.org/v3.0/expanded-search/"
API_EMPLOY = "https://pub.orcid.org/v3.0/{orcid}/employments"
API_EDU    = "https://pub.orcid.org/v3.0/{orcid}/educations"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "cod-kmap/0.1 (github.com/tyson-swetnam/cod-kmap; "
        "mailto:tswetnam@arizona.edu)"
    )
    s.headers["Accept"] = "application/json"
    return s


def norm(s: str) -> str:
    """Lowercase + strip diacritics for tolerant name matching."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def split_name(full: str) -> tuple[str, str]:
    parts = re.split(r"\s+", (full or "").strip())
    if len(parts) < 2:
        return parts[0] if parts else "", ""
    return " ".join(parts[:-1]), parts[-1]


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def search_orcid(sess: requests.Session, given: str, family: str
                 ) -> list[dict]:
    """Returns up to 25 candidate ORCID profiles. Tries TWO queries
    and merges results — Lucene-style fielded search is very strict
    in expanded-search and frequently returns 0 hits even when an
    obvious profile exists. The fallback uses the open-text 'q'
    parameter which behaves like the orcid.org website search."""
    if not family:
        return []
    seen_orcids: set[str] = set()
    out: list[dict] = []

    def _push(rows):
        for c in rows:
            oid = c.get("orcid-id") or ""
            if oid and oid not in seen_orcids:
                seen_orcids.add(oid)
                out.append(c)

    queries = []
    # Q1: fielded — strict but exact.
    if given:
        first = given.split()[0]
        queries.append(f'family-name:"{family}" AND given-names:{first}*')
    else:
        queries.append(f'family-name:"{family}"')
    # Q2: open-text — much more permissive, mirrors website behavior.
    queries.append(f'"{given} {family}"'.strip())
    # Q3: bare last-name only — last resort for unusual given-name spellings.
    queries.append(f'family-name:"{family}"')

    for q in queries:
        try:
            r = sess.get(API_SEARCH, params={"q": q, "rows": 25}, timeout=20)
        except Exception as e:
            print(f"[warn] orcid search failed for {q}: {e}")
            continue
        if r.status_code == 429:
            time.sleep(2)
            continue
        if not r.ok:
            continue
        try:
            _push(r.json().get("expanded-result", []) or [])
        except Exception:
            continue
        if len(out) >= 12:
            break
    return out


def fetch_employments(sess: requests.Session, orcid: str) -> list[str]:
    """List of organisation-names from employments + educations."""
    out: list[str] = []
    for url in (API_EMPLOY.format(orcid=orcid), API_EDU.format(orcid=orcid)):
        try:
            r = sess.get(url, timeout=20)
            if r.status_code == 429:
                time.sleep(2)
                r = sess.get(url, timeout=20)
            if not r.ok:
                continue
            j = r.json()
        except Exception as e:
            print(f"[warn] fetch employments failed for {orcid}: {e}")
            continue
        groups = j.get("affiliation-group", []) or []
        for g in groups:
            for s in g.get("summaries", []) or []:
                summary = (s.get("employment-summary")
                           or s.get("education-summary")
                           or s.get("qualification-summary")
                           or {})
                org = (summary.get("organization") or {}).get("name")
                if org:
                    out.append(org)
    return out


def normalize_facility_name(s: str) -> str:
    """Aggressively normalize a facility name for fuzzy matching:
       lowercase, drop common suffix words, expand the obvious acronyms,
       collapse whitespace. So 'NERR — Apalachicola NERR' and
       'Apalachicola National Estuarine Research Reserve' end up close.
    """
    if not s:
        return ""
    s = norm(s)
    # Drop the acronym—long-name separator structure.
    s = s.replace("—", " ").replace("–", " ").replace("-", " ")
    # Expand abbreviations BEFORE stripping suffixes.
    expansions = [
        ("nerr",  "national estuarine research reserve"),
        ("nms",   "national marine sanctuary"),
        ("nep",   "national estuary program"),
        ("ltreb", "long term research environmental biology"),
        ("lter",  "long term ecological research"),
        ("nps",   "national park service"),
        ("noaa",  "national oceanic atmospheric administration"),
        ("ucsb",  "university california santa barbara"),
        ("usf",   "university south florida"),
        ("ucsd",  "university california san diego"),
        ("uw",    "university washington"),
        ("dfo",   "fisheries oceans canada"),
    ]
    for short, long in expansions:
        s = re.sub(rf'\b{short}\b', long, s)
    # Drop common suffix / connector words.
    drop = {'the', 'a', 'an', 'of', 'and', 'for', 'at', 'in', 'on',
            'institute', 'foundation', 'incorporated', 'inc', 'llc',
            'department', 'reserve', 'sanctuary'}
    toks = [t for t in re.split(r'\s+', s) if t and t not in drop]
    return ' '.join(toks)


# Tokens that appear in so many organisation names that sharing one
# carries no evidence of being the same place. "Research" alone matched
# Electric Power Research Institute to a National Estuarine Research
# Reserve; "university" matched Minnesota to the Virgin Islands.
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
    "technologies", "engineering", "college", "academy", "museum",
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


def token_overlap(a: str, b: str) -> float:
    """Jaccard-like similarity over token sets after normalisation. More
    forgiving than character-level SequenceMatcher when one string is
    much longer than the other (e.g. ORCID employment org has the full
    departmental name + city + country, our facility has just the lab
    name)."""
    ta = set(normalize_facility_name(a).split())
    tb = set(normalize_facility_name(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if not inter:
        return 0.0
    # Recall-weighted: the shorter of the two should be mostly in the
    # other for a strong match.
    return inter / max(min(len(ta), len(tb)), 1)


def best_facility_match(orgs: list[str], facilities: list[str],
                        min_conf: float) -> tuple[float, str, str]:
    """Returns (best_score, matched_org, matched_facility) or (-1,'','').

    A match REQUIRES at least one shared distinctive token — a proper
    noun or domain word, not "research"/"university"/"national". Only
    then is a similarity score computed, and the character-level
    SequenceMatcher is used solely as a tie-breaker, never on its own.

    The earlier version took max(SequenceMatcher, token_overlap) with no
    distinctive-token requirement. Character similarity between two
    normalised org names sits in the 0.51-0.67 band for unrelated
    organisations just as often as for the same one, so against the 0.45
    default it accepted, among others:

        Electric Power Research Institute  -> NERR        (0.560)
        Oklahoma Medical Research Fdn      -> LTER        (0.593)
        European Medicines Agency  -> Institute of Ocean Sciences (0.513)
        Appalachian State University       -> Apalachicola NERR (0.529)

    Each of those attaches a stranger's entire publication record to a
    coastal researcher — the failure mode wipe_bad_openalex_attributions.py
    already had to clean up once.
    """
    best = (-1.0, "", "")
    for org in orgs:
        org_toks = distinctive_tokens(org)
        if not org_toks:
            continue
        for fac in facilities:
            for variant in [fac, *fac.split(" — ")]:
                var_toks = distinctive_tokens(variant)
                shared = org_toks & var_toks
                if not shared:
                    continue
                # Recall-weighted over distinctive tokens only.
                s_tok = len(shared) / max(min(len(org_toks),
                                              len(var_toks)), 1)
                s_seq = SequenceMatcher(
                    None,
                    normalize_facility_name(org),
                    normalize_facility_name(variant),
                ).ratio()
                # Character similarity can only refine a decision the
                # distinctive tokens already support; it is averaged in
                # at a low weight rather than allowed to carry a match.
                s = 0.75 * s_tok + 0.25 * s_seq
                if s > best[0]:
                    best = (s, org, variant)
    return best if best[0] >= min_conf else (-1.0, "", "")


def resolve_one(sess, person, min_conf):
    """Returns (orcid_or_None, decision_dict)."""
    given, family = split_name(person["name"])
    if not family:
        return None, {"decision": "skip-no-family", "candidates": 0}
    candidates = search_orcid(sess, given, family)
    if not candidates:
        return None, {"decision": "no-candidates", "candidates": 0}

    facilities = person.get("facilities") or []
    accepted = []
    name_only: list[str] = []
    for c in candidates:
        cand_given = c.get("given-names") or ""
        cand_family = c.get("family-names") or ""
        # Rule 1: family name exact match.
        if norm(cand_family) != norm(family):
            continue
        # Rule 2: first given name matches.
        if given:
            cg_first = (cand_given.split() or [""])[0]
            if not cg_first:
                continue
            if norm(cg_first.split('.')[0])[:len(norm(given.split()[0]))] \
                    != norm(given.split()[0]):
                continue
        orcid = c.get("orcid-id") or ""
        if not orcid:
            continue
        # Rule 3: employment-name fuzzy matches a facility.
        if facilities:
            orgs = fetch_employments(sess, orcid)
            score, org, fac = best_facility_match(orgs, facilities, min_conf)
            if score < min_conf:
                continue
            accepted.append((orcid, score, org, fac))
        else:
            # No facility on file. The comment here used to promise
            # "only when there's exactly one candidate", but the code
            # appended every name-matching candidate and then took the
            # first after a sort where all of them scored 0.0 — i.e. an
            # arbitrary pick among namesakes. "David White" was accepted
            # this way out of 25 ORCID candidates, and "Christine
            # Angelini" out of 26. Collect them and enforce the promise
            # after the loop, where the count is known.
            name_only.append(orcid)

    if not accepted and name_only:
        # Distinct ORCIDs matching the same name with nothing to
        # discriminate them: unresolvable, so leave it null.
        uniq = sorted(set(name_only))
        if len(uniq) == 1:
            return uniq[0], {"decision": "accept-name-only",
                             "candidates": len(candidates),
                             "score": 0.0, "match_org": "",
                             "match_facility": ""}
        return None, {"decision": "ambiguous-name-only",
                      "candidates": len(candidates)}

    if not accepted:
        return None, {"decision": "no-employment-match",
                      "candidates": len(candidates)}
    # Pick highest score.
    accepted.sort(key=lambda x: -x[1])
    orcid, score, org, fac = accepted[0]
    return orcid, {
        "decision": "accept",
        "candidates": len(candidates),
        "score": round(score, 3),
        "match_org": org,
        "match_facility": fac,
    }


def export_parquet(conn):
    for base in PARQUET_OUT:
        base.mkdir(parents=True, exist_ok=True)
        out = base / "people.parquet"
        conn.execute(f"COPY people TO '{out}' (FORMAT PARQUET)")
        print(f"[parquet] wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--min-conf", type=float, default=0.45)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-missing", action="store_true", default=True)
    ap.add_argument("--reverify", action="store_true",
                    help="Re-check people who already have orcid; useful "
                         "after a refactor of the matching rules.")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))
    sess = session()

    # Build the work list — each person + the list of facility names
    # they're affiliated with (for employment-match).
    #
    # parent_org is a variant in its own right, and for LTO it is the one
    # that usually matches: site personnel are employed by the OPERATOR of
    # an observatory, not by the observatory. Alan K. Knapp's ORCID
    # employment says "Colorado State University", which shares no
    # distinctive token with "Konza Prairie Biological Station" — but does
    # with Konza's parent_org. A dry run without this variant rejected
    # 14/15 people as no-employment-match; upstream cod-kmap never hit
    # this because coastal researchers work for the labs that employ them.
    rows = conn.execute(f"""
        WITH facs AS (
          SELECT fp.person_id,
                 list_filter(
                   flatten(list(DISTINCT [
                     COALESCE(f.acronym || ' — ' || f.canonical_name,
                              f.canonical_name),
                     f.parent_org
                   ])),
                   x -> x IS NOT NULL AND x <> ''
                 ) AS facilities
          FROM   facility_personnel fp
          JOIN   facilities         f  ON f.facility_id = fp.facility_id
          GROUP  BY fp.person_id
        )
        SELECT p.person_id, p.name, p.orcid,
               COALESCE(facs.facilities, []) AS facilities
        FROM   people p
        LEFT JOIN facs ON facs.person_id = p.person_id
        WHERE  {"p.orcid IS NULL OR length(p.orcid) = 0" if not args.reverify else "TRUE"}
        ORDER BY p.name
    """).fetchall()

    people = [
        {"person_id": r[0], "name": r[1], "orcid": r[2],
         "facilities": list(r[3] or [])}
        for r in rows
    ]
    if args.batch:
        people = people[: args.batch]
    print(f"[orcid] processing {len(people)} people  "
          f"min-conf={args.min_conf}  dry-run={args.dry_run}")

    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    log_exists = LOG_CSV.exists()
    log = LOG_CSV.open("a", newline="", encoding="utf-8")
    log_w = csv.writer(log)
    if not log_exists:
        log_w.writerow([
            "person_id", "name", "decision", "orcid",
            "candidates", "score", "match_org", "match_facility",
        ])

    totals = {"accept": 0, "no-candidates": 0, "no-employment-match": 0,
              "skip-no-family": 0, "errors": 0}
    for i, p in enumerate(people, 1):
        try:
            orcid, info = resolve_one(sess, p, args.min_conf)
        except Exception as e:
            print(f"  [{i}/{len(people)}] {p['name']:30s} ERROR: {e}")
            totals["errors"] += 1
            continue
        log_w.writerow([
            p["person_id"], p["name"], info["decision"], orcid or "",
            info.get("candidates", 0), info.get("score", ""),
            info.get("match_org", ""), info.get("match_facility", ""),
        ])
        totals[info["decision"]] = totals.get(info["decision"], 0) + 1
        msg = orcid or "—"
        print(f"  [{i}/{len(people)}] {p['name']:30s} {info['decision']:25s} {msg}")
        if orcid and not args.dry_run:
            conn.execute(
                "UPDATE people SET orcid = ?, updated_at = now() "
                "WHERE person_id = ?",
                [orcid, p["person_id"]],
            )
        time.sleep(0.05)
    log.close()

    print(f"[totals] {totals}")

    if not args.dry_run:
        export_parquet(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
