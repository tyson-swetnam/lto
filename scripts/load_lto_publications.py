#!/usr/bin/env python3
"""Load Wave-H H-PUB-* JSON outputs into publications + authorship.

Reads every `data/raw/H-PUB-*/publications.json` file. Resolves
authorship.person_name → people.person_id by lower-cased name match.
Drops authorship rows whose person isn't in the DB (no hallucinated
author attributions).

Idempotent: publication_id = sha1(doi or lower(title)). Re-running
upserts. One run is one DuckLake snapshot (scripts/lto_db.py): rows are
collected in file order and written at the end. Within the run a
publication replaces any earlier staged one with its DOI or id, and an
authorship row replaces any earlier one with its key.

Against the lake, a publication whose id is already there is *filled
in*, never overwritten: a column the lake already holds (journal,
abstract, openalex_id, source, a corrected year, ...) keeps its value
and only NULL columns take the agent's. Agent JSON carries a subset of
the columns and is often recalled rather than fetched, so replacing the
row would blank what OpenAlex enrichment wrote. (DuckDB used to block
that DELETE whenever authorship pointed at the row, so enriched rows
were in practice never replaced.) A lake row with the same DOI under
another id is replaced only when nothing points at it
(``doi_held_elsewhere``).

Usage::

    python scripts/load_lto_publications.py
    python scripts/load_lto_publications.py --catalog db/lto_catalog.sqlite --verbose
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_lto_archives import row_error  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"


def publication_id(doi: str | None, title: str | None) -> str:
    key = (doi or "").strip().lower() or (title or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


PUB_COLS = ["publication_id", "doi", "title", "abstract", "pub_year", "pub_type",
            "journal", "venue", "cited_by_count", "openalex_id", "scopus_eid", "wos_uid",
            "url", "source", "retrieved_at"]
AUTH_COLS = ["person_id", "publication_id", "author_position", "is_corresponding", "raw_name"]


def doi_held_elsewhere(conn, doi: str, pid: str, staged_auth: set[str]) -> bool:
    """A lake publication with this DOI under another id has authorship
    (in the lake or staged by this run) or topic rows. Replacing it would
    orphan them (DuckDB refused that DELETE, and the new publication was
    skipped), so it is still skipped."""
    for (other, has_children) in lto_db.rows(conn, """
            SELECT p.publication_id,
                   EXISTS (SELECT 1 FROM authorship a WHERE a.publication_id = p.publication_id)
                   OR EXISTS (SELECT 1 FROM publication_topics t
                              WHERE t.publication_id = p.publication_id)
            FROM publications p WHERE p.doi = ? AND p.publication_id <> ?""", [doi, pid]):
        if has_children or other in staged_auth:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path, help="deprecated alias of --catalog")
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

    staged: dict[str, dict] = {}         # publication_id -> row, last write wins
    del_dois: set[str] = set()           # lake rows each staged publication replaces
    del_pids: set[str] = set()
    auth_rows: list[list] = []
    auth_pids: set[str] = set()          # publications that staged authorship points at

    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    with lto_db.transaction(conn, f"load_lto_publications: publications + authorship from "
                                  f"{len(files)} agent files"):
        # Build name → person_id resolver from existing people table.
        name_to_pid: dict[str, str] = {}
        for pid, name in conn.execute("SELECT person_id, name FROM people").fetchall():
            if name:
                name_to_pid[name.strip().lower()] = pid

        def auth_error(pub_id: str, row: list) -> str | None:
            # The person comes from the people table; the publication must
            # be staged by this run, or be in the lake and not replaced by it.
            if pub_id not in staged:
                lake = lto_db.rows(conn, "SELECT doi FROM publications WHERE publication_id = ?",
                                   [pub_id])
                if not lake or pub_id in del_pids or (lake[0][0] and lake[0][0] in del_dois):
                    return f"publication {pub_id} was not loaded"
            return row_error(conn, "authorship", dict(zip(AUTH_COLS, row)), fks=False)

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

                row = dict(zip(PUB_COLS, [
                    pid, doi, title, p.get("abstract"),
                    p.get("pub_year"), p.get("pub_type") or "journal-article",
                    p.get("journal"), p.get("venue"),
                    p.get("cited_by_count") or 0,
                    p.get("openalex_id"), p.get("scopus_eid"), p.get("wos_uid"),
                    p.get("url") or (f"https://doi.org/{doi}" if doi else None),
                    p.get("source") or path.parent.name,
                    p.get("retrieved_at") or "2026-05-05",
                ]))
                err = row_error(conn, "publications", row)
                # Pre-clear any existing row with this DOI (to honor "upsert" semantics
                # despite the two-unique-constraint (id, doi) table) — unless
                # that row, in the lake or staged, has authorship pointing at it.
                gone = [k for k, v in staged.items() if k == pid or (doi and v["doi"] == doi)]
                if err is None and doi and (doi_held_elsewhere(conn, doi, pid, auth_pids)
                                            or any(k != pid and k in auth_pids for k in gone)):
                    err = f"DOI {doi} belongs to another publication that has authorship"
                if err:
                    skipped_pub += 1
                    warnings.append(f"  pub insert failed: {title}: {err}")
                    continue
                for k in gone:
                    del staged[k]
                staged[pid] = row
                if doi:
                    del_dois.add(doi)
                del_pids.add(pid)
                inserted_pubs += 1

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

                row = [
                    person_pid, pid,
                    a.get("author_position"),
                    bool(a.get("is_corresponding")),
                    a.get("raw_name") or a.get("person_name"),
                ]
                err = auth_error(pid, row)
                if err is None:
                    auth_rows.append(row)
                    auth_pids.add(pid)
                    inserted_auth += 1
                else:
                    skipped_auth += 1
                    warnings.append(f"  authorship insert failed: {pname}: {err}")

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
                row = [
                    person_pid, pid,
                    a.get("author_position"),
                    bool(a.get("is_corresponding")),
                    a.get("raw_name") or a.get("person_name"),
                ]
                err = auth_error(pid, row)
                if err is None:
                    auth_rows.append(row)
                    auth_pids.add(pid)
                    inserted_auth += 1
                else:
                    skipped_auth += 1

        # Write: lake rows the staged publications supersede under ANOTHER
        # id (same DOI, or an id staged earlier and then replaced in this
        # run) go; rows whose id is staged are merged fill-only (the lake's
        # non-NULL values win), so enrichment is never blanked. Then
        # authorship (last row per key wins, as INSERT OR REPLACE did).
        conn.execute("DELETE FROM publications WHERE (doi IN (SELECT unnest(?)) "
                     "OR publication_id IN (SELECT unnest(?))) "
                     "AND publication_id NOT IN (SELECT unnest(?))",
                     [sorted(del_dois), sorted(del_pids), sorted(staged)])
        lto_db.create_temp_like(conn, "_pubs", f"SELECT {', '.join(PUB_COLS)} FROM publications")
        if staged:
            conn.executemany(f"INSERT INTO _pubs VALUES ({', '.join('?' * len(PUB_COLS))})",
                             [list(r.values()) for r in staged.values()])
        p_stats = lto_db.merge_upsert(
            conn, "publications", ["publication_id"], "_pubs", update_cols=[],
            extra_set={c: f"COALESCE(t.{lto_db.qident(c)}, s.{lto_db.qident(c)})"
                       for c in PUB_COLS if c != "publication_id"})
        lto_db.create_temp_like(conn, "_auth",
                                f"SELECT {', '.join(AUTH_COLS)}, 0 AS _seq FROM authorship")
        if auth_rows:
            conn.executemany("INSERT INTO _auth VALUES (?,?,?,?,?,?)",
                             [[*r, i] for i, r in enumerate(auth_rows)])
        a_stats = lto_db.merge_upsert(conn, "authorship", ["person_id", "publication_id"],
                                      "_auth", order_by="_seq DESC")
        lto_db.assert_integrity(conn, ["publications", "authorship"])

    print(f"[load_lto_publications] publications merge {p_stats} (matched rows filled in only)")
    print(f"[load_lto_publications] authorship merge {a_stats}")
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
    conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
