#!/usr/bin/env python3
"""Merge `people` rows that are the same human — on evidence, never on a name.

Two rows are merged only when one of these holds:

  orcid               both carry the same ORCID iD
  verified-orcid      a verified research file (data/raw/R-PEOPLE2*/) gives
                      one row an ORCID that the other already carries (the
                      loader refuses to write a second copy and says
                      "merge the two")
  name+openalex       same normalised full name and the same OpenAlex id
  name+homepage       same normalised full name and the same homepage_url
  name+bio_source     same normalised full name and the same bio_source_url
  name+role+page      same normalised full name and an affiliation with the
                      same role cited to the same source page
  name+same-page      same normalised full name, and one row's profile page
                      (homepage_url or bio_source_url) is a page the other
                      row cites (as its own profile or for an affiliation)
  curated             a reviewed pair in data/seed/people_merge_seed.csv
                      (person_id_a, person_id_b, evidence): spellings of one
                      name at the same facility and role ('Ken Dunton' /
                      'Kenneth H. Dunton'), or a fetched ORCID / OpenAlex
                      record tying the two rows together. The evidence
                      column says which; a pair whose ids no longer both
                      exist is skipped.

The normalised name is load_people_research.norm_name (case, accents and
punctuation folded); "Daniel Doak" and "Daniel F. Doak" are different names
here. A name alone never merges: there are real namesakes (several "Kim
Miller"s, "Erik Smith"s, "Bob Miller"s in the catalogue). Groups are closed
transitively, and a group whose rows carry two different ORCIDs (or two
different OpenAlex ids) is not merged — it is reported for a human.

For each group the kept row is the one with an ORCID, then an OpenAlex id,
then the most authorship rows, then the most affiliations, then the most
filled fields (ties: lowest person_id). Empty fields on it are filled from
the merged rows (bio with its source and date, research_interests with its
source, ORCID with its source, homepage with its check date; a sourced
value is preferred over an unsourced one from another merged row), and a
bio, research_interests or ORCID the kept row holds without a source URL is
replaced by a merged row's sourced one (load_people_research's rule). The
kept row's updated_at becomes the newest updated_at of the merged rows (not
the wall clock), so a replay from older parquet is byte-identical. Every row that
names a merged person is repointed — facility_personnel, authorship,
person_areas, project_personnel, collaborations (both ends) and
person_registry.person_id; where the kept person already has the same key
the merged row is dropped (the kept row wins) — except in
facility_personnel, where the better-attested of the two rows survives
(is_current true over unknown over false, then evidence, then the later
retrieved_at), so a duplicate's stale copy of a role never replaces the
current one. A collaboration that
would become a self-pair is dropped. Then the merged person rows are
deleted. Each merge is appended to data/seed/people_merge_log.csv
(kept_id, merged_id, evidence).

One lake transaction (one snapshot), checked with lto_db.assert_integrity
before commit. Derived tables keyed on person_id (person_primary_groups,
person_area_metrics, mvg_node_layout) are not edited: re-run
compute_collaborations -> compute_person_areas -> compute_primary_groups ->
compute_area_metrics -> build_mvg_layout afterwards.

Idempotent: a re-run finds nothing to merge.

Usage::

    python scripts/dedupe_people.py --dry-run     # list groups + evidence, no writes
    python scripts/dedupe_people.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_people_research import norm_name, norm_orcid, stable_person_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MERGE_LOG = ROOT / "data" / "seed" / "people_merge_log.csv"
MERGE_SEED = ROOT / "data" / "seed" / "people_merge_seed.csv"
RESEARCH_GLOBS = ("R-PEOPLE2/*.json", "R-PEOPLE2-BIO/*.json")

# Child tables keyed on person_id, with the rest of each one's primary key
# (from schema.sql): a duplicate's row whose other key columns the canonical
# person already has is dropped, the rest are repointed.
CHILD_KEYS = {
    "facility_personnel": ["facility_id", "role"],
    "authorship": ["publication_id"],
    "person_areas": ["area_id"],
    "project_personnel": ["project_id", "role"],
}

# Filled on the kept row from a merged row when empty there. Each tuple
# moves together, so a bio never arrives without its source.
FILL_GROUPS = [
    ("orcid", "orcid_source_url"),
    ("openalex_id",), ("google_scholar_id",), ("scopus_author_id",),
    ("wos_researcher_id",), ("email",), ("photo_url",), ("status",),
    ("name_given",), ("name_family",),
    ("homepage_url", "homepage_checked_at"),
    ("bio", "bio_source_url", "bio_retrieved_at"),
    ("research_interests", "research_interests_source_url"),
]


def norm_url(u: str | None) -> str | None:
    if not u or not u.strip():
        return None
    u = re.sub(r"^https?://(www\.)?", "", u.strip().lower())
    return u.rstrip("/") or None


# facility_personnel row quality, best first: is_current true > NULL > false,
# then backed by evidence, then retrieved later.
_FP_RANK = ("[CASE WHEN {t}.is_current THEN 2 WHEN {t}.is_current IS NULL THEN 1 ELSE 0 END, "
            "CASE WHEN {t}.evidence IS NOT NULL THEN 1 ELSE 0 END, "
            "COALESCE(year({t}.retrieved_at) * 10000 + month({t}.retrieved_at) * 100 "
            "+ day({t}.retrieved_at), 0)]")


def repoint(conn, keep: str, drop: str) -> None:
    """Move everything that names `drop` onto `keep` (see module docstring)."""
    # Where both hold the same role at the same facility and the duplicate's
    # row is the better-attested one, the kept person's row gives way.
    conn.execute(
        f"DELETE FROM facility_personnel k WHERE k.person_id = ? AND EXISTS ("
        f"SELECT 1 FROM facility_personnel d WHERE d.person_id = ? "
        f"AND d.facility_id = k.facility_id AND d.role = k.role "
        f"AND {_FP_RANK.format(t='d')} > {_FP_RANK.format(t='k')})", [keep, drop])
    for table, rest in CHILD_KEYS.items():
        same = " AND ".join(f"k.{c} = d.{c}" for c in rest)
        conn.execute(
            f"DELETE FROM {table} d WHERE d.person_id = ? AND EXISTS "
            f"(SELECT 1 FROM {table} k WHERE k.person_id = ? AND {same})",
            [drop, keep])
        conn.execute(f"UPDATE {table} SET person_id = ? WHERE person_id = ?", [keep, drop])
    # collaborations are stored once per pair with person_a_id < person_b_id.
    conn.execute("""
        CREATE OR REPLACE TEMP TABLE _collab AS
        SELECT least(a, b) AS a, greatest(a, b) AS b, * EXCLUDE (a, b, person_a_id, person_b_id)
        FROM (SELECT CASE WHEN person_a_id = $drop THEN $keep ELSE person_a_id END AS a,
                     CASE WHEN person_b_id = $drop THEN $keep ELSE person_b_id END AS b, *
              FROM collaborations WHERE $drop IN (person_a_id, person_b_id))
        WHERE a <> b""", {"keep": keep, "drop": drop})
    conn.execute("DELETE FROM collaborations WHERE ? IN (person_a_id, person_b_id)", [drop])
    conn.execute("""
        INSERT INTO collaborations BY NAME
        SELECT DISTINCT ON (a, b) a AS person_a_id, b AS person_b_id, * EXCLUDE (a, b)
        FROM _collab c
        WHERE NOT EXISTS (SELECT 1 FROM collaborations k
                          WHERE k.person_a_id = c.a AND k.person_b_id = c.b)
        ORDER BY a, b""")
    conn.execute("UPDATE person_registry SET person_id = ? WHERE person_id = ?", [keep, drop])


def verified_orcid_claims(conn, people: dict) -> list[tuple[str, str, str]]:
    """(person_id, orcid, file) for every ORCID a verified research file
    assigns to a person already in the lake."""
    out = []
    for g in RESEARCH_GLOBS:
        for path in sorted((ROOT / "data" / "raw").glob(g)):
            try:
                doc = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            for rec in (doc.get("updates") or []) + (doc.get("people") or []):
                orcid = norm_orcid(rec.get("orcid"))
                if not orcid:
                    continue
                pid = rec.get("person_id") or rec.get("existing_person_id")
                if not pid:
                    # A research person minted by the loader under the
                    # name-only id; only trust it when that row's name is
                    # this record's name.
                    cand = stable_person_id(rec.get("name") or "")
                    if cand in people and norm_name(people[cand]["name"]) == norm_name(rec.get("name")):
                        pid = cand
                if pid in people:
                    out.append((pid, orcid, path.name))
    return out


class UF:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def find_groups(conn) -> tuple[list[dict], list[str]]:
    cols = [r[0] for r in lto_db.rows(
        conn, "SELECT column_name FROM duckdb_columns() WHERE database_name = ? "
              "AND table_name = 'people' ORDER BY column_index", [lto_db.LAKE])]
    people = {r[0]: dict(zip(cols, r)) for r in lto_db.rows(
        conn, f"SELECT {', '.join(cols)} FROM people ORDER BY person_id")}
    n_auth = dict(lto_db.rows(conn, "SELECT person_id, count(*) FROM authorship GROUP BY 1"))
    n_aff = dict(lto_db.rows(conn, "SELECT person_id, count(*) FROM facility_personnel GROUP BY 1"))
    pages = defaultdict(set)
    for pid, role, url in lto_db.rows(
            conn, "SELECT person_id, role, source_url FROM facility_personnel "
                  "WHERE source_url IS NOT NULL"):
        if norm_url(url):
            pages[pid].add((role, norm_url(url)))

    edges: list[tuple[str, str, str]] = []
    by = defaultdict(list)
    for pid, p in people.items():
        o = norm_orcid(p.get("orcid"))
        if o:
            by[("orcid", o)].append(pid)
        nn = norm_name(p["name"])
        if not nn:
            continue
        if p.get("openalex_id"):
            by[("name+openalex", nn, p["openalex_id"].upper())].append(pid)
        if norm_url(p.get("homepage_url")):
            by[("name+homepage", nn, norm_url(p["homepage_url"]))].append(pid)
        if norm_url(p.get("bio_source_url")):
            by[("name+bio_source", nn, norm_url(p["bio_source_url"]))].append(pid)
        for role, url in pages[pid]:
            by[("name+role+page", nn, role, url)].append(pid)
        # One row's profile page (homepage / bio source) is the page the
        # other cites for an affiliation, or for its own profile.
        own = {norm_url(p.get("homepage_url")), norm_url(p.get("bio_source_url"))} - {None}
        for url in own | {u for _r, u in pages[pid]}:
            by[("page", nn, url)].append(pid)
    profile = {pid: {norm_url(p.get("homepage_url")), norm_url(p.get("bio_source_url"))} - {None}
               for pid, p in people.items()}
    for key, pids in by.items():
        pids = sorted(set(pids))
        if key[0] == "page":
            # Only when the page is somebody's own profile page; two
            # affiliations citing one page are name+role+page's business.
            if not any(key[2] in profile[x] for x in pids):
                continue
            label = f"name+same-page: {key[1]} | {key[2]}"
        else:
            label = f"{key[0]}: {' | '.join(key[1:])}"
        for other in pids[1:]:
            edges.append((pids[0], other, label))
    if MERGE_SEED.exists():
        with MERGE_SEED.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                a, b = (r.get("person_id_a") or "").strip(), (r.get("person_id_b") or "").strip()
                if a in people and b in people and a != b:
                    edges.append((min(a, b), max(a, b), f"curated: {r['evidence'].strip()}"))
    holder = defaultdict(set)
    for pid, p in people.items():
        o = norm_orcid(p.get("orcid"))
        if o:
            holder[o].add(pid)
    for pid, orcid, fname in verified_orcid_claims(conn, people):
        for other in sorted(holder.get(orcid, ())):
            if other != pid:
                edges.append((min(pid, other), max(pid, other),
                              f"verified-orcid: {fname} gives {people[pid]['name']!r} ORCID "
                              f"{orcid}, carried by {people[other]['name']!r}"))

    uf = UF()
    evidence = defaultdict(list)
    for a, b, ev in edges:
        uf.union(a, b)
        evidence[frozenset((a, b))].append(ev)
    members = defaultdict(list)
    for pid in {x for e in edges for x in e[:2]}:
        members[uf.find(pid)].append(pid)

    groups, refused = [], []
    for root, pids in sorted(members.items()):
        pids = sorted(pids)
        orcids = {norm_orcid(people[p].get("orcid")) for p in pids} - {None}
        oas = {(people[p].get("openalex_id") or "").upper() for p in pids} - {""}
        names = ", ".join(f"{people[p]['name']} ({p})" for p in pids)
        if len(orcids) > 1 or len(oas) > 1:
            refused.append(f"{names}: {len(orcids)} ORCIDs {sorted(orcids)}, "
                           f"{len(oas)} OpenAlex ids {sorted(oas)} — not merged")
            continue

        def rank(p):
            r = people[p]
            filled = sum(1 for c, v in r.items() if v not in (None, "") and c not in
                         ("person_id", "created_at", "updated_at"))
            return (bool(r.get("orcid")), bool(r.get("openalex_id")), n_auth.get(p, 0),
                    n_aff.get(p, 0), filled, [-ord(c) for c in p])
        keep = max(pids, key=rank)
        drops = sorted((p for p in pids if p != keep), key=rank, reverse=True)
        ev = {d: sorted({e for k, es in evidence.items() if d in k for e in es}) for d in drops}
        groups.append({"keep": keep, "drops": drops, "evidence": ev,
                       "rows": {p: people[p] for p in pids}})
    return groups, refused


def merge(conn, g: dict) -> None:
    keep, rows = g["keep"], g["rows"]
    k = rows[keep]
    sets: dict[str, object] = {}
    def has(r, c):
        return r.get(c) not in (None, "")

    for cols in FILL_GROUPS:
        # A group with a source column (bio, research_interests, ORCID): a
        # merged row's sourced value replaces the kept row's unsourced one,
        # the same rule load_people_research applies, so a re-load of the
        # research file is a no-op after the merge.
        src = cols[1] if len(cols) > 1 and cols[1].endswith("_source_url") else None
        if has(k, cols[0]) and not (src and not has(k, src)):
            continue
        cands = [d for d in g["drops"] if has(rows[d], cols[0])]
        sourced = [d for d in cands if src and has(rows[d], src)]
        # Kept row unsourced: only a sourced value replaces it. Kept row
        # empty: the first sourced value, else the first value at all.
        pick = sourced if has(k, cols[0]) else (sourced or cands)
        if pick:
            sets.update({c: rows[pick[0]].get(c) for c in cols})
    note = " ".join(f"[dedupe] merged {rows[d]['name']} ({d}): {'; '.join(g['evidence'][d])}."
                    for d in g["drops"])
    other_notes = " ".join(rows[d]["notes"] for d in g["drops"] if rows[d].get("notes"))
    sets["notes"] = " ".join(x for x in (k.get("notes"), other_notes, note) if x)
    # updated_at: the newest of the merged rows' own stamps, not the wall
    # clock, so replaying a merge from older parquet reproduces the row
    # byte for byte (the merge itself is dated in people_merge_log.csv's
    # evidence and the notes).
    stamps = [r.get("updated_at") for r in rows.values() if r.get("updated_at") is not None]
    for d in g["drops"]:
        repoint(conn, keep, d)
        conn.execute("DELETE FROM people WHERE person_id = ?", [d])
    conn.execute(f"UPDATE people SET {', '.join(f'{c} = ?' for c in sets)}, "
                 f"updated_at = COALESCE(CAST(? AS TIMESTAMP), CAST(now() AS TIMESTAMP)) "
                 f"WHERE person_id = ?", [*sets.values(), max(stamps) if stamps else None, keep])


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
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", type=Path, default=None,
                    help="deprecated alias of --catalog (a db/lto.duckdb path is ignored)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", type=Path, default=MERGE_LOG,
                    help=f"merge log to append to (default {MERGE_LOG.relative_to(ROOT)})")
    args = ap.parse_args()

    conn = lto_db.connect(read_only=args.dry_run, catalog=catalog_arg(args),
                          data=args.lake_data)
    groups, refused = find_groups(conn)
    for g in groups:
        k = g["rows"][g["keep"]]
        print(f"  keep {k['name']} ({g['keep']})")
        for d in g["drops"]:
            print(f"    <- {g['rows'][d]['name']} ({d}): {'; '.join(g['evidence'][d])}")
    for r in refused:
        print(f"  [refused] {r}")
    n = sum(len(g["drops"]) for g in groups)
    if args.dry_run or not groups:
        print(f"{'[dry-run] would merge' if args.dry_run else '[dedupe] nothing to merge:'} "
              f"{n} rows into {len(groups)} people; {len(refused)} group(s) refused")
        return 0

    with lto_db.transaction(conn, f"dedupe_people: {n} rows merged into {len(groups)} people "
                                  f"on ORCID / name+identifier evidence"):
        for g in groups:
            merge(conn, g)
        # project_personnel is a soft reference (no FK in schema.sql), so
        # the generic check would not see an orphan there.
        orphans = lto_db.scalar(
            conn, "SELECT count(*) FROM project_personnel "
                  "WHERE person_id NOT IN (SELECT person_id FROM people)")
        if orphans:
            raise RuntimeError(f"{orphans} project_personnel rows left on a deleted person")
        lto_db.assert_integrity(conn, ["people", *CHILD_KEYS, "collaborations", "person_registry"])

    new = not args.log.exists()
    with args.log.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        if new:
            w.writerow(["kept_id", "merged_id", "evidence"])
        for g in groups:
            for d in g["drops"]:
                w.writerow([g["keep"], d, "; ".join(g["evidence"][d])])
    print(f"[dedupe] merged {n} rows into {len(groups)} people; {len(refused)} group(s) refused; "
          f"log {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
