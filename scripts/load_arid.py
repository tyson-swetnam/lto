#!/usr/bin/env python3
"""Load the ARID layer: the institute, its partner centers, projects, people.

Inputs
  data/raw/R-ARID/arid_site.json        scripts/fetch_arid_site.py output —
                                        who each page lists, as written
  data/seed/arid_partner_centers.csv    ARID itself + the UNM centers on its
                                        Resources Hub, as facility rows
  data/seed/arid_projects.csv           projects and sub-projects
  data/seed/arid_people.csv             one row per real person, with the
                                        spellings the site uses for them,
                                        and each ORCID with the basis on
                                        which it was accepted

Writes (idempotent — re-running replaces this script's own rows only)
  networks             the `arid-unm` vocab row
  facilities           ARID + partner centers (existing rows are matched,
                       never duplicated; Sevilleta LTER is matched, not made)
  facility_spheres, network_membership, provenance   for those facilities
  people               reused when already linked to ARID, else minted
  facility_personnel   leadership team + staff, on the ARID facility
  projects, project_personnel, project_facilities

Run from the repo root, then set states and re-export::

    python scripts/fetch_arid_site.py
    python scripts/load_arid.py
    python scripts/backfill_facility_state.py
    python scripts/qa.py && python scripts/export_parquet.py \\
        && python scripts/export_view_caches.py

The whole load is one DuckLake snapshot (scripts/lto_db.py), checked by
lto_db.assert_integrity before it commits.

A name on the site that arid_people.csv does not list (as a name or an
alias) stops the load. That is deliberate: it is how a new person, or a
new misspelling of an old one, gets a human decision instead of a
silently minted duplicate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_people_research import canonical_person_id  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "data" / "raw" / "R-ARID" / "arid_site.json"
SEED = ROOT / "data" / "seed"
CENTERS_CSV = SEED / "arid_partner_centers.csv"
PROJECTS_CSV = SEED / "arid_projects.csv"
PEOPLE_CSV = SEED / "arid_people.csv"
NETWORKS_CSV = ROOT / "schema" / "vocab" / "networks.csv"
TYPES_CSV = ROOT / "schema" / "vocab" / "facility_types.csv"

AGENT = "R-ARID"
NETWORK = "arid-unm"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def num(s: str):
    return float(s) if s else None


def split_name(full: str) -> tuple[str, str]:
    parts = full.split()
    return (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", full)


# ── vocab ────────────────────────────────────────────────────────────────
def sync_vocab(conn) -> None:
    """The DB is rebuilt from parquet, which predates these vocab rows."""
    for row in read_csv(NETWORKS_CSV):
        if row["slug"] == NETWORK:
            lto_db.merge_upsert(
                conn, "networks", ["network_id"],
                "SELECT ? AS network_id, ? AS label, ? AS level, ? AS url",
                params=[row["slug"], row["label"], row["level"], row["url"]],
                insert_only=True,
            )
    for row in read_csv(TYPES_CSV):
        if row["slug"] == "university-institute":
            conn.execute(
                "UPDATE facility_types SET description = ? WHERE slug = ?",
                [row["description"], row["slug"]],
            )


# ── facilities ───────────────────────────────────────────────────────────
def find_facility(conn, name: str, acronym: str) -> str | None:
    row = conn.execute(
        "SELECT facility_id FROM facilities WHERE "
        "(? <> '' AND acronym IS NOT NULL AND upper(acronym) = upper(?)) "
        "OR lower(canonical_name) = lower(?) LIMIT 1",
        [acronym, acronym, name],
    ).fetchone()
    return row[0] if row else None


def load_centers(conn) -> dict[str, str]:
    """Returns seed key → facility_id."""
    ids: dict[str, str] = {}
    made = matched = 0
    for c in read_csv(CENTERS_CSV):
        fid = find_facility(conn, c["canonical_name"], c["acronym"])
        ours = fid is not None and conn.execute(
            "SELECT 1 FROM provenance WHERE record_type='facility' AND record_id=? AND agent=?",
            [fid, AGENT],
        ).fetchone() is not None

        if fid is None:
            if not c["facility_type"]:
                raise SystemExit(
                    f"[error] '{c['canonical_name']}' is marked as an existing facility "
                    "(no facility_type in the seed) but was not found")
            fid = sha16(c["canonical_name"].lower() + "|" + c["acronym"].lower())
            conn.execute(
                """INSERT INTO facilities
                   (facility_id, canonical_name, acronym, parent_org, facility_type,
                    country, region, hq_address, hq_lat, hq_lng, url, established)
                   VALUES (?,?,?,?,?, 'US', 'Southwest', ?,?,?,?,?)""",
                [fid, c["canonical_name"], c["acronym"] or None, c["parent_org"] or None,
                 c["facility_type"], c["hq_address"] or None, num(c["hq_lat"]),
                 num(c["hq_lng"]), c["url"] or None,
                 int(c["established"]) if c["established"] else None],
            )
            ours = True
            made += 1
        elif ours:
            # One of this script's own rows from an earlier run: refresh it.
            # The lake has no foreign-key block, so facility_type is
            # refreshed too (a seed row without one keeps the lake's).
            conn.execute(
                """UPDATE facilities SET parent_org=?, facility_type=COALESCE(?, facility_type),
                          hq_address=?, hq_lat=?, hq_lng=?, url=?, established=?
                   WHERE facility_id=?""",
                [c["parent_org"] or None, c["facility_type"] or None, c["hq_address"] or None,
                 num(c["hq_lat"]), num(c["hq_lng"]), c["url"] or None,
                 int(c["established"]) if c["established"] else None, fid],
            )
        else:
            matched += 1          # someone else's facility (Sevilleta LTER): leave it alone

        if ours:
            conn.execute("DELETE FROM facility_spheres WHERE facility_id = ?", [fid])
            if c["primary_sphere"]:
                conn.execute("INSERT INTO facility_spheres VALUES (?, ?, 'primary')",
                             [fid, c["primary_sphere"]])
            for s in filter(None, c["secondary_spheres"].split("|")):
                conn.execute("INSERT INTO facility_spheres VALUES (?, ?, 'secondary')", [fid, s])
            conn.execute(
                "DELETE FROM provenance WHERE record_type='facility' AND record_id=? AND agent=?",
                [fid, AGENT])
            conn.execute(
                "INSERT INTO provenance VALUES ('facility', ?, ?, ?, ?, ?)",
                [fid, c["source_url"], c["retrieved_at"], c["confidence"], AGENT])

        lto_db.merge_upsert(
            conn, "network_membership", ["facility_id", "network_id"],
            "SELECT ? AS facility_id, ? AS network_id, ? AS role",
            params=[fid, NETWORK, "host" if c["relation"] == "self" else c["relation"]],
        )
        ids[c["key"]] = fid
    print(f"[facilities] {made} created, {matched} matched to existing rows, "
          f"{len(ids)} in the {NETWORK} network")
    return ids


# ── people ───────────────────────────────────────────────────────────────
def load_people(conn, site: dict, arid_fid: str) -> dict[str, str]:
    """Returns name-as-written (lower-cased) → person_id, aliases included."""
    seed = read_csv(PEOPLE_CSV)

    # Facts about a person that only the scrape knows.
    extra: dict[str, dict] = {}
    alias_of: dict[str, str] = {}
    for p in seed:
        alias_of[p["name"].lower()] = p["name"]
        for a in filter(None, p["aliases"].split("|")):
            alias_of[a.lower()] = p["name"]
    for section in ("for_nm", "leadership"):         # leadership wins: applied last
        for p in site[section]["people"]:
            canon = alias_of.get(p["name_as_written"].lower())
            if canon:
                e = extra.setdefault(canon, {})
                if p.get("url"):
                    e["homepage_url"] = p["url"]
                if p.get("photo_url"):
                    e["photo_url"] = p["photo_url"]

    # The seed is staged and written with one MERGE. A seed row is matched
    # against the lake and against the rows staged before it, as the old
    # per-row upsert saw them.
    by_orcid: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for pid, orcid, lname in conn.execute(
            "SELECT person_id, orcid, lower(name) FROM people").fetchall():
        if orcid:
            by_orcid.setdefault(orcid, pid)
        by_name.setdefault(lname, pid)
    staged: dict[str, list] = {}
    lookup: dict[str, str] = {}
    made = 0
    for p in seed:
        name = p["name"]
        pid = (by_orcid.get(p["orcid"]) if p["orcid"] else None) or by_name.get(name.lower())
        if pid is None:
            # Name only, so the id survives an ORCID being added to the seed
            # later; an id dedupe_people.py merged away means the kept person.
            pid = canonical_person_id(sha16(f"{name.lower()}||"))
            made += 1
        given, family = split_name(name)
        e = extra.get(name, {})
        # The seed's homepage is a fallback for people the ARID site names
        # without linking anywhere.
        homepage = e.get("homepage_url") or p.get("homepage_url") or None
        row = [pid, name, family, given, p["orcid"] or None, p["openalex_id"] or None,
               p["google_scholar_id"] or None, homepage, e.get("photo_url"),
               p["notes"] or None]
        if pid in staged:
            # Two seed rows for one person: later non-NULL values win for
            # the COALESCE'd columns; name and name parts stay the first.
            staged[pid][4:] = [new if new is not None else old
                               for new, old in zip(row[4:], staged[pid][4:])]
        else:
            staged[pid] = row
        if p["orcid"]:
            by_orcid.setdefault(p["orcid"], pid)
        by_name.setdefault(name.lower(), pid)
        lookup[name.lower()] = pid
        for a in filter(None, p["aliases"].split("|")):
            lookup[a.lower()] = pid

    conn.execute(
        """CREATE OR REPLACE TEMP TABLE _arid_people (
               person_id VARCHAR, name VARCHAR, name_family VARCHAR, name_given VARCHAR,
               orcid VARCHAR, openalex_id VARCHAR, google_scholar_id VARCHAR,
               homepage_url VARCHAR, photo_url VARCHAR, notes VARCHAR)""")
    conn.executemany("INSERT INTO _arid_people VALUES (?,?,?,?,?,?,?,?,?,?)",
                     list(staged.values()))
    # An existing person keeps name, name parts and status; the identifiers
    # and photo are only ever filled in from the seed, never blanked.
    # homepage_url and notes are fill-only: once the lake has a value (a
    # research batch may have corrected a homepage with its check date, or
    # appended its findings to notes) the seed never overwrites it, so the
    # weekly refresh cannot revert that work. updated_at moves only when one
    # of those values actually changes, so a re-run on unchanged inputs
    # writes no timestamp-only diff.
    seed_wins = ["orcid", "openalex_id", "google_scholar_id", "photo_url"]
    lake_wins = ["homepage_url", "notes"]
    changed = " OR ".join([f"COALESCE(s.{c}, t.{c}) IS DISTINCT FROM t.{c}" for c in seed_wins]
                          + [f"COALESCE(t.{c}, s.{c}) IS DISTINCT FROM t.{c}" for c in lake_wins])
    lto_db.merge_upsert(
        conn, "people", ["person_id"],
        f"SELECT s.*, 'active' AS status, "
        f"CASE WHEN t.person_id IS NULL OR {changed} THEN now() ELSE t.updated_at END "
        f"AS updated_at FROM _arid_people s LEFT JOIN people t USING (person_id)",
        update_cols=seed_wins + lake_wins + ["updated_at"],
        coalesce=seed_wins,
        fill=lake_wins,
    )

    # Leadership team and staff attach to the ARID facility itself.
    retrieved = site["retrieved_at"]
    roles: list[list] = []

    def role_row(written: str, role: str, title: str | None, key: bool, url: str) -> None:
        roles.append([resolve(lookup, written), arid_fid, role, title or None, key,
                      AGENT, url, retrieved, len(roles)])

    for p in site["leadership"]["people"]:
        role_row(p["name_as_written"], "leadership-team", p["title"], False,
                 site["leadership"]["source_url"])
    for p in site["staff"]["people"]:
        title = (p["title"] or "").lower()
        role = ("director" if title == "director"
                else "manager" if "director" in title or "manager" in title
                else "staff")
        role_row(p["name_as_written"], role, p["title"], role != "staff",
                 site["staff"]["source_url"])

    # Last row per (person, facility, role) wins. The merge sets only the
    # columns the site states; start_date, end_date, notes, is_current and
    # evidence keep whatever another source wrote (DuckDB's INSERT OR
    # REPLACE also kept columns it was not given). Only this loader's own
    # rows that the site no longer lists are deleted, so a row another
    # source annotated is not dropped and re-created on the next run.
    conn.execute(
        """CREATE OR REPLACE TEMP TABLE _arid_roles (
               person_id VARCHAR, facility_id VARCHAR, role VARCHAR, title VARCHAR,
               is_key_personnel BOOLEAN, source VARCHAR, source_url VARCHAR,
               retrieved_at DATE, _seq INTEGER)""")
    if roles:
        conn.executemany("INSERT INTO _arid_roles VALUES (?,?,?,?,?,?,?,?,?)", roles)
    conn.execute(
        """DELETE FROM facility_personnel fp
           WHERE fp.facility_id = ? AND fp.source = ?
             AND NOT EXISTS (SELECT 1 FROM _arid_roles r
                             WHERE r.person_id = fp.person_id
                               AND r.facility_id = fp.facility_id AND r.role = fp.role)""",
        [arid_fid, AGENT])
    lto_db.merge_upsert(
        conn, "facility_personnel", ["person_id", "facility_id", "role"],
        "SELECT *, 'high' AS confidence FROM _arid_roles WHERE person_id <> ''",
        order_by="_seq DESC",
    )

    print(f"[people] {len(seed)} in the seed, {made} new; "
          f"{len(site['leadership']['people'])} leadership + "
          f"{len(site['staff']['people'])} staff rows on ARID")
    return lookup


_unknown: list[str] = []


def resolve(lookup: dict[str, str], written: str) -> str:
    pid = lookup.get(written.lower())
    if pid is None:
        _unknown.append(written)
        return ""
    return pid


# ── projects ─────────────────────────────────────────────────────────────
def team_rows(site: dict, key: str) -> list[tuple[str, str, str | None, str]]:
    """(name as written, role, title, source_url) for one team_sources key."""
    kind, _, arg = key.partition(":")
    if kind == "for_nm":
        out = []
        for p in site["for_nm"]["people"]:
            text = p["role_text"]
            low = text.lower()
            role = ("lead-PI" if low.startswith("head principal investigator")
                    else "co-PI" if low.startswith("co-pi")
                    else "manager" if "program manager" in low
                    else "team")
            title = "; ".join(x for x in (text, p["affiliation"]) if x)
            out.append((p["name_as_written"], role, title, site["for_nm"]["source_url"]))
        return out
    if kind == "changes":
        for sp in site["changes"]["sub_projects"]:
            if sp["title"] == arg:
                url = site["changes"]["source_url"]
                return ([(n, "leader", None, url) for n in sp["leaders"]]
                        + [(n, "co-leader", None, url) for n in sp["co_leaders"]])
        raise SystemExit(f"[error] no CHANGES sub-project titled '{arg}' in {SITE.name}")
    if kind == "cec_team":
        url = site["changes_cec_team"]["source_url"]
        return [(p["name_as_written"], "leader" if p["role_text"] else "team",
                 p["role_text"], url) for p in site["changes_cec_team"]["people"]]
    if kind == "pi":
        for pl in site["pi_lines"]:
            if pl["title"] == arg:
                return [(n, "PI", None, pl["source_url"]) for n in pl["pis"]]
        raise SystemExit(f"[error] no project page titled '{arg}' in {SITE.name}")
    raise SystemExit(f"[error] unknown team_sources key '{key}' in {PROJECTS_CSV.name}")


def load_projects(conn, site: dict, fac: dict[str, str], lookup: dict[str, str]) -> None:
    arid_fid = fac["arid"]
    old = [r[0] for r in conn.execute(
        "SELECT project_id FROM projects WHERE lead_facility_id = ?", [arid_fid]).fetchall()]
    # The rows are rebuilt from the seed, but a project keeps the created_at
    # it was first written with (a re-run must not restamp it).
    created = dict(conn.execute(
        "SELECT project_id, created_at FROM projects WHERE project_id IN (SELECT unnest(?))",
        [old]).fetchall())
    for table in ("project_personnel", "project_facilities", "projects"):
        conn.execute(f"DELETE FROM {table} WHERE project_id IN (SELECT unnest(?))", [old])

    n_people = n_links = 0
    team: dict[tuple, dict] = {}
    links: dict[tuple, str] = {}
    seed = read_csv(PROJECTS_CSV)
    known = {p["project_id"] for p in seed}
    for p in seed:
        if p["parent_project_id"] and p["parent_project_id"] not in known:
            raise SystemExit(f"[error] {p['project_id']}: unknown parent {p['parent_project_id']}")
        conn.execute(
            """INSERT INTO projects
               (project_id, name, acronym, parent_project_id, lead_facility_id,
                description, url, external_url, funding_text, extent_label,
                lat, lng, location_precision, source_url, retrieved_at, confidence, notes,
                created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, COALESCE(?, now()))""",
            [p["project_id"], p["name"], p["acronym"] or None, p["parent_project_id"] or None,
             arid_fid, p["description"] or None, p["url"] or None, p["external_url"] or None,
             p["funding_text"] or None, p["extent_label"] or None, num(p["lat"]), num(p["lng"]),
             p["location_precision"] or None, p["source_url"], p["retrieved_at"] or None,
             p["confidence"] or None, p["notes"] or None, created.get(p["project_id"])],
        )
        for key in filter(None, p["team_sources"].split("|")):
            for written, role, title, url in team_rows(site, key):
                pid = resolve(lookup, written)
                if not pid:
                    continue
                # A person can appear under two keys for one project (the
                # CEC lead is on both the index and the team page). Keep the
                # row that carries a title.
                k = (p["project_id"], pid, role)
                if k not in team or title is not None:
                    team[k] = {"title": title, "source_url": url}
                n_people += 1
        for link in filter(None, p["facility_links"].split("|")):
            key, _, relation = link.partition(":")
            if key not in fac:
                raise SystemExit(f"[error] {p['project_id']}: unknown facility key '{key}'")
            links[(p["project_id"], fac[key], relation or "partner")] = p["source_url"]
            n_links += 1
    if team:
        conn.executemany(
            """INSERT INTO project_personnel
               (project_id, person_id, role, title, source_url, retrieved_at, confidence)
               VALUES (?,?,?,?,?,?, 'high')""",
            [[*k, v["title"], v["source_url"], site["retrieved_at"]] for k, v in team.items()],
        )
    if links:
        # The projects' old rows were deleted above, so these are plain
        # inserts; a repeated (project, facility, relation) keeps its last
        # source_url, as INSERT OR REPLACE did.
        conn.executemany("INSERT INTO project_facilities VALUES (?,?,?,?,NULL)",
                         [[*k, url] for k, url in links.items()])
    n_pp = conn.execute(
        "SELECT COUNT(*) FROM project_personnel WHERE project_id IN (SELECT unnest(?))",
        [sorted(known)]).fetchone()[0]
    print(f"[projects] {len(seed)} projects, {n_pp} team rows, {n_links} facility links")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path, help="deprecated alias of --catalog")
    args = ap.parse_args()

    if not SITE.exists():
        print(f"[error] {SITE.relative_to(ROOT)} not found — run scripts/fetch_arid_site.py",
              file=sys.stderr)
        return 2
    site = json.loads(SITE.read_text())

    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    try:
        with lto_db.transaction(conn, f"load_arid: ARID layer from {SITE.name} "
                                      f"(retrieved {site['retrieved_at']}) + data/seed/arid_*.csv"):
            sync_vocab(conn)
            fac = load_centers(conn)
            lookup = load_people(conn, site, fac["arid"])
            load_projects(conn, site, fac, lookup)
            if _unknown:
                names = sorted(set(_unknown))
                raise SystemExit(
                    "[error] names on arid.unm.edu that data/seed/arid_people.csv does not "
                    f"list: {names}\n        Add each as a new row or as an alias of an "
                    "existing one, then re-run. Nothing was written.")
            lto_db.assert_integrity(conn, [
                "networks", "facility_types", "facilities", "facility_spheres",
                "network_membership", "provenance", "people", "facility_personnel",
                "projects", "project_personnel", "project_facilities",
            ])
    finally:
        conn.close()
    print(f"[done] ARID layer loaded into {lto_db.catalog_path(args.catalog)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
