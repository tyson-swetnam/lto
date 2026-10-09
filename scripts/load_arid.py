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

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "lto.duckdb"
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
            conn.execute(
                "INSERT OR IGNORE INTO networks (network_id, label, level, url) VALUES (?,?,?,?)",
                [row["slug"], row["label"], row["level"], row["url"]],
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
            # facility_type is left out: it is a foreign-key column, and
            # DuckDB turns an UPDATE of one into delete + insert, which the
            # personnel rows pointing at this facility then block.
            conn.execute(
                """UPDATE facilities SET parent_org=?, hq_address=?,
                          hq_lat=?, hq_lng=?, url=?, established=?
                   WHERE facility_id=?""",
                [c["parent_org"] or None, c["hq_address"] or None,
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

        conn.execute(
            "INSERT OR REPLACE INTO network_membership (facility_id, network_id, role) VALUES (?,?,?)",
            [fid, NETWORK, "host" if c["relation"] == "self" else c["relation"]],
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

    lookup: dict[str, str] = {}
    made = 0
    for p in seed:
        name = p["name"]
        row = None
        if p["orcid"]:
            row = conn.execute("SELECT person_id FROM people WHERE orcid = ?",
                               [p["orcid"]]).fetchone()
        if row is None:
            row = conn.execute("SELECT person_id FROM people WHERE lower(name) = lower(?)",
                               [name]).fetchone()
        if row:
            pid = row[0]
        else:
            # Name only, so the id survives an ORCID being added to the seed later.
            pid = sha16(f"{name.lower()}||")
            made += 1
        given, family = split_name(name)
        e = extra.get(name, {})
        # The seed's homepage is a fallback for people the ARID site names
        # without linking anywhere.
        homepage = e.get("homepage_url") or p.get("homepage_url") or None
        conn.execute(
            """INSERT INTO people (person_id, name, name_family, name_given, orcid,
                                   openalex_id, google_scholar_id, homepage_url,
                                   photo_url, status, notes, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?, 'active', ?, now())
               ON CONFLICT (person_id) DO UPDATE SET
                   orcid             = COALESCE(excluded.orcid, people.orcid),
                   openalex_id       = COALESCE(excluded.openalex_id, people.openalex_id),
                   google_scholar_id = COALESCE(excluded.google_scholar_id, people.google_scholar_id),
                   homepage_url      = COALESCE(excluded.homepage_url, people.homepage_url),
                   photo_url         = COALESCE(excluded.photo_url, people.photo_url),
                   notes             = COALESCE(excluded.notes, people.notes),
                   updated_at        = now()""",
            [pid, name, family, given, p["orcid"] or None, p["openalex_id"] or None,
             p["google_scholar_id"] or None, homepage, e.get("photo_url"),
             p["notes"] or None],
        )
        lookup[name.lower()] = pid
        for a in filter(None, p["aliases"].split("|")):
            lookup[a.lower()] = pid

    # Leadership team and staff attach to the ARID facility itself.
    conn.execute("DELETE FROM facility_personnel WHERE facility_id = ? AND source = ?",
                 [arid_fid, AGENT])
    retrieved = site["retrieved_at"]

    def role_row(written: str, role: str, title: str | None, key: bool, url: str) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO facility_personnel
               (person_id, facility_id, role, title, is_key_personnel,
                source, source_url, retrieved_at, confidence)
               VALUES (?,?,?,?,?,?,?,?, 'high')""",
            [resolve(lookup, written), arid_fid, role, title or None, key, AGENT, url, retrieved])

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
    for table in ("project_personnel", "project_facilities", "projects"):
        conn.execute(f"DELETE FROM {table} WHERE project_id IN (SELECT unnest(?))", [old])

    n_people = n_links = 0
    seed = read_csv(PROJECTS_CSV)
    known = {p["project_id"] for p in seed}
    for p in seed:
        if p["parent_project_id"] and p["parent_project_id"] not in known:
            raise SystemExit(f"[error] {p['project_id']}: unknown parent {p['parent_project_id']}")
        conn.execute(
            """INSERT INTO projects
               (project_id, name, acronym, parent_project_id, lead_facility_id,
                description, url, external_url, funding_text, extent_label,
                lat, lng, location_precision, source_url, retrieved_at, confidence, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [p["project_id"], p["name"], p["acronym"] or None, p["parent_project_id"] or None,
             arid_fid, p["description"] or None, p["url"] or None, p["external_url"] or None,
             p["funding_text"] or None, p["extent_label"] or None, num(p["lat"]), num(p["lng"]),
             p["location_precision"] or None, p["source_url"], p["retrieved_at"] or None,
             p["confidence"] or None, p["notes"] or None],
        )
        for key in filter(None, p["team_sources"].split("|")):
            for written, role, title, url in team_rows(site, key):
                pid = resolve(lookup, written)
                if not pid:
                    continue
                # A person can appear under two keys for one project (the
                # CEC lead is on both the index and the team page). Keep the
                # row that carries a title.
                conn.execute(
                    """INSERT INTO project_personnel
                       (project_id, person_id, role, title, source_url, retrieved_at, confidence)
                       VALUES (?,?,?,?,?,?, 'high')
                       ON CONFLICT (project_id, person_id, role) DO UPDATE SET
                           title = COALESCE(excluded.title, project_personnel.title),
                           source_url = CASE WHEN excluded.title IS NOT NULL
                                             THEN excluded.source_url
                                             ELSE project_personnel.source_url END""",
                    [p["project_id"], pid, role, title, url, site["retrieved_at"]],
                )
                n_people += 1
        for link in filter(None, p["facility_links"].split("|")):
            key, _, relation = link.partition(":")
            if key not in fac:
                raise SystemExit(f"[error] {p['project_id']}: unknown facility key '{key}'")
            conn.execute(
                "INSERT OR REPLACE INTO project_facilities VALUES (?,?,?,?,NULL)",
                [p["project_id"], fac[key], relation or "partner", p["source_url"]],
            )
            n_links += 1
    n_pp = conn.execute(
        "SELECT COUNT(*) FROM project_personnel WHERE project_id IN (SELECT unnest(?))",
        [sorted(known)]).fetchone()[0]
    print(f"[projects] {len(seed)} projects, {n_pp} team rows, {n_links} facility links")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()

    if not SITE.exists():
        print(f"[error] {SITE.relative_to(ROOT)} not found — run scripts/fetch_arid_site.py",
              file=sys.stderr)
        return 2
    site = json.loads(SITE.read_text())

    conn = duckdb.connect(str(args.db))
    conn.execute("BEGIN")
    try:
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
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    print(f"[done] ARID layer loaded into {args.db.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
