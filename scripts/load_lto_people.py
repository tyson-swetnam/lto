#!/usr/bin/env python3
"""Load Wave-F R-PEOPLE-* JSON outputs into people + facility_personnel.

Reads every `data/raw/R-PEOPLE-*/people.json` file, deduplicates people
across files (one ORCID/name → one canonical row), resolves each
affiliation's `facility_canonical_name` + `facility_acronym` to the
existing `facilities.facility_id`, and inserts upsert-style.

Idempotent: re-running just refreshes existing rows. Writes go to the
DuckLake store of record (scripts/lto_db.py) as one snapshot per run.

person_id is the name-only stable hash (load_people_research.stable_person_id);
a person who already carries the same ORCID / OpenAlex id, or who exists
under the pre-lake name|orcid|email hash, keeps that row's id. Existing
ids never change.

Usage::

    python scripts/load_lto_people.py
    python scripts/load_lto_people.py --catalog /tmp/scratch/cat.sqlite

Companion to `load_facility_personnel.py` which loads from a hand-curated
CSV — this one is for the agent-emitted JSON path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_people_research import (  # noqa: E402
    legacy_person_id, norm_orcid, resolve_person_id)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

PEOPLE_COLS = ["person_id", "name", "name_family", "name_given", "email",
               "orcid", "openalex_id", "scopus_author_id", "wos_researcher_id",
               "google_scholar_id", "homepage_url", "photo_url",
               "research_interests", "bio", "status", "notes"]
FP_COLS = ["person_id", "facility_id", "role", "title", "is_key_personnel",
           "start_date", "end_date", "source", "source_url", "retrieved_at",
           "confidence", "notes"]


def load_files() -> tuple[list[dict], list[dict]]:
    people, affils = [], []
    # Pick up Wave-F first-pass + Wave-I loop + Wave-K fill agents,
    # plus any future people emissions from the J-A archive agents
    # (NMFS / USACE-NRL-NASA write people.json alongside their archives).
    for d in sorted(set(
            list(RAW_DIR.glob("R-PEOPLE-*/people.json")) +
            list(RAW_DIR.glob("K-*/people.json")) +
            list(RAW_DIR.glob("J-*/people.json")) +
            list(RAW_DIR.glob("Q-ENRICH-*/additional_people.json"))
    )):
        try:
            doc = json.loads(d.read_text())
        except json.JSONDecodeError as e:
            print(f"[skip] {d}: {e}", file=sys.stderr)
            continue
        agent = d.parent.name
        for p in doc.get("people", []):
            p["_agent"] = agent
            people.append(p)
        for a in doc.get("affiliations", []):
            a["_agent"] = agent
            affils.append(a)
    return people, affils


def resolve_facility(conn, canonical_name: str, acronym: str | None,
                     warn: list[str] | None = None) -> str | None:
    """Look up facility_id by canonical name + acronym, case-insensitive,
    with a token-overlap fuzzy fallback.

    The cod-kmap ingest merge is first-seen-wins (alphabetical R* order),
    so "Hubbard Brook Experimental Forest" (R-TER-EFR / R-TER-LTER) gets
    absorbed into "Hubbard Brook Watershed 6" (R-AQ-FRESH) when the ILIKE
    + 5km haversine match succeeds. The resolver below tolerates this by
    falling back to a token-set fuzzy match scored ≥85.

    An acronym is only trusted when exactly one facility carries it. 29
    facilities once shared "NERR" (19 "NEP", 9 "LTER"), and the
    old LIMIT 1 put 27 reserve managers from 27 reserves on Mission Aransas
    NERR. data/seed/facility_fixes.csv has since given each reserve and
    estuary program its own acronym or NULL. A shared acronym falls through
    to the name steps instead.
    """
    warn = warn if warn is not None else []
    if not canonical_name and not acronym:
        return None
    # 1. Acronym (highest precision) — only when it names one facility.
    if acronym:
        rows = conn.execute(
            "SELECT facility_id FROM facilities WHERE upper(acronym) = upper(?) "
            "ORDER BY facility_id LIMIT 2",
            [acronym],
        ).fetchall()
        if len(rows) == 1:
            return rows[0][0]
        if rows:
            warn.append(f"  acronym {acronym!r} is shared by several facilities; "
                        f"resolving {canonical_name!r} by name")
    if not canonical_name:
        return None
    # 2. Exact canonical name match
    row = conn.execute(
        "SELECT facility_id FROM facilities WHERE lower(canonical_name) = lower(?) LIMIT 1",
        [canonical_name],
    ).fetchone()
    if row:
        return row[0]
    # 3. ILIKE substring (single hit)
    rows = conn.execute(
        "SELECT facility_id FROM facilities WHERE canonical_name ILIKE ? LIMIT 2",
        [f"%{canonical_name}%"],
    ).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    # 4. Token-set fuzzy match against all facility names
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return None
    candidates = conn.execute(
        "SELECT facility_id, canonical_name, acronym FROM facilities"
    ).fetchall()
    name_to_row = {c[1]: c for c in candidates}
    best = process.extract(
        canonical_name, list(name_to_row.keys()),
        scorer=fuzz.token_set_ratio, score_cutoff=85, limit=2,
    )
    # token_set_ratio scores 100 whenever one name's tokens are a subset of
    # the other's, which is how USGS Water Mission Area leadership landed on
    # "USGS Gauge 01400500 — Raritan River". Require the whole names to be
    # alike too (token_sort_ratio), and a clear winner.
    if not best:
        return None
    if len(best) > 1 and best[0][1] - best[1][1] < 5:
        warn.append(f"  fuzzy match for {canonical_name!r} is ambiguous: "
                    f"{best[0][0]!r} / {best[1][0]!r}")
        return None
    if fuzz.token_sort_ratio(canonical_name, best[0][0]) < 70:
        warn.append(f"  fuzzy match {canonical_name!r} -> {best[0][0]!r} rejected "
                    f"(names differ beyond a shared subset)")
        return None
    return name_to_row[best[0][0]][0]


def upsert_people(conn, people: list[dict]) -> dict[str, str]:
    """Insert/update people. Returns a name -> person_id resolver.

    Records for the same person across agent files (same ORCID, else same
    name) collapse to one row: the first record wins, later ones only fill
    its empty fields. That row then merges into the lake with COALESCE, so
    a field the files leave empty never erases one already there.

    resolve_person_id() only sees the lake, so two records of this run can
    resolve to one id that is staged but not yet written. That is checked
    here the way resolve_person_id checks the lake: a record whose ORCID or
    OpenAlex id conflicts with the staged row's is a namesake and is kept
    apart under its legacy id; otherwise it is the same person and fills
    the staged row's empty fields (so a no-ORCID record seen first does not
    swallow the ORCID record that follows it).
    """
    name_to_pid: dict[str, str] = {}
    merged: dict[str, dict] = {}
    for p in people:
        name = p.get("name") or ""
        if not name:
            continue
        orcid = p.get("orcid")
        email = p.get("email")
        # If we already have this person from another agent, dedupe by orcid,
        # otherwise dedupe by name.
        key = orcid or name.strip().lower()
        if key in name_to_pid:
            # Merge identifier coverage: only fill fields still empty.
            existing_pid = name_to_pid[key]
            for col in ("orcid", "openalex_id", "google_scholar_id", "scopus_author_id",
                        "wos_researcher_id", "homepage_url", "photo_url",
                        "research_interests", "bio", "status", "email"):
                v = p.get(col)
                if v and not merged[existing_pid].get(col):
                    merged[existing_pid][col] = v
            name_to_pid[name.strip().lower()] = existing_pid
            continue

        pid = resolve_person_id(conn, name, orcid, p.get("openalex_id"),
                                legacy_id=legacy_person_id(name, orcid, email))
        while pid in merged:
            m = merged[pid]
            oa = p.get("openalex_id")
            if ((orcid and m.get("orcid") and norm_orcid(m["orcid"]) != norm_orcid(orcid))
                    or (oa and m.get("openalex_id")
                        and m["openalex_id"].upper() != oa.upper())):
                alt = legacy_person_id(name, orcid or oa, email)
                if alt == pid:            # cannot happen for distinct ids; stay safe
                    alt = legacy_person_id(name, orcid or oa, f"{email or ''}#{pid}")
                pid = alt                 # namesake: keep apart (re-check alt)
                continue
            for col in PEOPLE_COLS:       # same person: fill its empty fields
                if col not in ("person_id", "name") and p.get(col) and not m.get(col):
                    m[col] = p[col]
            break
        name_to_pid[key] = pid
        name_to_pid[name.strip().lower()] = pid
        if pid in merged:
            continue
        row = {c: p.get(c) for c in PEOPLE_COLS}
        row.update(person_id=pid, name=name)
        merged[pid] = row

    conn.execute("CREATE OR REPLACE TEMP TABLE _stage_people ("
                 + ", ".join(f"{c} VARCHAR" for c in PEOPLE_COLS) + ")")
    if merged:                            # executemany rejects an empty list
        conn.executemany(
            f"INSERT INTO _stage_people VALUES ({', '.join('?' for _ in PEOPLE_COLS)})",
            [[r.get(c) for c in PEOPLE_COLS] for r in merged.values()])
    stats = lto_db.merge_upsert(conn, "people", ["person_id"], "_stage_people",
                                coalesce=True, extra_set={"updated_at": "now()"})
    print(f"[load_lto_people] people merge: {stats}")
    return name_to_pid


def insert_affiliations(conn, affils: list[dict],
                        name_to_pid: dict[str, str]) -> tuple[int, int, list[str]]:
    skipped = 0
    warnings: list[str] = []
    rows = []
    for a in affils:
        pname = (a.get("person_name") or "").strip()
        pid = name_to_pid.get(pname.lower())
        if not pid:
            skipped += 1
            warnings.append(f"  no person for affiliation: '{pname}'")
            continue
        fid = resolve_facility(conn, a.get("facility_canonical_name"), a.get("facility_acronym"),
                               warnings)
        if not fid:
            skipped += 1
            warnings.append(f"  no facility for {pname}: '{a.get('facility_canonical_name')}'")
            continue
        rows.append([
            pid, fid,
            a.get("role") or "faculty",
            a.get("title"),
            bool(a.get("is_key_personnel")),
            a.get("start_date"), a.get("end_date"),
            a.get("source"), a.get("source_url"),
            a.get("retrieved_at") or "2026-05-05",
            a.get("confidence") or "medium",
            a.get("notes"),
            len(rows),
        ])
    conn.execute("""CREATE OR REPLACE TEMP TABLE _stage_fp (
        person_id VARCHAR, facility_id VARCHAR, role VARCHAR, title VARCHAR,
        is_key_personnel BOOLEAN, start_date DATE, end_date DATE, source VARCHAR,
        source_url VARCHAR, retrieved_at DATE, confidence VARCHAR, notes VARCHAR,
        _seq INTEGER)""")
    if rows:
        conn.executemany("INSERT INTO _stage_fp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    # Row replace on (person_id, facility_id, role), last record wins — what
    # the per-row INSERT OR REPLACE did.
    stats = lto_db.merge_upsert(conn, "facility_personnel",
                                ["person_id", "facility_id", "role"], "_stage_fp",
                                order_by="_seq DESC")
    return stats["unique_keys"], skipped, warnings


def catalog_arg(args) -> Path | None:
    """--db is the pre-lake flag, kept as an alias of --catalog. The retired
    db/lto.duckdb file itself is not a catalog, so it is ignored."""
    if args.db is None or args.catalog is not None:
        return args.catalog
    if args.db.suffix == ".duckdb":
        print(f"[deprecated] --db {args.db} ignored (db/lto.duckdb is retired); "
              f"use --catalog", file=sys.stderr)
        return None
    return args.db


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", type=Path, default=None,
                    help="deprecated alias of --catalog (a db/lto.duckdb path is ignored)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    people, affils = load_files()
    print(f"[load_lto_people] read {len(people)} people, {len(affils)} affiliations from R-PEOPLE-*")

    conn = lto_db.connect(catalog=catalog_arg(args), data=args.lake_data)
    with lto_db.transaction(conn, f"load_lto_people: {len(people)} people, "
                                  f"{len(affils)} affiliations from agent JSON"):
        name_to_pid = upsert_people(conn, people)
        print(f"[load_lto_people] upserted {lto_db.scalar(conn, 'SELECT count(*) FROM people')} people")

        inserted, skipped, warnings = insert_affiliations(conn, affils, name_to_pid)
        lto_db.assert_integrity(conn, ["people", "facility_personnel"])
        print(f"[load_lto_people] inserted {inserted} affiliations, skipped {skipped}")
        if warnings and args.verbose:
            print("\n".join(warnings[:20]))
            if len(warnings) > 20:
                print(f"  … {len(warnings) - 20} more warnings suppressed")

        # Sanity stats
        stats = conn.execute(
            """
            SELECT
                count(*) AS n_people,
                count(orcid) AS n_orcid,
                count(openalex_id) AS n_openalex,
                count(google_scholar_id) AS n_gscholar,
                count(homepage_url) AS n_homepage
            FROM people
            """
        ).fetchall()[0]
        print(
            f"[load_lto_people] coverage — people {stats[0]} / orcid {stats[1]} "
            f"/ openalex {stats[2]} / gscholar {stats[3]} / homepage {stats[4]}"
        )

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
