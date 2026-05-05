#!/usr/bin/env python3
"""Merge duplicate-name `people` rows and null-out conflicting ORCIDs.

Wave F-1 sub-agents emitted overlapping people across spheres (e.g.
Gene E. Likens appears in R-PEOPLE-LTER, R-PEOPLE-OTHER, R-PEOPLE-FRESH).
Some agents supplied an ORCID; others didn't; a few supplied conflicting
ORCIDs. The cod-kmap `person_id = hash(name||orcid||email)` produces a
DIFFERENT row for each ORCID variant, so the upsert path doesn't actually
merge them.

This script:
  1. Groups people rows by lower(name).
  2. For each group, picks a canonical person_id (the one with the
     fewest null fields; ties broken by first-seen).
  3. Repoints facility_personnel rows to the canonical person_id.
  4. For ORCIDs that conflict across the duplicates → null the field on
     the canonical row, leave a note in `notes` flagging that
     enrichment must verify against the public ORCID API.
  5. Deletes the redundant person rows.

Idempotent: safe to re-run; if there are no duplicates, exits cleanly.

Usage::

    python scripts/dedupe_people.py
    python scripts/dedupe_people.py --db db/cod_kmap.duckdb --dry-run
"""
from __future__ import annotations

import argparse
from pathlib import Path
from collections import defaultdict

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with duckdb.connect(str(args.db)) as conn:
        # Pull all people grouped by lowercased name.
        rows = conn.execute(
            "SELECT person_id, name, orcid, openalex_id, google_scholar_id, "
            "       homepage_url, email, research_interests, status, notes "
            "FROM people"
        ).fetchall()
        groups: dict[str, list[tuple]] = defaultdict(list)
        for r in rows:
            groups[(r[1] or "").strip().lower()].append(r)

        merges = 0
        orcid_conflicts = 0
        for name_key, recs in groups.items():
            if len(recs) < 2:
                continue
            # Score by non-null field count; pick the canonical.
            def score(r):
                return sum(1 for v in r[2:] if v) * 100 + (-rows.index(r))  # tie-break: earlier rows lose
            canonical = max(recs, key=score)
            others = [r for r in recs if r[0] != canonical[0]]
            canonical_pid = canonical[0]

            # Detect ORCID conflicts (any non-null ORCID different from canonical's).
            canonical_orcid = canonical[2]
            conflict_orcids = sorted({r[2] for r in recs if r[2] and r[2] != canonical_orcid})
            if conflict_orcids:
                orcid_conflicts += 1
                merged_note = (canonical[9] or "") + (
                    f" [DEDUPE] conflicting ORCIDs across agents: "
                    f"canonical={canonical_orcid or 'NULL'}; others={','.join(conflict_orcids)}; "
                    f"NULLED until enrichment API verifies."
                )
                if not args.dry_run:
                    conn.execute(
                        "UPDATE people SET orcid = NULL, notes = ? WHERE person_id = ?",
                        [merged_note.strip(), canonical_pid],
                    )

            # Coalesce missing identifiers from other rows into canonical.
            for col in ("openalex_id", "google_scholar_id", "scopus_author_id",
                        "wos_researcher_id", "homepage_url", "research_interests"):
                if not args.dry_run:
                    conn.execute(
                        f"""
                        UPDATE people
                        SET {col} = COALESCE({col}, (
                            SELECT {col} FROM people p2
                            WHERE lower(p2.name) = ? AND p2.{col} IS NOT NULL
                            LIMIT 1
                        ))
                        WHERE person_id = ?
                        """,
                        [name_key, canonical_pid],
                    )

            # Repoint facility_personnel from each duplicate to canonical.
            # DuckDB doesn't support UPDATE OR IGNORE, so we copy non-conflicting
            # rows then delete originals.
            for r in others:
                pid = r[0]
                if not args.dry_run:
                    # Copy affiliations not already present at canonical.
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO facility_personnel
                        SELECT ?, facility_id, role, title,
                               is_key_personnel, start_date, end_date,
                               source, source_url, retrieved_at, confidence, notes
                        FROM facility_personnel WHERE person_id = ?
                        """,
                        [canonical_pid, pid],
                    )
                    conn.execute(
                        "DELETE FROM facility_personnel WHERE person_id = ?",
                        [pid],
                    )
                    # Same idea for authorship / person_areas.
                    for table, cols in (
                        ("authorship", "publication_id, author_position, is_corresponding, raw_name"),
                        ("person_areas", "area_id, weight, evidence_count, source"),
                    ):
                        conn.execute(
                            f"INSERT OR IGNORE INTO {table} SELECT ?, {cols} FROM {table} WHERE person_id = ?",
                            [canonical_pid, pid],
                        )
                        conn.execute(
                            f"DELETE FROM {table} WHERE person_id = ?",
                            [pid],
                        )
                    conn.execute("DELETE FROM people WHERE person_id = ?", [pid])
                merges += 1

            if args.dry_run and conflict_orcids:
                print(f"  [conflict] {canonical[1]:30s}  ORCIDs={conflict_orcids}")

        # Stats after.
        n_people = conn.execute("SELECT count(*) FROM people").fetchone()[0]
        n_orcid = conn.execute("SELECT count(*) FROM people WHERE orcid IS NOT NULL").fetchone()[0]
        n_strong = conn.execute(
            "SELECT count(*) FROM people WHERE orcid IS NOT NULL OR openalex_id IS NOT NULL OR google_scholar_id IS NOT NULL"
        ).fetchone()[0]

    mode = "[dry-run] would have" if args.dry_run else "[dedupe]"
    print(f"{mode} merged {merges} duplicate person rows; flagged {orcid_conflicts} ORCID conflicts.")
    print(f"After cleanup: {n_people} unique people, {n_orcid} with ORCID, {n_strong} with any strong-ID.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
