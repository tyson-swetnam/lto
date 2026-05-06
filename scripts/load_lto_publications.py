#!/usr/bin/env python3
"""Load Wave-H H-PUB-* JSON outputs into publications + authorship.

Reads every `data/raw/H-PUB-*/publications.json` file. Resolves
authorship.person_name → people.person_id by lower-cased name match.
Drops authorship rows whose person isn't in the DB (no hallucinated
author attributions).

Idempotent: publication_id = sha1(doi or lower(title)). Re-running
upserts.

Usage::

    python scripts/load_lto_publications.py
    python scripts/load_lto_publications.py --db db/cod_kmap.duckdb --verbose
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


def publication_id(doi: str | None, title: str | None) -> str:
    key = (doi or "").strip().lower() or (title or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # Pick up Wave-H first-pass + Wave-I loop + Wave-N loop + Wave-O loop pub agents.
    files = sorted(set(
        list(RAW_DIR.glob("H-PUB-*/publications.json"))
        + list(RAW_DIR.glob("I-*/publications.json"))
        + list(RAW_DIR.glob("N-PUB-*/publications.json"))
        + list(RAW_DIR.glob("O-PUB-*/publications.json"))
    ))
    print(f"[load_lto_publications] reading {len(files)} agent files")

    inserted_pubs = 0
    inserted_auth = 0
    skipped_pub = 0
    skipped_auth = 0
    warnings: list[str] = []

    with duckdb.connect(str(args.db)) as conn:
        # Build name → person_id resolver from existing people table.
        name_to_pid: dict[str, str] = {}
        for pid, name in conn.execute("SELECT person_id, name FROM people").fetchall():
            if name:
                name_to_pid[name.strip().lower()] = pid

        for path in files:
            try:
                doc = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                print(f"[skip] {path}: {e}", file=sys.stderr)
                continue

            pubs = doc.get("publications", [])
            auths = doc.get("authorship", [])
            # Some agents emit `authorship_by_title` for entries without DOI.
            auths_by_title = doc.get("authorship_by_title", [])

            # Build doi → pub_id and title → pub_id resolvers from this file.
            doi_to_pid: dict[str, str] = {}
            title_to_pid: dict[str, str] = {}
            for p in pubs:
                doi = p.get("doi")
                title = p.get("title")
                pid = publication_id(doi, title)
                doi_to_pid[(doi or "").strip().lower()] = pid
                title_to_pid[(title or "").strip().lower()] = pid

                try:
                    # Pre-clear any existing row with this DOI (to honor "upsert" semantics
                    # despite DuckDB's two-unique-constraint limitation on INSERT OR REPLACE).
                    if doi:
                        conn.execute("DELETE FROM publications WHERE doi = ?", [doi])
                    conn.execute("DELETE FROM publications WHERE publication_id = ?", [pid])
                    conn.execute(
                        """
                        INSERT INTO publications (
                            publication_id, doi, title, abstract, pub_year, pub_type,
                            journal, venue, cited_by_count, openalex_id,
                            scopus_eid, wos_uid, url, source, retrieved_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        [
                            pid, doi, title, p.get("abstract"),
                            p.get("pub_year"), p.get("pub_type") or "journal-article",
                            p.get("journal"), p.get("venue"),
                            p.get("cited_by_count") or 0,
                            p.get("openalex_id"), p.get("scopus_eid"), p.get("wos_uid"),
                            p.get("url") or (f"https://doi.org/{doi}" if doi else None),
                            p.get("source") or path.parent.name,
                            p.get("retrieved_at") or "2026-05-05",
                        ],
                    )
                    inserted_pubs += 1
                except duckdb.Error as e:
                    skipped_pub += 1
                    warnings.append(f"  pub insert failed: {title}: {e}")

            # Authorship by DOI.
            for a in auths:
                doi = (a.get("doi") or "").strip().lower()
                pid = doi_to_pid.get(doi)
                if not pid and a.get("title"):
                    pid = title_to_pid.get(a["title"].strip().lower())
                if not pid:
                    skipped_auth += 1
                    continue

                pname = (a.get("person_name") or "").strip().lower()
                person_pid = name_to_pid.get(pname)
                if not person_pid:
                    skipped_auth += 1
                    warnings.append(f"  authorship: no person '{a.get('person_name')}' in DB")
                    continue

                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO authorship (
                            person_id, publication_id, author_position,
                            is_corresponding, raw_name
                        ) VALUES (?,?,?,?,?)
                        """,
                        [
                            person_pid, pid,
                            a.get("author_position"),
                            bool(a.get("is_corresponding")),
                            a.get("raw_name") or a.get("person_name"),
                        ],
                    )
                    inserted_auth += 1
                except duckdb.Error as e:
                    skipped_auth += 1
                    warnings.append(f"  authorship insert failed: {pname}: {e}")

            # Authorship by title (NEON agent format).
            for a in auths_by_title:
                title = (a.get("title") or "").strip().lower()
                pid = title_to_pid.get(title)
                if not pid:
                    skipped_auth += 1
                    continue
                pname = (a.get("person_name") or "").strip().lower()
                person_pid = name_to_pid.get(pname)
                if not person_pid:
                    skipped_auth += 1
                    continue
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO authorship (
                            person_id, publication_id, author_position,
                            is_corresponding, raw_name
                        ) VALUES (?,?,?,?,?)
                        """,
                        [
                            person_pid, pid,
                            a.get("author_position"),
                            bool(a.get("is_corresponding")),
                            a.get("raw_name") or a.get("person_name"),
                        ],
                    )
                    inserted_auth += 1
                except duckdb.Error:
                    skipped_auth += 1

        print(f"[load_lto_publications] inserted {inserted_pubs} publications, {inserted_auth} authorship rows")
        print(f"[load_lto_publications] skipped: {skipped_pub} pubs, {skipped_auth} authorships")
        if args.verbose and warnings:
            print("\n".join(warnings[:25]))
            if len(warnings) > 25:
                print(f"  … {len(warnings) - 25} more suppressed")

        n_pubs = conn.execute("SELECT count(*) FROM publications").fetchone()[0]
        n_auth = conn.execute("SELECT count(*) FROM authorship").fetchone()[0]
        n_people_pubd = conn.execute("SELECT count(DISTINCT person_id) FROM authorship").fetchone()[0]
        print(f"[load_lto_publications] DB now: {n_pubs} pubs, {n_auth} authorship rows, {n_people_pubd} people with ≥1 pub")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
