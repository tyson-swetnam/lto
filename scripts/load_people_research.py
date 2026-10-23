#!/usr/bin/env python3
"""Load fetched facility-leadership research and person bio updates.

Inputs
  data/raw/R-PEOPLE2/*.json      one batch per file: the facilities an agent
                                 researched, the pages it fetched, the people
                                 it found, their affiliations (each with the
                                 page and a quote that back it) and a verdict
                                 on every leadership row already in the lake
  data/raw/R-PEOPLE2-BIO/*.json  bio / identifier / status updates for people
                                 who already exist, keyed on person_id

Writes (idempotent — a second run changes nothing)
  people               new people, plus COALESCE-merged fields on existing
                       ones; a value already in the lake is never nulled
  facility_personnel   the affiliations, keyed (person_id, facility_id, role)

Rules
  * facility_id is authoritative: no name or acronym resolution. An unknown
    facility_id stops the load.
  * A person is matched, in order, on existing_person_id; on exact ORCID
    equality; on an exact normalised full-name match among the people
    already attached to one of the same facilities (failing that, a unique
    match there under another spelling of the name — middle names or
    initials, a nickname, accents, a hyphenated or double surname:
    same_person_name); otherwise a new
    person_id is minted from the name alone (stable_person_id below, the
    same hash load_arid.py uses). Names never merge people across
    facilities, and an ORCID that conflicts with the one on file is
    reported and not written. A person_id that dedupe_people.py merged away
    (data/seed/people_merge_log.csv) is read as the person it was kept as,
    wherever a file names it.
  * Roles go through schema/vocab/personnel_roles.csv; an unknown role stops
    the load and lists every unknown value.
  * An affiliation without source_url or evidence is refused (skipped and
    listed). A bio, research_interests or status without its own source URL
    is not written. A research batch fills empty or unsourced people fields
    and replaces sourced ones only with something retrieved on a later date
    (so overlapping same-day batches do not flip each other on re-runs); a
    bio-update batch replaces them outright. Never with a NULL.
  * When a batch lists the current holders of a leadership role at a
    facility (is_leadership in the vocab), any other current holder of that
    role there is marked is_current = false — the row is kept, never
    deleted, and its notes say which batch superseded it. end_date is left
    alone: the batch shows the person is no longer listed, not when they
    left. Only rows retrieved before the batch are superseded (so batches
    never undo each other, whatever the file order), and never a row whose
    person is one of the listed holders under another spelling of the name
    (that is a duplicate to merge, reported as a warning).
  * Verifications: stale -> is_current = false on that row (kept);
    confirmed -> source_url, retrieved_at, confidence and evidence
    refreshed; not-found -> confidence 'low' and a note "not found on
    official pages <retrieved_at>" (a row nobody could find on current
    official pages must not stay 'high'), unless another batch confirmed
    or re-sourced the same row; unverifiable -> reported, no change.
  * retrieved_at comes from the file, never from the clock.

One lake transaction (one snapshot) per file, with the commit message
``load_people_research: <batch_id>``; a failing file rolls back alone.

Usage::

    python scripts/load_people_research.py --dry-run     # diff summary, no writes
    python scripts/load_people_research.py
    python scripts/load_people_research.py data/raw/R-PEOPLE2/R-PEOPLE2-NERR-01a.json

Then: qa.py -> export_parquet.py -> export_view_caches.py.

The identity helpers here (stable_person_id, resolve_person_id,
normalize_role) are shared with the other people loaders.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESEARCH_GLOB = "R-PEOPLE2/*.json"
BIO_GLOB = "R-PEOPLE2-BIO/*.json"
ROLES_CSV = ROOT / "schema" / "vocab" / "personnel_roles.csv"

# Spellings older loaders and seed CSVs use, mapped to vocab slugs. Matching
# is case-insensitive; a value that is neither a slug nor listed here is an
# error, so a new spelling gets a human decision rather than a new role.
ROLE_ALIASES = {
    "research-collaborator": "collaborator",
    "principal investigator": "lead-PI",
    "pi": "lead-PI",
    "lead pi": "lead-PI",
    "co-principal investigator": "co-PI",
    "co-pi": "co-PI",
    "executive director": "director",
    "research director": "director",
    "scientific director": "director",
    "science director": "director",
    "president & director": "director",
    "chief scientist": "director",
    "reserve manager": "manager",
    "program manager": "manager",
    "head administrator": "manager",
    "research leader": "manager",
    "president & ceo": "executive-officer",
    "ceo": "executive-officer",
    "research scientist": "scientist",
    "professor": "faculty",
    "technician": "technical-staff",
    # Round-2 / seed CSV spellings (data/seed/facility_personnel_*.csv).
    "staff scientist": "scientist",
    "lab director": "director",
    "acting director": "director",
    "interim director": "director",
    "co-director": "director",
    "dean": "director",               # dean of a school that is the facility (URI GSO, RSMAES)
    "dean & director": "director",
    "co-lead pi": "lead-PI",
    "branch chief": "manager",
    "reserve director": "manager",    # director of a reserve inside the facility
    "division director": "leadership-team",
    "technical director": "leadership-team",
    "emeritus director": "former-director",
}


def parse_date(v) -> str | None:
    """'2002' -> 2002-01-01, '2014-07' -> 2014-07-01, ISO dates as given;
    anything else -> None."""
    v = (v or "").strip() if isinstance(v, str) else v
    if not v:
        return None
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", str(v))
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2) or "1", m.group(3) or "1"
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

# people.status vocabulary (schema.sql: active | emeritus | former | unknown,
# plus 'deceased', which the committed data already uses). Verifiers also
# wrote 'retired', which maps to 'former' (the raw value is kept in the note
# the bio loader appends: "status retired per <url>"). 'unknown' writes
# nothing.
STATUS_MAP = {"active": "active", "emeritus": "emeritus", "former": "former",
              "retired": "former", "deceased": "deceased", "unknown": None}

PEOPLE_COLS = ["bio_source_url", "bio_retrieved_at", "research_interests_source_url",
               "orcid_source_url", "homepage_checked_at"]
PERSONNEL_COLS = ["is_current", "evidence"]


class LoadError(RuntimeError):
    """A file this loader refuses to apply; nothing from it is written."""


class _DryRun(Exception):
    """Raised at the end of a dry-run transaction to roll it back."""


# ── identity (shared with load_lto_people / load_facility_personnel*) ──────
def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def stable_person_id(name: str) -> str:
    """Name-only person_id: ``sha1(lower(name)||'||')[:16]``.

    Same value load_arid.py mints, and the same value the old
    ``hash(name|orcid|email)`` gave a person with neither, so existing ids
    are unchanged. An ORCID or email arriving later no longer changes it.
    """
    return sha16(f"{(name or '').strip().lower()}||")


def legacy_person_id(name: str, a: str | None = None, b: str | None = None) -> str:
    """The pre-lake ``hash(lower(name)|orcid|email)`` id. Only ever used to
    find a row that already exists under it, or to keep two namesakes with
    conflicting ORCIDs apart."""
    return sha16(f"{(name or '').strip().lower()}|{(a or '').strip()}|{(b or '').strip().lower()}")


def norm_orcid(orcid: str | None) -> str | None:
    if not orcid:
        return None
    o = re.sub(r"^https?://(www\.)?orcid\.org/", "", orcid.strip(), flags=re.I)
    return o.upper() or None


def norm_name(name: str | None) -> str:
    """Lower case, accents stripped, punctuation to spaces, spaces collapsed:
    'Debra P.C. Peters' and 'debra p c  peters' compare equal."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s-]", " ", s)
    return " ".join(s.split())


# Common English short forms. Used only to compare two names already
# attached to the same facility (never to merge across facilities).
NICKNAMES = {
    "bob": "robert", "rob": "robert", "bobby": "robert", "dave": "david",
    "mike": "michael", "pete": "peter", "ken": "kenneth", "jeff": "jeffrey",
    "jim": "james", "jimmy": "james", "bill": "william", "will": "william",
    "tom": "thomas", "dan": "daniel", "chris": "christopher", "kate": "katherine",
    "katie": "katherine", "liz": "elizabeth", "beth": "elizabeth", "steve": "stephen",
    "joe": "joseph", "tony": "anthony", "andy": "andrew", "matt": "matthew",
    "nick": "nicholas", "sam": "samuel", "ed": "edward", "rick": "richard",
    "dick": "richard", "jen": "jennifer", "jenny": "jennifer", "greg": "gregory",
    "tim": "timothy", "don": "donald", "ron": "ronald", "larry": "lawrence",
    "deb": "deborah", "debbie": "deborah", "sue": "susan", "cathy": "catherine",
    "pat": "patrick", "doug": "douglas", "russ": "russell", "nikki": "nicole",
    "fred": "frederick", "al": "alan", "jon": "jonathan", "ben": "benjamin",
}


def name_parts(name: str | None) -> tuple[list[str], set[str]]:
    """(tokens, aliases): accents folded, lower case, hyphens and
    punctuation split; a parenthesised part ("Yoshimi (Shimi) Rii") is an
    alias, not a token."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    aliases = set(re.sub(r"[^\w\s]", " ", " ".join(re.findall(r"\(([^)]*)\)", s))).split())
    s = re.sub(r"\([^)]*\)", " ", s)
    toks = re.sub(r"[^\w\s]|_", " ", s).split()
    toks = [t for t in toks if t not in ("jr", "sr", "ii", "iii", "iv", "dr", "phd")]
    return toks, aliases


def same_person_name(a: str | None, b: str | None) -> bool:
    """Two spellings of one person's name, for names ALREADY at the same
    facility: 'Ken Dunton' / 'Kenneth H. Dunton', 'Tonna-Marie Rogers' /
    'Tonna-Marie Surgeon Rogers', 'Aitza Pabón' / 'Aitza E. Pabón-Valentín',
    'Patrick Megonigal' / 'James Patrick Megonigal', 'Shimi Rii' /
    'Yoshimi (Shimi) Rii'. The family name must agree (one's last token is
    one of the other's tokens) and the given name must agree (equal up to a
    listed nickname, or one's first name is the other's middle name or
    parenthesised alias). Never used across facilities: there are real
    namesakes in the catalogue."""
    (ta, aa), (tb, ab) = name_parts(a), name_parts(b)
    if len(ta) < 2 or len(tb) < 2:
        return False
    if not (ta[-1] in tb or tb[-1] in ta):
        return False
    # Middle names that contradict each other ('John Michael Smith' /
    # 'John David Smith', 'Ann B. Lee' / 'Ann C. Lee') are two people.
    ma, mb = ta[1:-1], tb[1:-1]
    wa, wb = {t for t in ma if len(t) > 1}, {t for t in mb if len(t) > 1}
    if wa and wb and not (wa & set(tb) or wb & set(ta)):
        return False
    ia, ib = {t[0] for t in ma}, {t[0] for t in mb}
    if ia and ib and not (ia & ib):
        return False
    fa, fb = NICKNAMES.get(ta[0], ta[0]), NICKNAMES.get(tb[0], tb[0])
    if fa == fb or ta[0] in tb[1:-1] or tb[0] in ta[1:-1] or ta[0] in ab or tb[0] in aa:
        return True
    # 'K. Dunton' style: a lone initial agrees with the other's first letter.
    return (len(ta[0]) == 1 and tb[0].startswith(ta[0])) or \
           (len(tb[0]) == 1 and ta[0].startswith(tb[0]))


def same_family(a: str | None, b: str | None) -> bool:
    """The family names agree (accents, hyphens and particles folded)."""
    (ta, _), (tb, _) = name_parts(a), name_parts(b)
    return bool(ta and tb and (ta[-1] in tb or tb[-1] in ta))


# ── merged people ──────────────────────────────────────────────────────────
MERGE_LOG = ROOT / "data" / "seed" / "people_merge_log.csv"
_redirects: dict[str, str] | None = None


def merge_redirects(path: Path = MERGE_LOG) -> dict[str, str]:
    """merged_id -> the person_id it was merged into (dedupe_people.py's
    log), closed transitively. A research file or seed CSV written before a
    merge still names the merged id or mints it from a name; every loader
    sends those to the kept person instead of re-creating the duplicate."""
    global _redirects
    if _redirects is None:
        m: dict[str, str] = {}
        if path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if r.get("merged_id") and r.get("kept_id"):
                        m[r["merged_id"].strip()] = r["kept_id"].strip()
        for k in list(m):
            seen = {k}
            while m[k] in m and m[k] not in seen:
                seen.add(m[k])
                m[k] = m[m[k]]
        _redirects = m
    return _redirects


def canonical_person_id(pid: str | None) -> str | None:
    return merge_redirects().get(pid, pid) if pid else pid


def person_at_facility(con, name: str, facility_id: str | None) -> str | None:
    """The one person already attached to ``facility_id`` whose name is a
    spelling of ``name`` (same_person_name), or None (none, or ambiguous)."""
    if not facility_id:
        return None
    hits = {pid for pid, n in lto_db.rows(
        con, "SELECT DISTINCT p.person_id, p.name FROM facility_personnel fp "
             "JOIN people p USING (person_id) WHERE fp.facility_id = ?", [facility_id])
        if same_person_name(n, name)}
    return hits.pop() if len(hits) == 1 else None


def resolve_person_id(con, name: str, orcid: str | None = None,
                      openalex_id: str | None = None,
                      legacy_id: str | None = None,
                      facility_id: str | None = None) -> str:
    """person_id for a loader row, merging only on identifier equality.

    1. a person already carrying this ORCID (exact), else this OpenAlex id;
    2. the row's pre-lake id, if a person exists under it (keeps the ids of
       rows minted by the old name|orcid|email hash);
    3. the name-only stable id — unless a person already holds it with a
       different ORCID or OpenAlex id, in which case they are a namesake
       and keep apart under the caller's legacy id (or name|orcid);
    4. when that id is not in the lake yet and the row names a facility,
       the one person already at that facility under another spelling of
       the name (person_at_facility), so 'Bob Miller' in a seed CSV does
       not become a second Robert J. Miller at SBC LTER.
    Any id dedupe_people.py has merged away is replaced by the kept one.
    """
    pid = _resolve_person_id(con, name, orcid, openalex_id, legacy_id)
    pid = canonical_person_id(pid)
    if not lto_db.scalar(con, "SELECT count(*) FROM people WHERE person_id = ?", [pid]):
        pid = person_at_facility(con, name, facility_id) or pid
    return pid


def _resolve_person_id(con, name, orcid, openalex_id, legacy_id) -> str:
    orcid = norm_orcid(orcid)
    for col, val in (("orcid", orcid), ("openalex_id", openalex_id)):
        if val:
            hit = lto_db.rows(
                con, f"SELECT person_id FROM people WHERE upper({col}) = upper(?) "
                     "ORDER BY lower(name) = lower(?) DESC, person_id LIMIT 1", [val, name])
            if hit:
                return hit[0][0]
    if legacy_id and lto_db.scalar(con, "SELECT count(*) FROM people WHERE person_id = ?",
                                   [legacy_id]):
        return legacy_id
    pid = stable_person_id(name)
    have = lto_db.rows(con, "SELECT orcid, openalex_id FROM people WHERE person_id = ?", [pid])
    if have and ((orcid and have[0][0] and norm_orcid(have[0][0]) != orcid)
                 or (openalex_id and have[0][1] and have[0][1].upper() != openalex_id.upper())):
        alt = legacy_id if legacy_id and legacy_id != pid else \
            legacy_person_id(name, orcid or openalex_id)
        return alt
    return pid


# ── roles ──────────────────────────────────────────────────────────────────
def load_roles(path: Path = ROLES_CSV) -> dict[str, tuple[str, bool]]:
    """lower(slug) -> (slug, is_leadership)."""
    with path.open(newline="") as fh:
        return {r["slug"].lower(): (r["slug"], r["is_leadership"].strip().lower() == "true")
                for r in csv.DictReader(fh)}


def normalize_role(raw: str | None, roles: dict[str, tuple[str, bool]]) -> str | None:
    """Vocab slug for a role as written, or None when it has no mapping."""
    if not raw or not raw.strip():
        return None
    k = raw.strip().lower()
    for cand in (k, re.sub(r"[\s_]+", "-", k), ROLE_ALIASES.get(k, "").lower()):
        if cand and cand in roles:
            return roles[cand][0]
    return None


# ── helpers ────────────────────────────────────────────────────────────────
def blank(v):
    if isinstance(v, str):
        v = v.strip()
    return v if v not in ("", None) else None


def year_date(y) -> str | None:
    # Sources give years; store Jan 1 so "ended in 2024" is already past in 2024.
    return f"{int(y):04d}-01-01" if y not in (None, "") else None


def append_note(old: str | None, add: str) -> str:
    old = old or ""
    if add in old:
        return old
    return f"{old} {add}".strip()


def ensure_columns(con) -> bool:
    """True when the lake already has every column this loader writes."""
    have = {(t, c) for t, c in lto_db.rows(
        con, "SELECT table_name, column_name FROM duckdb_columns() "
             "WHERE database_name = ? AND table_name IN ('people', 'facility_personnel')",
        [lto_db.LAKE])}
    return all(("people", c) in have for c in PEOPLE_COLS) and \
        all(("facility_personnel", c) in have for c in PERSONNEL_COLS)


STAGE_PEOPLE_DDL = """
CREATE OR REPLACE TEMP TABLE _stage_people (
    person_id VARCHAR, name VARCHAR, name_given VARCHAR, name_family VARCHAR,
    orcid VARCHAR, orcid_source_url VARCHAR,
    homepage_url VARCHAR, homepage_checked_at DATE,
    bio VARCHAR, bio_source_url VARCHAR, bio_retrieved_at DATE,
    research_interests VARCHAR, research_interests_source_url VARCHAR,
    status VARCHAR, note_add VARCHAR, _seq INTEGER)"""

# A matched person changes only when some incoming value differs, so a re-run
# writes nothing. Identity (name, name_given, name_family) of an existing
# person is never rewritten; new people take the file's spelling.
#
# Several research batches describe the same person (a NEON domain manager
# appears in every batch for the domain) with differently worded bios. If
# every sourced value simply replaced the last one, each re-run would flip
# them back and forth. So a research batch fills a field that is empty or
# unsourced, and replaces a sourced one only with something retrieved on a
# strictly later date. A bio-update batch (R-PEOPLE2-BIO) is a deliberate
# correction and replaces whatever is there — still never with a NULL.
def _people_set(authoritative: bool) -> dict[str, str]:
    force = "true" if authoritative else "false"
    bio = (f"s.bio IS NOT NULL AND (t.bio IS NULL OR t.bio_source_url IS NULL "
           f"OR s.bio_retrieved_at > t.bio_retrieved_at OR {force})")
    ri = (f"s.research_interests IS NOT NULL AND (t.research_interests IS NULL "
          f"OR t.research_interests_source_url IS NULL OR {force})")
    home = (f"s.homepage_url IS NOT NULL AND (t.homepage_url IS NULL OR {force} OR "
            f"(s.homepage_checked_at IS NOT NULL AND (t.homepage_checked_at IS NULL "
            f"OR s.homepage_checked_at > t.homepage_checked_at)))")
    osrc = ("COALESCE(s.orcid_source_url, t.orcid_source_url)" if authoritative
            else "COALESCE(t.orcid_source_url, s.orcid_source_url)")
    return {
        "orcid": "COALESCE(t.orcid, s.orcid)",
        "orcid_source_url": f"CASE WHEN s.orcid IS NOT NULL THEN {osrc} "
                            f"ELSE t.orcid_source_url END",
        "homepage_url": f"CASE WHEN {home} THEN s.homepage_url ELSE t.homepage_url END",
        "homepage_checked_at": f"CASE WHEN {home} THEN s.homepage_checked_at "
                               f"ELSE t.homepage_checked_at END",
        "bio": f"CASE WHEN {bio} THEN s.bio ELSE t.bio END",
        "bio_source_url": f"CASE WHEN {bio} THEN s.bio_source_url ELSE t.bio_source_url END",
        "bio_retrieved_at": f"CASE WHEN {bio} THEN s.bio_retrieved_at ELSE t.bio_retrieved_at END",
        "research_interests": f"CASE WHEN {ri} THEN s.research_interests "
                              f"ELSE t.research_interests END",
        "research_interests_source_url": f"CASE WHEN {ri} THEN s.research_interests_source_url "
                                         f"ELSE t.research_interests_source_url END",
        # 'retired' arrives as 'former'; an emeritus is retired too, and the
        # more specific value stays.
        "status": "CASE WHEN t.status = 'emeritus' AND s.status = 'former' THEN t.status "
                  "ELSE COALESCE(s.status, t.status) END",
        "notes": "CASE WHEN s.note_add IS NULL OR position(s.note_add IN COALESCE(t.notes, '')) > 0 "
                 "THEN t.notes ELSE trim(COALESCE(t.notes, '') || ' ' || s.note_add) END",
    }


def merge_people(con, authoritative: bool = False) -> dict:
    """MERGE _stage_people into people; returns new / changed / unchanged."""
    pset = _people_set(authoritative)
    changed = " OR ".join(f"t.{c} IS DISTINCT FROM ({e})" for c, e in pset.items())
    con.execute("""CREATE OR REPLACE TEMP TABLE _stage_people_d AS
                   SELECT DISTINCT ON (person_id) * FROM _stage_people
                   ORDER BY person_id, _seq DESC""")
    n_new = lto_db.scalar(con, "SELECT count(*) FROM _stage_people_d s WHERE NOT EXISTS "
                               "(SELECT 1 FROM people t WHERE t.person_id = s.person_id)")
    n_chg = lto_db.scalar(con, f"SELECT count(*) FROM _stage_people_d s JOIN people t "
                               f"USING (person_id) WHERE {changed}")
    n_all = lto_db.scalar(con, "SELECT count(*) FROM _stage_people_d")
    sets = ", ".join(f"{c} = {e}" for c, e in pset.items())
    con.execute(f"""
        MERGE INTO people t USING _stage_people_d s ON t.person_id = s.person_id
        WHEN MATCHED AND ({changed}) THEN UPDATE SET {sets}, updated_at = now()
        WHEN NOT MATCHED THEN INSERT
            (person_id, name, name_given, name_family, orcid, orcid_source_url,
             homepage_url, homepage_checked_at, bio, bio_source_url, bio_retrieved_at,
             research_interests, research_interests_source_url, status, notes)
        VALUES (s.person_id, s.name, s.name_given, s.name_family, s.orcid, s.orcid_source_url,
                s.homepage_url, s.homepage_checked_at, s.bio, s.bio_source_url,
                s.bio_retrieved_at, s.research_interests, s.research_interests_source_url,
                s.status, s.note_add)""")
    con.execute("DROP TABLE _stage_people_d")
    return {"new": n_new, "changed": n_chg, "unchanged": n_all - n_new - n_chg}


def person_fields(con, pid: str, rec: dict, retrieved_at: str, fetched_ok: set[str],
                  warn: list[str]) -> dict:
    """The people columns one record may write, after the provenance rules."""
    orcid = norm_orcid(rec.get("orcid"))
    existing_orcid = lto_db.scalar(con, "SELECT orcid FROM people WHERE person_id = ?", [pid])
    if orcid and existing_orcid and norm_orcid(existing_orcid) != orcid:
        warn.append(f"ORCID conflict for {rec.get('name')!r}: file {orcid}, "
                    f"lake {existing_orcid} — kept the lake's")
        orcid = None
    if orcid and not existing_orcid:
        # One ORCID, one person: if someone else already carries it, the two
        # rows are the same researcher and need a merge, not a second copy.
        other = lto_db.rows(con, "SELECT person_id, name FROM people WHERE upper(orcid) = ? "
                                 "AND person_id <> ? ORDER BY person_id LIMIT 1", [orcid, pid])
        if other:
            warn.append(f"ORCID {orcid} for {rec.get('name')!r} ({pid}) is already on "
                        f"{other[0][1]!r} ({other[0][0]}) — not written; merge the two")
            orcid = None
    bio, bio_src = blank(rec.get("bio")), blank(rec.get("bio_source_url"))
    if bio and not bio_src:
        warn.append(f"bio for {rec.get('name')!r} has no bio_source_url — not written")
        bio = None
    ri, ri_src = blank(rec.get("research_interests")), blank(rec.get("research_interests_source_url"))
    if ri and not ri_src:
        warn.append(f"research_interests for {rec.get('name')!r} have no source URL — not written")
        ri = None
    home = blank(rec.get("homepage_url"))
    cited = fetched_ok | {u for u in (bio_src, ri_src, blank(rec.get("orcid_source_url")),
                                      blank(rec.get("status_source_url"))) if u}
    return {
        "orcid": orcid,
        "orcid_source_url": blank(rec.get("orcid_source_url")) if orcid else None,
        "homepage_url": home,
        "homepage_checked_at": retrieved_at if home and home in cited else None,
        "bio": bio, "bio_source_url": bio_src if bio else None,
        "bio_retrieved_at": retrieved_at if bio else None,
        "research_interests": ri, "research_interests_source_url": ri_src if ri else None,
    }


def stage_people(con, rows: list[dict]) -> None:
    con.execute(STAGE_PEOPLE_DDL)
    cols = ["person_id", "name", "name_given", "name_family", "orcid", "orcid_source_url",
            "homepage_url", "homepage_checked_at", "bio", "bio_source_url", "bio_retrieved_at",
            "research_interests", "research_interests_source_url", "status", "note_add"]
    if rows:                              # executemany rejects an empty list
        con.executemany(
            f"INSERT INTO _stage_people ({', '.join(cols)}, _seq) VALUES "
            f"({', '.join('?' for _ in cols)}, ?)",
            [[r.get(c) for c in cols] + [i] for i, r in enumerate(rows)])


# ── R-PEOPLE2: facility leadership research ────────────────────────────────
def load_research(con, path: Path, doc: dict, roles, verbose: bool,
                  confirmed_elsewhere: frozenset = frozenset()) -> dict:
    batch = doc.get("batch_id") or path.stem
    retrieved = doc.get("retrieved_at")
    if not retrieved:
        raise LoadError(f"{path.name}: no retrieved_at")
    warn: list[str] = []
    stats: Counter = Counter()

    # Ids that dedupe_people.py merged away point at the kept person.
    people = {p["key"]: dict(p, existing_person_id=canonical_person_id(p.get("existing_person_id")))
              for p in doc.get("people", [])}
    affs = doc.get("affiliations", [])
    vers = [dict(v, person_id=canonical_person_id(v.get("person_id")))
            for v in doc.get("verifications", [])]

    # 1. Everything that stops the load, collected so one run lists it all.
    errors: list[str] = []
    fids = ({f.get("facility_id") for f in doc.get("facilities", [])}
            | {a.get("facility_id") for a in affs} | {v.get("facility_id") for v in vers})
    known = {r[0] for r in lto_db.rows(
        con, "SELECT facility_id FROM facilities WHERE facility_id IN "
             "(SELECT unnest(?::VARCHAR[]))", [sorted(f for f in fids if f)])}
    bad_fids = sorted(f or "<missing>" for f in fids if f not in known)
    if bad_fids:
        errors.append(f"unknown facility_id(s): {', '.join(bad_fids)}")
    unknown_roles = sorted({a.get("role") or "<blank>" for a in affs
                            if not normalize_role(a.get("role"), roles)})
    if unknown_roles:
        errors.append(f"role(s) not in {ROLES_CSV.relative_to(ROOT)}: {', '.join(unknown_roles)}")
    bad_keys = sorted({a.get("person_key") or "<blank>" for a in affs
                       if a.get("person_key") not in people})
    if bad_keys:
        errors.append(f"affiliation person_key(s) with no people entry: {', '.join(bad_keys)}")
    ext_ids = sorted({p["existing_person_id"] for p in people.values() if p.get("existing_person_id")}
                     | {v["person_id"] for v in vers if v.get("person_id")})
    have_ids = {r[0] for r in lto_db.rows(
        con, "SELECT person_id FROM people WHERE person_id IN (SELECT unnest(?::VARCHAR[]))",
        [ext_ids])}
    if set(ext_ids) - have_ids:
        errors.append(f"person_id(s) not in people: {', '.join(sorted(set(ext_ids) - have_ids))}")
    if errors:
        raise LoadError(f"{path.name}: " + "; ".join(errors))

    fetched_ok = {pg.get("url") for f in doc.get("facilities", [])
                  for pg in f.get("pages_fetched", []) if pg.get("status") == 200}

    # 2. Affiliations without their evidence are refused.
    good_affs = []
    for a in affs:
        if not blank(a.get("source_url")) or not blank(a.get("evidence")):
            stats["aff_refused"] += 1
            warn.append(f"refused affiliation {a.get('person_key')} @ {a.get('facility_id')} "
                        f"({a.get('role')}): missing source_url/evidence")
            continue
        good_affs.append(a)
    key_facilities: dict[str, set[str]] = defaultdict(set)
    for a in good_affs:
        key_facilities[a["person_key"]].add(a["facility_id"])

    # 3. People -> person_id.
    attached = defaultdict(list)          # facility_id -> [(person_id, norm name)]
    attached_names = defaultdict(list)    # facility_id -> [(person_id, name)]
    for fid, pid, name in lto_db.rows(
            con, "SELECT DISTINCT fp.facility_id, p.person_id, p.name "
                 "FROM facility_personnel fp JOIN people p USING (person_id) "
                 "WHERE fp.facility_id IN (SELECT unnest(?::VARCHAR[]))", [sorted(known)]):
        attached[fid].append((pid, norm_name(name)))
        attached_names[fid].append((pid, name))
    key_pid: dict[str, str] = {}
    stage: list[dict] = []
    new_people: list[str] = []
    for key, p in people.items():
        name = blank(p.get("name"))
        if not name:
            raise LoadError(f"{path.name}: person {key!r} has no name")
        orcid = norm_orcid(p.get("orcid"))
        if p.get("existing_person_id"):
            pid, how = p["existing_person_id"], "existing_id"
        else:
            hit = lto_db.rows(con, "SELECT person_id FROM people WHERE upper(orcid) = ? "
                                   "ORDER BY person_id", [orcid]) if orcid else []
            if len(hit) > 1:
                warn.append(f"ORCID {orcid} is on {len(hit)} people "
                            f"({', '.join(h[0] for h in hit)}); used {hit[0][0]}")
            if hit:
                pid, how = hit[0][0], "orcid"
            else:
                nn = norm_name(name)
                cands = sorted({pid for fid in key_facilities.get(key, ())
                                for pid, n in attached[fid] if n == nn})
                if len(cands) > 1:
                    raise LoadError(f"{path.name}: {name!r} matches {len(cands)} people at "
                                    f"the same facility ({', '.join(cands)}); set "
                                    f"existing_person_id")
                if not cands:
                    # Another spelling of the same name at the same facility:
                    # middle initials ("Sarah H. Fernald" / "Sarah Fernald"),
                    # a nickname ("Ken" / "Kenneth H."), a double or
                    # hyphenated surname, accents (same_person_name).
                    loose = {pid for fid in key_facilities.get(key, ())
                             for pid, n in attached_names[fid] if same_person_name(n, name)}
                    if len(loose) > 1:
                        # Tie-break on corroboration: the candidate already
                        # holding this role at this facility, cited to the
                        # same page as the incoming affiliation.
                        mine = {(a["facility_id"], normalize_role(a["role"], roles),
                                 a["source_url"].strip())
                                for a in good_affs if a["person_key"] == key}
                        same_page = {pid for pid in loose if any(
                            r in mine for r in lto_db.rows(
                                con, "SELECT facility_id, role, trim(source_url) FROM "
                                     "facility_personnel WHERE person_id = ?", [pid]))}
                        if len(same_page) == 1:
                            loose = same_page
                    if len(loose) == 1:
                        cands = sorted(loose)
                        how_name = "name_at_facility_initials"
                    elif loose:
                        warn.append(f"{name!r} matches {len(loose)} people at the same facility "
                                    f"up to middle initials ({', '.join(sorted(loose))}) — "
                                    f"not merged; set existing_person_id")
                else:
                    how_name = "name_at_facility"
                if cands:
                    pid, how = cands[0], how_name
                else:
                    if not key_facilities.get(key):
                        stats["people_skipped_no_affiliation"] += 1
                        warn.append(f"new person {name!r} has no accepted affiliation — skipped")
                        continue
                    pid = canonical_person_id(stable_person_id(name))
                    have = lto_db.rows(con, "SELECT orcid FROM people WHERE person_id = ?", [pid])
                    if have and orcid and have[0][0] and norm_orcid(have[0][0]) != orcid:
                        pid, how = legacy_person_id(name, orcid), "new_namesake"
                    elif have:
                        how = "name_hash_reuse"
                        warn.append(f"{name!r} not at these facilities but its name-only id "
                                    f"{pid} exists — reused")
                    else:
                        how = "new"
                    if how != "name_hash_reuse":
                        new_people.append(f"{name} ({pid})")
        stats[f"match_{how}"] += 1
        key_pid[key] = pid
        row = {"person_id": pid, "name": name, "name_given": blank(p.get("name_given")),
               "name_family": blank(p.get("name_family"))}
        row.update(person_fields(con, pid, p, retrieved, fetched_ok, warn))
        stage.append(row)

    stage_people(con, stage)
    ps = merge_people(con)

    # 4. Affiliations.
    con.execute("""CREATE OR REPLACE TEMP TABLE _stage_fp (
        person_id VARCHAR, facility_id VARCHAR, role VARCHAR, title VARCHAR,
        is_key_personnel BOOLEAN, is_current BOOLEAN, start_date DATE, end_date DATE,
        source VARCHAR, source_url VARCHAR, retrieved_at DATE, confidence VARCHAR,
        evidence VARCHAR, _seq INTEGER)""")
    fp_rows = []
    for i, a in enumerate(good_affs):
        if a["person_key"] not in key_pid:
            continue
        fp_rows.append([key_pid[a["person_key"]], a["facility_id"],
                        normalize_role(a["role"], roles), blank(a.get("title")),
                        bool(a.get("is_key_personnel")),
                        None if a.get("is_current") is None else bool(a["is_current"]),
                        year_date(a.get("start_year")), year_date(a.get("end_year")),
                        batch, a["source_url"].strip(), retrieved,
                        blank(a.get("confidence")) or "medium", a["evidence"].strip(), i])
    if fp_rows:
        con.executemany("INSERT INTO _stage_fp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", fp_rows)
    fp_set = {
        "title": "COALESCE(s.title, t.title)",
        "is_key_personnel": "s.is_key_personnel",
        "is_current": "COALESCE(s.is_current, t.is_current)",
        "start_date": "COALESCE(s.start_date, t.start_date)",
        # A batch that lists the holder as current overrides an older end
        # date (e.g. an award end copied from a seed CSV before a renewal).
        "end_date": "CASE WHEN s.is_current IS TRUE THEN s.end_date "
                    "ELSE COALESCE(s.end_date, t.end_date) END",
        "source": "s.source", "source_url": "s.source_url",
        "retrieved_at": "s.retrieved_at", "confidence": "s.confidence",
        "evidence": "s.evidence",
    }
    # Same idea as for people: a row already backed by evidence is replaced
    # only by a batch retrieved on a later date, so two same-day batches that
    # both list a person do not overwrite each other on every run.
    changed = ("(t.evidence IS NULL OR t.retrieved_at IS NULL OR s.retrieved_at > t.retrieved_at)"
               " AND (" + " OR ".join(f"t.{c} IS DISTINCT FROM ({e})"
                                      for c, e in fp_set.items()) + ")")
    con.execute("""CREATE OR REPLACE TEMP TABLE _stage_fp_d AS
                   SELECT DISTINCT ON (person_id, facility_id, role) * FROM _stage_fp
                   ORDER BY person_id, facility_id, role, _seq DESC""")
    on = "t.person_id = s.person_id AND t.facility_id = s.facility_id AND t.role = s.role"
    fs = {"new": lto_db.scalar(con, f"SELECT count(*) FROM _stage_fp_d s WHERE NOT EXISTS "
                                    f"(SELECT 1 FROM facility_personnel t WHERE {on})"),
          "changed": lto_db.scalar(con, f"SELECT count(*) FROM _stage_fp_d s JOIN "
                                        f"facility_personnel t ON {on} WHERE {changed}"),
          "all": lto_db.scalar(con, "SELECT count(*) FROM _stage_fp_d")}
    con.execute(f"""
        MERGE INTO facility_personnel t USING _stage_fp_d s ON {on}
        WHEN MATCHED AND ({changed}) THEN UPDATE SET
            {', '.join(f'{c} = {e}' for c, e in fp_set.items())}
        WHEN NOT MATCHED THEN INSERT
            (person_id, facility_id, role, title, is_key_personnel, is_current, start_date,
             end_date, source, source_url, retrieved_at, confidence, evidence)
        VALUES (s.person_id, s.facility_id, s.role, s.title, s.is_key_personnel, s.is_current,
                s.start_date, s.end_date, s.source, s.source_url, s.retrieved_at,
                s.confidence, s.evidence)""")

    # 5. Supersede: current holders of a leadership role this batch lists
    #    replace other current holders of that role at that facility.
    holders: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in fp_rows:
        if r[5] is not False and roles[r[2].lower()][1]:
            holders[(r[1], r[2])].add(r[0])
    for v in vers:
        slug = normalize_role(v.get("existing_role"), roles)
        if v.get("status") == "confirmed" and slug and (v["facility_id"], slug) in holders:
            holders[(v["facility_id"], slug)].add(v["person_id"])
    superseded = []
    holder_names = {pid: n for pid, n in lto_db.rows(
        con, "SELECT person_id, name FROM people WHERE person_id IN "
             "(SELECT unnest(?::VARCHAR[]))", [sorted({p for h in holders.values() for p in h})])}
    if holders:
        # Only rows older than this batch: a row retrieved on the same day
        # or later was listed as current by a source at least as recent, so
        # two batches never knock each other's holders out (and the result
        # does not depend on file order).
        for pid, fid, role, name, notes in lto_db.rows(
                con, "SELECT fp.person_id, fp.facility_id, fp.role, p.name, fp.notes "
                     "FROM facility_personnel fp JOIN people p USING (person_id) "
                     "WHERE fp.facility_id IN (SELECT unnest(?::VARCHAR[])) "
                     "AND COALESCE(fp.is_current, true) "
                     "AND (fp.end_date IS NULL OR fp.end_date > ?::DATE) "
                     "AND (fp.retrieved_at IS NULL OR fp.retrieved_at < ?::DATE) "
                     "ORDER BY ALL", [sorted({k[0] for k in holders}), retrieved, retrieved]):
            slug = normalize_role(role, roles)
            if slug and (fid, slug) in holders and pid not in holders[(fid, slug)]:
                # The same person under another spelling is not "someone
                # else": leave the row for dedupe_people.py to merge.
                if any(same_person_name(name, holder_names.get(h)) for h in holders[(fid, slug)]):
                    warn.append(f"{name!r} ({pid}) as {slug} @ {fid} looks like current holder "
                                f"{', '.join(holder_names.get(h, h) for h in holders[(fid, slug)])}"
                                f" under another spelling — not superseded; merge the two")
                    continue
                note = (f"[{batch}] superseded as {slug}: not listed as current on "
                        f"{', '.join(sorted({r[9] for r in fp_rows if r[1] == fid and r[2] == slug}))}"
                        f" (retrieved {retrieved})")
                superseded.append((pid, fid, role, name, append_note(notes, note)))
    for pid, fid, role, _name, notes in superseded:
        con.execute("UPDATE facility_personnel SET is_current = false, notes = ? "
                    "WHERE person_id = ? AND facility_id = ? AND role = ?",
                    [notes, pid, fid, role])

    # 6. Verifications of rows already in the lake.
    vstats: Counter = Counter()
    for v in vers:
        status = v.get("status")
        vstats[status] += 1
        if status == "not-found":
            key = [v.get("person_id"), v.get("facility_id"), v.get("existing_role")]
            if tuple(key) in confirmed_elsewhere:
                vstats["not-found_overridden_by_confirmed"] += 1
                continue
            cur = lto_db.rows(con, "SELECT confidence, notes, evidence, retrieved_at::VARCHAR "
                                   "FROM facility_personnel WHERE person_id = ? AND facility_id = ? "
                                   "AND role = ?", key)
            if not cur:
                vstats["row_missing"] += 1
                warn.append(f"not-found verification names a row not in the lake: {key}")
                continue
            conf, notes, ev, ret = cur[0]
            if ev is not None and ret is not None and ret >= retrieved:
                continue                  # re-sourced by a research batch this recent
            where = blank(v.get("source_url"))
            note = (f"[{batch}] not found on official pages {retrieved}"
                    + (f" ({where})" if where else ""))
            new = ("low", append_note(notes, note))
            if new != (conf, notes):
                con.execute("UPDATE facility_personnel SET confidence = ?, notes = ? "
                            "WHERE person_id = ? AND facility_id = ? AND role = ?", [*new, *key])
                vstats["not-found_applied"] += 1
            continue
        if status not in ("confirmed", "stale"):
            continue
        if not blank(v.get("source_url")) or not blank(v.get("evidence")):
            vstats["refused"] += 1
            warn.append(f"refused {status} verification of {v.get('person_id')} @ "
                        f"{v.get('facility_id')}: missing source_url/evidence")
            continue
        key = [v["person_id"], v["facility_id"], v.get("existing_role")]
        cur = lto_db.rows(con, "SELECT is_current, source_url, retrieved_at::VARCHAR, "
                               "confidence, evidence, notes FROM facility_personnel "
                               "WHERE person_id = ? AND facility_id = ? AND role = ?", key)
        if not cur:
            vstats["row_missing"] += 1
            warn.append(f"{status} verification names a row not in the lake: {key}")
            continue
        is_cur, src, ret, conf, ev, notes = cur[0]
        if status == "stale":
            holder = v.get("current_holder_key")
            if holder in key_pid and key_pid[holder] == v["person_id"]:
                vstats["stale_is_current_holder"] += 1
                continue                  # merged: the "stale" row's person is the holder
            if ev is not None and ret is not None and ret > retrieved:
                continue                  # re-sourced by a later batch
            note = (f"[{batch}] stale: {v['evidence'].strip()} ({v['source_url'].strip()}, "
                    f"retrieved {retrieved})" + (f"; current holder {people[holder]['name']}"
                                                 if holder in people else ""))
            new = (False, src, ret, conf, ev, append_note(notes, note))
        elif ev is not None and ret is not None and ret >= retrieved:
            continue                      # already backed by a batch this recent
        else:
            new = (True, v["source_url"].strip(), retrieved, "high", v["evidence"].strip(), notes)
        if new != (is_cur, src, ret, conf, ev, notes):
            con.execute("UPDATE facility_personnel SET is_current = ?, source_url = ?, "
                        "retrieved_at = ?::DATE, confidence = ?, evidence = ?, notes = ? "
                        "WHERE person_id = ? AND facility_id = ? AND role = ?", [*new, *key])
            vstats[f"{status}_applied"] += 1

    lto_db.assert_integrity(con, ["people", "facility_personnel"])

    print(f"[{batch}] people: {ps['new']} new, {ps['changed']} updated, "
          f"{ps['unchanged']} unchanged  (matched: "
          + ", ".join(f"{k[6:]} {n}" for k, n in sorted(stats.items()) if k.startswith("match_"))
          + ")")
    print(f"[{batch}] affiliations: {len(affs)} read, {stats['aff_refused']} refused; "
          f"{fs['new']} new, {fs['changed']} updated, {fs['all'] - fs['new'] - fs['changed']} "
          f"unchanged; {len(superseded)} superseded")
    print(f"[{batch}] verifications: " + ", ".join(f"{k} {n}" for k, n in sorted(vstats.items()))
          if vers else f"[{batch}] verifications: none")
    if verbose:
        for s in new_people:
            print(f"    + person {s}")
        for pid, fid, role, name, _ in superseded:
            print(f"    ~ superseded {name} ({pid}) as {role} @ {fid}")
    for w in warn if verbose else warn[:5]:
        print(f"    [warn] {w}")
    if not verbose and len(warn) > 5:
        print(f"    … {len(warn) - 5} more warnings (--verbose)")
    return {"people_new": ps["new"], "people_changed": ps["changed"],
            "fp_new": fs["new"], "fp_changed": fs["changed"],
            "superseded": len(superseded),
            "verified": vstats["confirmed_applied"] + vstats["stale_applied"]
                        + vstats["not-found_applied"]}


# ── R-PEOPLE2-BIO: updates for existing people ─────────────────────────────
def load_bio(con, path: Path, doc: dict, verbose: bool) -> dict:
    batch = doc.get("batch_id") or path.stem
    retrieved = doc.get("retrieved_at")
    if not retrieved:
        raise LoadError(f"{path.name}: no retrieved_at")
    ups = [dict(u, person_id=canonical_person_id(u.get("person_id")))
           for u in doc.get("updates", [])]
    ids = sorted({u.get("person_id") or "<blank>" for u in ups})
    lake = {pid: (name, orcid) for pid, name, orcid in lto_db.rows(
        con, "SELECT person_id, name, orcid FROM people WHERE person_id IN "
             "(SELECT unnest(?::VARCHAR[]))", [ids])}
    errors = [f"person_id(s) not in people: {', '.join(i for i in ids if i not in lake)}"] \
        if set(ids) - set(lake) else []
    # A person_id typo would put one person's bio on another: the family
    # name (last token) must agree with the lake's.
    for u in ups:
        if u.get("person_id") in lake and u.get("name"):
            if not same_family(u["name"], lake[u["person_id"]][0]):
                errors.append(f"{u['person_id']}: file name {u['name']!r} vs lake "
                              f"{lake[u['person_id']][0]!r}")
    if errors:
        raise LoadError(f"{path.name}: " + "; ".join(errors))

    warn: list[str] = []
    stage = []
    for u in ups:
        row = {"person_id": u["person_id"], "name": lake[u["person_id"]][0]}
        row.update(person_fields(con, u["person_id"], u, retrieved, set(), warn))
        raw_status, ssrc = blank(u.get("status")), blank(u.get("status_source_url"))
        if raw_status and raw_status.lower() not in STATUS_MAP:
            warn.append(f"status {raw_status!r} for {u['person_id']} is not in the people.status "
                        f"vocabulary — not written")
            raw_status = None
        status = STATUS_MAP[raw_status.lower()] if raw_status else None
        if status and not ssrc:
            warn.append(f"status {status!r} for {u['person_id']} has no status_source_url "
                        f"— not written")
            status = None
        row["status"] = status
        bits = []
        cur = ", ".join(x for x in (blank(u.get("current_title")),
                                    blank(u.get("current_affiliation"))) if x)
        if cur:
            bits.append(f"current: {cur}")
        if status:
            bits.append(f"status {raw_status} per {ssrc}")
        if blank(u.get("notes")):
            bits.append(u["notes"].strip())
        row["note_add"] = f"[{batch}] " + "; ".join(bits) if bits else None
        stage.append(row)
    stage_people(con, stage)
    ps = merge_people(con, authoritative=True)
    lto_db.assert_integrity(con, ["people"])
    print(f"[{batch}] people: {len(ups)} updates; {ps['changed']} changed, "
          f"{ps['unchanged']} unchanged")
    for w in warn if verbose else warn[:5]:
        print(f"    [warn] {w}")
    if not verbose and len(warn) > 5:
        print(f"    … {len(warn) - 5} more warnings (--verbose)")
    return {"people_new": 0, "people_changed": ps["changed"], "fp_new": 0, "fp_changed": 0,
            "superseded": 0, "verified": 0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", type=Path,
                    help=f"JSON files (default: data/raw/{RESEARCH_GLOB} then data/raw/{BIO_GLOB})")
    ap.add_argument("--dry-run", action="store_true",
                    help="apply each file inside a transaction, print the diff, roll back. "
                         "Files are rolled back one by one, so a person new in two files "
                         "counts as new in both")
    ap.add_argument("--verbose", action="store_true")
    lto_db.add_argparse_catalog(ap)
    args = ap.parse_args()

    files = args.files or (sorted(RAW.glob(RESEARCH_GLOB)) + sorted(RAW.glob(BIO_GLOB)))
    if not files:
        print(f"[error] no input files under data/raw/{RESEARCH_GLOB} or {BIO_GLOB}",
              file=sys.stderr)
        return 2
    roles = load_roles()
    con = lto_db.connect(catalog=args.catalog, data=args.lake_data)

    # The provenance columns are new in schema.sql; a lake built before them
    # gets them in place (a rebuild would discard unexported lake changes).
    migrate = not ensure_columns(con)
    if migrate and not args.dry_run:
        with lto_db.transaction(con, "schema: people provenance columns, "
                                     "facility_personnel.is_current/evidence"):
            print(f"[schema] {lto_db.ensure_schema(con)}")

    # A row one batch confirmed is not downgraded by another batch that
    # looked at different pages and did not find it.
    confirmed_elsewhere = set()
    for path in files:
        try:
            for v in json.loads(path.read_text()).get("verifications") or []:
                if v.get("status") == "confirmed":
                    confirmed_elsewhere.add((canonical_person_id(v.get("person_id")),
                                             v.get("facility_id"),
                                             v.get("existing_role")))
        except (OSError, json.JSONDecodeError):
            pass
    confirmed_elsewhere = frozenset(confirmed_elsewhere)

    totals: Counter = Counter()
    failed = []
    for path in files:
        try:
            doc = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"[error] {path}: {e}", file=sys.stderr)
            failed.append(path.name)
            continue
        kind = "bio" if "updates" in doc else "research"
        try:
            with lto_db.transaction(con, f"load_people_research: {doc.get('batch_id') or path.stem}"):
                if migrate and args.dry_run:
                    lto_db.ensure_schema(con)
                if kind == "bio":
                    s = load_bio(con, path, doc, args.verbose)
                else:
                    s = load_research(con, path, doc, roles, args.verbose, confirmed_elsewhere)
                totals.update(s)
                if args.dry_run:
                    raise _DryRun
        except _DryRun:
            pass
        except (LoadError, lto_db.IntegrityError) as e:
            print(f"[error] {e}", file=sys.stderr)
            failed.append(path.name)

    mode = "[dry-run] would write" if args.dry_run else "[done]"
    print(f"{mode} {len(files) - len(failed)} file(s): people {totals['people_new']} new / "
          f"{totals['people_changed']} updated; affiliations {totals['fp_new']} new / "
          f"{totals['fp_changed']} updated; {totals['superseded']} superseded; "
          f"{totals['verified']} verification(s) applied")
    if failed:
        print(f"[error] {len(failed)} file(s) not loaded: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
