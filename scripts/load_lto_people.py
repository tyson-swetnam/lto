#!/usr/bin/env python3
"""Load Wave-F R-PEOPLE-* JSON outputs into people + facility_personnel.

Reads every `data/raw/R-PEOPLE-*/people.json` file, deduplicates people
across files (one ORCID/name → one canonical row), resolves each
affiliation's `facility_canonical_name` + `facility_acronym` to the
existing `facilities.facility_id`, and inserts upsert-style.

Idempotent: re-running just refreshes existing rows.

Usage::

    python scripts/load_lto_people.py
    python scripts/load_lto_people.py --db db/cod_kmap.duckdb

Companion to `load_facility_personnel.py` which loads from a hand-curated
CSV — this one is for the agent-emitted JSON path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
RAW_DIR = ROOT / "data" / "raw"


def person_id(name: str, orcid: str | None = None, email: str | None = None) -> str:
    key = f"{(name or '').strip().lower()}|{(orcid or '').strip()}|{(email or '').strip().lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


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


def resolve_facility(conn: duckdb.DuckDBPyConnection, canonical_name: str, acronym: str | None) -> str | None:
    """Look up facility_id by canonical name + acronym, case-insensitive,
    with a token-overlap fuzzy fallback.

    The cod-kmap ingest merge is first-seen-wins (alphabetical R* order),
    so "Hubbard Brook Experimental Forest" (R-TER-EFR / R-TER-LTER) gets
    absorbed into "Hubbard Brook Watershed 6" (R-AQ-FRESH) when the ILIKE
    + 5km haversine match succeeds. The resolver below tolerates this by
    falling back to a token-set fuzzy match scored ≥85.
    """
    if not canonical_name and not acronym:
        return None
    # 1. Acronym (highest precision)
    if acronym:
        row = conn.execute(
            "SELECT facility_id FROM facilities WHERE upper(acronym) = upper(?) LIMIT 1",
            [acronym],
        ).fetchone()
        if row:
            return row[0]
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
    best = process.extractOne(
        canonical_name, list(name_to_row.keys()),
        scorer=fuzz.token_set_ratio, score_cutoff=85,
    )
    if best:
        return name_to_row[best[0]][0]
    return None


def upsert_people(conn: duckdb.DuckDBPyConnection, people: list[dict]) -> dict[str, str]:
    """Insert/update people. Returns a name -> person_id resolver."""
    name_to_pid: dict[str, str] = {}
    seen_pids: set[str] = set()
    for p in people:
        name = p.get("name") or ""
        if not name:
            continue
        orcid = p.get("orcid")
        email = p.get("email")
        pid = person_id(name, orcid, email)
        # If we already have this person from another agent, dedupe by orcid,
        # otherwise dedupe by name.
        key = orcid or name.strip().lower()
        if key in name_to_pid:
            # Merge identifier coverage: only update if new fields are non-null.
            existing_pid = name_to_pid[key]
            for col in ("orcid", "openalex_id", "google_scholar_id", "scopus_author_id",
                        "wos_researcher_id", "homepage_url", "photo_url",
                        "research_interests", "bio", "status", "email"):
                v = p.get(col)
                if v:
                    conn.execute(
                        f"UPDATE people SET {col} = COALESCE({col}, ?) WHERE person_id = ?",
                        [v, existing_pid],
                    )
            name_to_pid[name.strip().lower()] = existing_pid
            continue

        name_to_pid[key] = pid
        name_to_pid[name.strip().lower()] = pid
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        conn.execute(
            """
            INSERT OR REPLACE INTO people (
                person_id, name, name_family, name_given, email,
                orcid, openalex_id, scopus_author_id, wos_researcher_id,
                google_scholar_id, homepage_url, photo_url,
                research_interests, bio, status, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                pid, name, p.get("name_family"), p.get("name_given"), email,
                orcid, p.get("openalex_id"), p.get("scopus_author_id"),
                p.get("wos_researcher_id"), p.get("google_scholar_id"),
                p.get("homepage_url"), p.get("photo_url"),
                p.get("research_interests"), p.get("bio"),
                p.get("status"), p.get("notes"),
            ],
        )
    return name_to_pid


def insert_affiliations(conn: duckdb.DuckDBPyConnection, affils: list[dict],
                        name_to_pid: dict[str, str]) -> tuple[int, int, list[str]]:
    inserted = 0
    skipped = 0
    warnings: list[str] = []
    for a in affils:
        pname = (a.get("person_name") or "").strip()
        pid = name_to_pid.get(pname.lower())
        if not pid:
            skipped += 1
            warnings.append(f"  no person for affiliation: '{pname}'")
            continue
        fid = resolve_facility(conn, a.get("facility_canonical_name"), a.get("facility_acronym"))
        if not fid:
            skipped += 1
            warnings.append(f"  no facility for {pname}: '{a.get('facility_canonical_name')}'")
            continue
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO facility_personnel (
                    person_id, facility_id, role, title,
                    is_key_personnel, start_date, end_date,
                    source, source_url, retrieved_at, confidence, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    pid, fid,
                    a.get("role") or "faculty",
                    a.get("title"),
                    bool(a.get("is_key_personnel")),
                    a.get("start_date"), a.get("end_date"),
                    a.get("source"), a.get("source_url"),
                    a.get("retrieved_at") or "2026-05-05",
                    a.get("confidence") or "medium",
                    a.get("notes"),
                ],
            )
            inserted += 1
        except duckdb.Error as e:
            skipped += 1
            warnings.append(f"  insert failed for {pname} @ {a.get('facility_canonical_name')}: {e}")
    return inserted, skipped, warnings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    people, affils = load_files()
    print(f"[load_lto_people] read {len(people)} people, {len(affils)} affiliations from R-PEOPLE-*")

    with duckdb.connect(str(args.db)) as conn:
        name_to_pid = upsert_people(conn, people)
        print(f"[load_lto_people] upserted {conn.execute('SELECT count(*) FROM people').fetchone()[0]} people")

        inserted, skipped, warnings = insert_affiliations(conn, affils, name_to_pid)
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
        ).fetchone()
        print(
            f"[load_lto_people] coverage — people {stats[0]} / orcid {stats[1]} "
            f"/ openalex {stats[2]} / gscholar {stats[3]} / homepage {stats[4]}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
