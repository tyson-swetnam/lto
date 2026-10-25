"""Data-quality assertions run after ingest.

Exits non-zero on any failure so CI workflows can gate deploys.

Two checks read source files rather than the database and run even on a
checkout with no data:

  * check_frontend_parses — every src/**/*.js must parse as an ES module
    (node vm.SourceTextModule; skipped with a warning when node is absent).
  * check_view_sql_types — no SQL template literal in src/views/*.js may
    return DECIMAL/HUGEINT to the browser (duckdb-wasm hands those to JS
    as non-numbers; the silent failure mode is a blank view).

Both are ported from cod-kmap, where each exists because of a shipped
incident documented in its docstring.

The store is a DuckLake (scripts/lto_db.py), opened read-only. DuckLake
cannot hold PRIMARY KEY / UNIQUE / FOREIGN KEY / CHECK constraints, so
the first database gate, check_integrity, re-enforces every constraint
declared in schema/schema.sql (duplicate keys, orphaned references,
failed CHECKs, NULLs in NOT NULL columns) against the lake. That gate is
what used to be the database's own job; a loader that writes a duplicate
or an orphan now fails here instead of at INSERT time. The same gate
covers the derived tables' keys (lto_db.DERIVED_CONSTRAINTS), the soft
references schema.sql does not declare (lto_db.SOFT_REFERENCES) and
column drift between the lake and schema.sql.

Warnings (printed, not failures) flag known debt that needs a data change
to clear: vocabulary tables that differ from schema/vocab/*.csv. (Duplicate
ORCIDs in people were a warning until dedupe_people.py ran; they fail now.)

Usage::

    python scripts/qa.py
    python scripts/qa.py --catalog /tmp/scratch/cat.sqlite   # or $LTO_LAKE_CATALOG
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_people_research import merge_redirects, same_person_name  # noqa: E402
from apply_facility_fixes import KEYED as FIX_KEYED  # noqa: E402

# Territories that fall outside their country's main bounding box. Guam
# and the Northern Marianas sit at ~+145 EAST longitude and Palmyra at
# ~6 N, none of which a single US rectangle can express. Directly
# relevant to LTO: NEON's PUUM (Hawaii) and GUAN (Guam) domains, PacIOOS,
# and the Papahānaumokuākea sites all live in these boxes.
EXTRA_BBOXES = {
    "US": [
        (13.0, 21.0, 144.0, 146.5),      # Guam + Northern Mariana Islands
        (-15.0, 0.0, -172.0, -168.0),    # American Samoa
        (5.0, 7.0, -163.0, -161.0),      # Palmyra Atoll / Line Islands
        (18.0, 29.0, -178.5, -154.0),    # Hawaii + NW Hawaiian Islands
    ],
}

BBOX_BY_COUNTRY = {
    # (min_lat, max_lat, min_lng, max_lng) — generous continental boxes
    "US": (17.0, 72.0, -180.0, -64.0),
    "CA": (41.0, 84.0, -142.0, -52.0),
    "MX": (14.0, 33.0, -118.0, -86.0),
    "CU": (19.5, 23.5, -85.5, -74.0),
    "JM": (17.5, 18.7, -78.5, -76.0),
    "BS": (20.5, 27.5, -79.5, -72.5),
    "DO": (17.5, 20.0, -72.0, -68.0),
    "HT": (17.5, 20.0, -74.5, -71.5),
    "PR": (17.8, 18.6, -67.3, -65.2),
    "VI": (17.6, 18.5, -65.1, -64.5),
    "CO": (-4.3, 13.0, -81.8, -66.8),
    "BR": (-34.0, 5.3, -74.0, -28.6),
    "AR": (-55.2, -21.8, -73.6, -53.6),
    "CL": (-56.0, -17.5, -75.7, -66.4),
    "PE": (-18.4, -0.1, -81.4, -68.6),
    "EC": (-5.1, 1.7, -92.1, -75.2),
    "UY": (-35.0, -30.0, -58.5, -53.0),
    "VE": (0.6, 12.3, -73.4, -59.8),
    "PA": (7.2, 9.7, -83.0, -77.2),
    "CR": (8.0, 11.3, -86.0, -82.5),
    "GT": (13.7, 17.9, -92.3, -88.2),
    "BZ": (15.9, 18.5, -89.3, -87.3),
    "HN": (12.9, 16.6, -89.4, -83.1),
    "NI": (10.7, 15.1, -87.7, -82.6),
    "SV": (12.9, 14.5, -90.2, -87.6),
    "BB": (13.0, 13.4, -60.0, -59.3),
    "TT": (10.0, 11.5, -62.0, -60.4),
    "KY": (19.2, 19.9, -81.5, -79.7),
    "TC": (20.9, 22.0, -72.5, -71.0),
    # French Polynesia (Moorea Coral Reef LTER): OSM relation 3412620
    # "Polynésie Française" boundingbox -28.0990..-7.6592, -154.9361..-134.2448
    # (nominatim.openstreetmap.org/search?q=French+Polynesia, fetched 2026-10-25),
    # rounded outward.
    "PF": (-28.2, -7.5, -155.0, -134.2),
}


def assert_true(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)


# Columns each LTO table must still have. Duplicated from schema.sql on
# purpose: the point of a gate is to fail when the schema and the
# expectation drift apart, which a shared constant would hide.
EXPECTED_COLUMNS = {
    "spheres": {"slug", "label", "description"},
    "ecosystem_types": {"slug", "label", "source", "description"},
    "life_zones": {"slug", "label", "holdridge_class"},
    "facility_spheres": {"facility_id", "sphere_slug", "role"},
    "facility_ecosystems": {"facility_id", "ecosystem_slug"},
    "facility_life_zones": {"facility_id", "life_zone_slug"},
    "data_archives": {
        "archive_id", "name", "organization", "archive_type", "base_url",
        "api_url", "api_type", "license_slug",
    },
    "facility_archives": {"facility_id", "archive_id", "role", "scope_url"},
    "data_products": {
        "product_id", "archive_id", "facility_id", "title", "doi", "url",
        "format_slug", "license_slug", "source", "confidence",
        "description", "category", "api_url",
    },
    "api_endpoints": {"endpoint_id", "archive_id", "path_or_url", "method"},
    "cloud_buckets": {"bucket_id", "archive_id", "provider", "bucket_name"},
    # ARID wave.
    "projects": {
        "project_id", "name", "parent_project_id", "lead_facility_id",
        "url", "extent_label", "lat", "lng", "location_precision",
        "source_url", "retrieved_at", "confidence",
    },
    "project_personnel": {"project_id", "person_id", "role", "source_url"},
    "project_facilities": {"project_id", "facility_id", "relation"},
    # Unified person identity (KMAP alignment M3+).
    "person_registry": {
        "canonical_id", "display_name", "orcid", "openalex_id",
        "is_site_personnel", "is_scholar", "person_id", "tier", "tier_rank",
        "lto_works_count", "lto_share", "source_url", "confidence",
    },
    "person_identity_source": {
        "canonical_id", "field", "value", "method", "confidence",
    },
    "registry_collaborations": {
        "canonical_id_a", "canonical_id_b", "co_pub_count",
        "first_year", "last_year",
    },
    "registry_facilities": {
        "canonical_id", "facility_id", "method", "ror",
    },
    "person_validation": {
        "validation_id", "canonical_id", "check_id", "verdict",
        "method", "source_url", "retrieved_at", "confidence", "run_id",
    },
    "coauthor_edges": {
        "edge_id", "canonical_id_a", "canonical_id_b", "co_pub_count",
        "exemplar_work_id", "match_method", "source_url", "retrieved_at",
        "confidence", "run_id",
    },
    "coauthor_candidates": {
        "candidate_id", "display_name", "openalex_id",
        "seen_with_canonical_id", "seen_on_work_id", "n_registry_coauthors",
        "decision", "source_url", "retrieved_at", "confidence", "run_id",
    },
}


def table_rows(conn, table: str) -> int:
    """Row count, or -1 when the table isn't in this database.

    The weekly refresh workflow rebuilds a DB from ingest.py alone, where
    the layered tables are empty (their data lives in committed parquet
    that ingest never touches). Gating on this keeps that run green
    instead of failing on absent data it was never asked to produce.
    """
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except duckdb.Error:
        return -1


def check_tables_present(conn, failures: list[str]) -> None:
    """If any of the layered tables has rows, they must all exist.

    Every check below no-ops on an empty table, which means an
    accidentally *dropped* table looked exactly like an empty one and
    silenced its invariants. Once one of the group is populated we know
    this is a full database, so a missing sibling is a real fault.
    """
    counts = {t: table_rows(conn, t) for t in EXPECTED_COLUMNS}
    if not any(n > 0 for n in counts.values()):
        return
    absent = sorted(t for t, n in counts.items() if n < 0)
    assert_true(not absent,
                f"table(s) missing from a populated database: {absent}", failures)


def check_columns(conn, failures: list[str]) -> None:
    for table, expected in EXPECTED_COLUMNS.items():
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
        except duckdb.Error:
            continue          # table absent — the row-count gates report it
        if not cols:
            continue
        missing = expected - cols
        assert_true(not missing, f"{table} missing column(s): {sorted(missing)}", failures)


def check_spheres(conn, failures: list[str]) -> None:
    """Six-sphere layer invariants."""
    if table_rows(conn, "facility_spheres") <= 0:
        return
    bad_slug = conn.execute(
        """SELECT COUNT(*) FROM facility_spheres fs
           LEFT JOIN spheres s ON fs.sphere_slug = s.slug
           WHERE s.slug IS NULL"""
    ).fetchone()[0]
    assert_true(bad_slug == 0,
                f"{bad_slug} facility_spheres rows reference unknown sphere_slug", failures)

    multi_primary = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT facility_id FROM facility_spheres
             WHERE role = 'primary'
             GROUP BY facility_id HAVING COUNT(*) > 1)"""
    ).fetchone()[0]
    assert_true(multi_primary == 0,
                f"{multi_primary} facilities have more than one primary sphere", failures)

    orphan = conn.execute(
        """SELECT COUNT(*) FROM facility_spheres fs
           LEFT JOIN facilities f ON fs.facility_id = f.facility_id
           WHERE f.facility_id IS NULL"""
    ).fetchone()[0]
    assert_true(orphan == 0,
                f"{orphan} facility_spheres rows point at unknown facilities", failures)


# Committed inputs keyed on facility_id that a loader reads as live input
# (not history): a merged id left in one is resolved by
# lto_db.canonical_facility_id, but the file should say the kept id.
FACILITY_ID_INPUTS = [
    "data/funding_overrides/nsf_recipient_overrides.csv",
    "data/funding_overrides/usaspending_recipient_overrides.csv",
    "data/seed/openalex_institution_overrides.csv",
    "data/seed/facility_fixes.csv",
]


def check_facility_merges(conn, failures: list[str], warnings: list[str]) -> None:
    """A facility merge_facilities.py merged away must stay gone: a loader
    that re-creates the id (an override, seed or regenerated raw file
    written before the merge) brings the duplicate back."""
    merged = lto_db.facility_merge_redirects()
    if not merged:
        return
    back = conn.execute(
        "SELECT facility_id, canonical_name FROM facilities "
        "WHERE facility_id IN (SELECT unnest(?::VARCHAR[])) ORDER BY 1",
        [sorted(merged)]).fetchall()
    assert_true(not back, f"{len(back)} facilities rows carry an id merged away in "
                          f"data/seed/facility_merge_log.csv (a loader re-created them): "
                + "; ".join(f"{n} {fid} -> {merged[fid]}" for fid, n in back[:5]), failures)
    root = Path(__file__).resolve().parent.parent
    for rel in FACILITY_ID_INPUTS:
        path = root / rel
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if rel == "data/seed/facility_fixes.csv":
            # A keyed remove on the duplicate itself is cleanup that ran
            # before its merge (e.g. a point merge_facilities would otherwise
            # move): it can only name the duplicate, and apply_facility_fixes
            # skips it once the duplicate is gone. A facet remove (spheres,
            # networks, ...) on a merged id is still redirected to the
            # survivor, so it keeps the warning.
            with path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            lines = [",".join(r) for r in rows[1:]
                     if not (len(r) > 3 and r[3] == "remove" and r[1] in FIX_KEYED
                             and r[0] in merged)]
        hits = sorted({fid for line in lines for fid in merged if fid in line})
        if hits:
            warnings.append(f"{rel} still names {len(hits)} merged facility id(s) "
                            f"(rewrite to the kept id): "
                            + ", ".join(f"{f} -> {merged[f]}" for f in hits[:5]))


# Committed inputs that name funders by id or by name and that a writer
# reads as live input: a merged id or name left in one is resolved by
# lto_db.canonical_funder, but the file should say the survivor.
FUNDER_INPUTS = [
    "data/funding_research/agency_budgets",
    "data/funding_overrides",
]


def check_funder_merges(conn, failures: list[str], warnings: list[str]) -> None:
    """A funder merge_funders.py merged away must stay gone: a writer that
    mints its id again (ingest.py's sha1('nsf'), a raw record's 'EPA') would
    bring the duplicate back. Every id the merge log redirects (merged ids
    and both hash families' ids of each merged name, alias and kept name)
    must be absent from funders and funding_events."""
    merged, kept_names = lto_db._funder_redirect_maps()
    if not merged:
        return
    ids = sorted(merged)
    back = conn.execute(
        "SELECT funder_id, name FROM funders "
        "WHERE funder_id IN (SELECT unnest(?::VARCHAR[])) ORDER BY 1", [ids]).fetchall()
    assert_true(not back, f"{len(back)} funders rows carry an id merged away in "
                          f"data/seed/funder_merge_log.csv (a writer re-created them): "
                + "; ".join(f"{n} {fid} -> {merged[fid]}" for fid, n in back[:5]), failures)
    ev = conn.execute(
        "SELECT count(*) FROM funding_events "
        "WHERE funder_id IN (SELECT unnest(?::VARCHAR[]))", [ids]).fetchone()[0]
    assert_true(not ev, f"{ev} funding_events rows name a funder id merged away in "
                        f"data/seed/funder_merge_log.csv", failures)
    root = Path(__file__).resolve().parent.parent
    for rel in FUNDER_INPUTS:
        base = root / rel
        for path in sorted(base.glob("*.csv")) if base.is_dir() else [base]:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(root) if path.is_relative_to(root) else path
            hits = sorted({fid for line in text.splitlines()
                           for fid in merged if fid in line})
            if hits:
                warnings.append(f"{rel} still names {len(hits)} merged "
                                f"funder id(s) (rewrite to the kept id): "
                                + ", ".join(f"{f} -> {merged[f]}" for f in hits[:5]))
            # Most inputs name funders by name (agency_budgets' funder_name):
            # a merged name ('NOAA OCM', 'USGS') would load onto the survivor
            # without a trace, so name it here too.
            stale = set()
            for r in csv.DictReader(text.splitlines()):
                n = (r.get("funder_name") or "").strip()
                keep = next((merged[i] for i in lto_db.funder_name_ids(n) if i in merged), None)
                if keep and n.lower() != (kept_names.get(keep) or "").strip().lower():
                    stale.add((n, keep))
            if stale:
                warnings.append(f"{rel} names {len(stale)} merged funder "
                                f"name(s) (it loads onto the kept funder; rename it): "
                                + ", ".join(f"'{n}' -> {k} '{kept_names.get(k)}'"
                                            for n, k in sorted(stale)[:5]))


ESTUARY_NETWORKS = ("nerrs", "nep")
USASPENDING_WHITELIST = "data/funding_overrides/usaspending_award_whitelist.csv"


def check_estuary_funding(conn, failures: list[str]) -> None:
    """NERR / NEP money is fetched award by award from USAspending.gov
    (fetch_funding_usaspending.py, pinned in usaspending_award_whitelist.csv).

    * No 'training-data recall' amount may sit on a reserve or estuary
      program: the 2026-10-25 recall rows were removed in facility_fixes.csv.
    * Every USAspending row on one of them names an award the whitelist pins
      to that facility (the nep / nerrs guard: never a recipient search).
    * No facility may carry an 'agency budget research' row and a
      USAspending row for the same funder and year: agency_budgets/
      noaa_nerr.csv rolls the same 11.420 awards up, so both would count
      the money twice.
    """
    nets = list(ESTUARY_NETWORKS)
    recall = conn.execute(
        """SELECT count(*) FROM funding_events fe
           WHERE fe.source ILIKE '%training-data recall%'
             AND fe.facility_id IN (SELECT facility_id FROM network_membership
                                    WHERE network_id IN (SELECT unnest(?::VARCHAR[])))""",
        [nets]).fetchone()[0]
    assert_true(not recall, f"{recall} funding_events rows on a nerrs/nep facility cite "
                            f"'training-data recall' (fetch the awards instead: "
                            f"fetch_funding_usaspending.py --network nerrs,nep)", failures)
    path = Path(__file__).resolve().parent.parent / USASPENDING_WHITELIST
    pinned: set[tuple[str, str]] = set()
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(l for l in fh if not l.lstrip().startswith("#")):
                pinned.add((lto_db.canonical_facility_id(r["facility_id"].strip()),
                            r["award_id"].strip()))
    rows = conn.execute(
        """SELECT DISTINCT fe.facility_id, fe.award_id FROM funding_events fe
           WHERE fe.source = 'USAspending.gov'
             AND fe.facility_id IN (SELECT facility_id FROM network_membership
                                    WHERE network_id IN (SELECT unnest(?::VARCHAR[])))
           ORDER BY 1, 2""", [nets]).fetchall()
    stray = [(f, a) for f, a in rows if (f, a) not in pinned]
    assert_true(not stray, f"{len(stray)} USAspending awards on nerrs/nep facilities are not "
                           f"pinned to them in {USASPENDING_WHITELIST}: "
                + ", ".join(f"{f}:{a}" for f, a in stray[:5]), failures)
    dup = conn.execute(
        """SELECT count(*) FROM (
               SELECT facility_id, funder_id, fiscal_year FROM funding_events
               WHERE source = 'agency budget research' AND amount_usd IS NOT NULL
               INTERSECT
               SELECT facility_id, funder_id, fiscal_year FROM funding_events
               WHERE source = 'USAspending.gov')""").fetchone()[0]
    assert_true(not dup, f"{dup} facility/funder/fiscal-year cells carry both an 'agency budget "
                         f"research' row and USAspending.gov award rows (the same money "
                         f"twice)", failures)


def check_states(conn, failures: list[str]) -> None:
    """Once any facility carries a state, every locatable US one must.

    The state column is derived (scripts/backfill_facility_state.py), so a
    gap means a loader added facilities and the backfill was not re-run —
    and those facilities would silently drop out of the New Mexico and
    drylands lenses.
    """
    if conn.execute("SELECT COUNT(*) FROM facilities WHERE state IS NOT NULL").fetchone()[0] == 0:
        return
    missing = conn.execute(
        """SELECT COUNT(*) FROM facilities
           WHERE country = 'US' AND hq_lat IS NOT NULL AND hq_lng IS NOT NULL
             AND state IS NULL"""
    ).fetchone()[0]
    assert_true(missing == 0,
                f"{missing} US facilities with coordinates have no state — "
                "run scripts/backfill_facility_state.py", failures)


PROJECT_PRECISIONS = {"site", "county", "city", "statewide", "regional", "none"}


def check_projects(conn, failures: list[str]) -> None:
    """ARID wave: projects and their soft-referenced link tables."""
    if table_rows(conn, "projects") <= 0:
        return
    no_source = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE source_url IS NULL OR source_url = ''"
    ).fetchone()[0]
    assert_true(no_source == 0, f"{no_source} projects without a source_url", failures)

    bad_parent = conn.execute(
        """SELECT COUNT(*) FROM projects p
           WHERE p.parent_project_id IS NOT NULL
             AND p.parent_project_id NOT IN (SELECT project_id FROM projects)"""
    ).fetchone()[0]
    assert_true(bad_parent == 0, f"{bad_parent} projects point at an unknown parent", failures)

    bad_lead = conn.execute(
        """SELECT COUNT(*) FROM projects p
           WHERE p.lead_facility_id IS NULL
              OR p.lead_facility_id NOT IN (SELECT facility_id FROM facilities)"""
    ).fetchone()[0]
    assert_true(bad_lead == 0, f"{bad_lead} projects without a known lead facility", failures)

    precisions = {r[0] for r in conn.execute(
        "SELECT DISTINCT location_precision FROM projects").fetchall()}
    unknown = sorted(str(p) for p in precisions - PROJECT_PRECISIONS)
    assert_true(not unknown, f"projects use unknown location_precision: {unknown}", failures)

    # A point claims a place. A project the source only describes as
    # statewide or regional must not have one, and a placed project must.
    half = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE (lat IS NULL) <> (lng IS NULL)").fetchone()[0]
    assert_true(half == 0, f"{half} projects with only one of lat/lng", failures)
    misplaced = conn.execute(
        """SELECT COUNT(*) FROM projects
           WHERE (lat IS NOT NULL AND location_precision IN ('statewide','regional','none'))
              OR (lat IS NULL AND location_precision IN ('site','county','city'))"""
    ).fetchone()[0]
    assert_true(misplaced == 0,
                f"{misplaced} projects whose coordinates disagree with location_precision",
                failures)

    for table, col, parent, pcol in (
        ("project_personnel", "project_id", "projects", "project_id"),
        ("project_personnel", "person_id", "people", "person_id"),
        ("project_facilities", "project_id", "projects", "project_id"),
        ("project_facilities", "facility_id", "facilities", "facility_id"),
    ):
        if table_rows(conn, table) <= 0:
            continue
        orphan = conn.execute(
            f"SELECT COUNT(*) FROM {table} t "
            f"WHERE t.{col} NOT IN (SELECT {pcol} FROM {parent})"
        ).fetchone()[0]
        assert_true(orphan == 0,
                    f"{orphan} {table} rows point at an unknown {parent}.{pcol}", failures)

    # The leadership roster must match what the scraper last read. A gap
    # here means load_arid.py dropped someone the site lists.
    site_file = Path(__file__).resolve().parent.parent / "data" / "raw" / "R-ARID" / "arid_site.json"
    if site_file.exists():
        expected = len(json.loads(site_file.read_text())["leadership"]["people"])
        got = conn.execute(
            """SELECT COUNT(*) FROM facility_personnel fp
               JOIN facilities f USING (facility_id)
               WHERE f.acronym = 'ARID' AND fp.role = 'leadership-team'"""
        ).fetchone()[0]
        assert_true(got == expected,
                    f"ARID leadership team has {got} rows; arid_site.json lists {expected}",
                    failures)


# Archives catalogued as pointers: metadata plus links back to the source's
# own endpoints, never a copy of its data. archive_id → the prefix every
# product url and api_url must start with.
POINTER_ARCHIVES = {
    "envirodata-nm": "https://envirodata-nm.unm.edu/",
    "arizona-water-observatory": "https://arizonawaterobservatory-api.rtd.asu.edu/",
}


def check_portal_products(conn, failures: list[str]) -> None:
    """Pointer records must point somewhere, on the source's own host."""
    if table_rows(conn, "data_products") <= 0:
        return
    for archive_id, prefix in POINTER_ARCHIVES.items():
        n = conn.execute(
            "SELECT COUNT(*) FROM data_products WHERE archive_id = ?", [archive_id]
        ).fetchone()[0]
        if n == 0:
            continue
        bad = conn.execute(
            """SELECT COUNT(*) FROM data_products
               WHERE archive_id = ?
                 AND (url IS NULL OR api_url IS NULL OR category IS NULL
                      OR NOT starts_with(url, ?) OR NOT starts_with(api_url, ?))""",
            [archive_id, prefix, prefix],
        ).fetchone()[0]
        assert_true(bad == 0,
                    f"{bad} {archive_id} products lack a source url, api_url or category",
                    failures)
        dup = conn.execute(
            """SELECT COUNT(*) FROM (
                 SELECT identifier FROM data_products WHERE archive_id = ?
                 GROUP BY identifier HAVING COUNT(*) > 1)""",
            [archive_id],
        ).fetchone()[0]
        assert_true(dup == 0, f"{dup} {archive_id} identifiers are duplicated", failures)


def check_topic_crosswalk(conn, failures: list[str]) -> None:
    """The OpenAlex → research-area crosswalk must name real things.

    Its ids were once typed from memory: "Kelp" carried the id of "Global
    warming", "Ecosystem" the id of the general concept "Ecology", and
    15,000 unrelated papers were filed under marine ecosystems as a
    result. Two checks stop that recurring: every id that occurs in
    publication_topics must carry OpenAlex's own name for it, and every
    area must exist in the vocabulary.
    """
    import csv as _csv                                    # noqa: PLC0415
    import re as _re                                      # noqa: PLC0415
    root = Path(__file__).resolve().parent.parent
    path = root / "data" / "vocab_crosswalk" / "openalex_to_area.csv"
    areas_csv = root / "schema" / "vocab" / "research_areas.csv"
    if not path.exists() or not areas_csv.exists():
        return
    with areas_csv.open(newline="") as fh:
        areas = {r["slug"] for r in _csv.DictReader(fh)}
    with path.open(newline="") as fh:
        rows = [r for r in _csv.reader(fh)
                if r and not r[0].startswith("#") and r[0] != "openalex_id"]

    def norm(s: str) -> str:
        return _re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    bad_area = sorted({r[2] for r in rows if len(r) < 3 or r[2] not in areas})
    assert_true(not bad_area,
                f"topic crosswalk maps to unknown research areas: {bad_area[:8]}", failures)

    if table_rows(conn, "publication_topics") <= 0:
        return
    real = dict(conn.execute(
        "SELECT concept_id, any_value(concept_name) FROM publication_topics GROUP BY 1"
    ).fetchall())
    wrong = sorted({f"{r[0]} is '{real[r[0]]}', not '{r[1]}'" for r in rows
                    if r[0] in real and norm(real[r[0]]) != norm(r[1])})
    assert_true(not wrong,
                f"{len(wrong)} topic-crosswalk ids carry the wrong label: {wrong[:5]}",
                failures)


def check_life_zones(conn, failures: list[str]) -> None:
    """Holdridge life-zone layer invariants (ecosystem facet checked too)."""
    if table_rows(conn, "facility_life_zones") > 0:
        bad = conn.execute(
            """SELECT COUNT(*) FROM facility_life_zones fl
               LEFT JOIN life_zones z ON fl.life_zone_slug = z.slug
               WHERE z.slug IS NULL"""
        ).fetchone()[0]
        assert_true(bad == 0,
                    f"{bad} facility_life_zones rows reference unknown life_zone_slug",
                    failures)
    if table_rows(conn, "facility_ecosystems") > 0:
        bad = conn.execute(
            """SELECT COUNT(*) FROM facility_ecosystems fe
               LEFT JOIN ecosystem_types e ON fe.ecosystem_slug = e.slug
               WHERE e.slug IS NULL"""
        ).fetchone()[0]
        assert_true(bad == 0,
                    f"{bad} facility_ecosystems rows reference unknown ecosystem_slug",
                    failures)


def check_archives(conn, failures: list[str]) -> None:
    """Wave-J data-archive layer invariants."""
    if table_rows(conn, "facility_archives") > 0:
        orphan_archive = conn.execute(
            """SELECT COUNT(*) FROM facility_archives fa
               LEFT JOIN data_archives a ON fa.archive_id = a.archive_id
               WHERE a.archive_id IS NULL"""
        ).fetchone()[0]
        assert_true(orphan_archive == 0,
                    f"{orphan_archive} facility_archives rows point at unknown archives",
                    failures)
        orphan_fac = conn.execute(
            """SELECT COUNT(*) FROM facility_archives fa
               LEFT JOIN facilities f ON fa.facility_id = f.facility_id
               WHERE f.facility_id IS NULL"""
        ).fetchone()[0]
        assert_true(orphan_fac == 0,
                    f"{orphan_fac} facility_archives rows point at unknown facilities",
                    failures)
    if table_rows(conn, "data_archives") > 0:
        no_url = conn.execute(
            "SELECT COUNT(*) FROM data_archives WHERE base_url IS NULL OR base_url = ''"
        ).fetchone()[0]
        assert_true(no_url == 0,
                    f"{no_url} data_archives rows have no base_url", failures)
    if table_rows(conn, "data_products") > 0:
        orphan = conn.execute(
            """SELECT COUNT(*) FROM data_products p
               LEFT JOIN data_archives a ON p.archive_id = a.archive_id
               WHERE p.archive_id IS NOT NULL AND a.archive_id IS NULL"""
        ).fetchone()[0]
        assert_true(orphan == 0,
                    f"{orphan} data_products rows point at unknown archives", failures)


def check_person_registry(conn, failures: list[str]) -> None:
    """Registry identity invariants. No-ops while the registry is empty.

    The non-negotiable this enforces: identity comes from persistent
    identifiers, never from names. A row with neither an ORCID nor an
    OpenAlex id cannot be re-resolved or de-duplicated later.
    """
    if table_rows(conn, "person_registry") <= 0:
        return
    no_id = conn.execute(
        "SELECT COUNT(*) FROM person_registry WHERE orcid IS NULL AND openalex_id IS NULL"
    ).fetchone()[0]
    assert_true(no_id == 0,
                f"{no_id} person_registry rows have neither orcid nor openalex_id", failures)

    bad_key = conn.execute(
        """SELECT COUNT(*) FROM person_registry
           WHERE canonical_id NOT LIKE 'orcid:%' AND canonical_id NOT LIKE 'openalex:%'"""
    ).fetchone()[0]
    assert_true(bad_key == 0,
                f"{bad_key} person_registry rows have a malformed canonical_id", failures)

    bad_tier = conn.execute(
        "SELECT COUNT(*) FROM person_registry WHERE tier NOT IN ('core', 'archive')"
    ).fetchone()[0]
    assert_true(bad_tier == 0,
                f"{bad_tier} person_registry rows have an unknown tier", failures)

    # An ORCID-keyed row must carry that ORCID; catches key/field drift.
    key_drift = conn.execute(
        """SELECT COUNT(*) FROM person_registry
           WHERE canonical_id LIKE 'orcid:%'
             AND canonical_id <> 'orcid:' || orcid"""
    ).fetchone()[0]
    assert_true(key_drift == 0,
                f"{key_drift} person_registry rows whose canonical_id disagrees with orcid",
                failures)


VOCAB_DIR = Path(__file__).resolve().parent.parent / "schema" / "vocab"

# Roles older loaders wrote before personnel_roles.csv existed, tolerated
# here while rows still carried them. Empty since 2026-10-22, when the three
# 'research-collaborator' rows became 'collaborator'
# (data/seed/personnel_repairs_2026-10-22.csv); add an entry only with a
# migration that clears it.
LEGACY_ROLES: dict[str, str] = {}

# people.status values (schema.sql's comment, plus 'deceased', which the
# committed data uses; load_people_research.STATUS_MAP maps the rest).
PEOPLE_STATUSES = ("active", "emeritus", "former", "deceased", "unknown")

# Decision log of enrich_people_orcid.py and the review/wipe passes.
ORCID_LOG = Path(__file__).resolve().parent.parent / "data" / "seed" / "orcid_resolution_log.csv"

# More current holders of one leadership role at one facility than this is
# a loader fan-in (an acronym or fuzzy match that piled one network's
# managers onto a single facility: 26 NERR managers on Mission Aransas,
# Bonanza Creek and Tenderfoot Creek PIs on Bent Creek).
MAX_CURRENT_LEADERS = 5

# Reviewed pairs of different people at one facility whose names
# same_person_name() would take for one person: frozenset({id_a, id_b}).
DISTINCT_NAMESAKES: set[frozenset[str]] = set()


def check_people(conn, failures: list[str], warnings: list[str]) -> None:
    """People-layer invariants that schema.sql states in comments."""
    if table_rows(conn, "people") <= 0:
        return
    no_src = conn.execute(
        "SELECT COUNT(*) FROM people WHERE bio IS NOT NULL AND bio_source_url IS NULL"
    ).fetchone()[0]
    assert_true(no_src == 0, f"{no_src} people have a bio without bio_source_url", failures)

    roles_csv = VOCAB_DIR / "personnel_roles.csv"
    if roles_csv.exists() and table_rows(conn, "facility_personnel") > 0:
        bad = conn.execute(
            """SELECT role, COUNT(*) FROM facility_personnel
               WHERE role NOT IN (SELECT slug FROM read_csv_auto(?, header=True))
                 AND role NOT IN (SELECT unnest(?::VARCHAR[]))
               GROUP BY role ORDER BY role""",
            [str(roles_csv), list(LEGACY_ROLES)]).fetchall()
        assert_true(not bad, f"facility_personnel roles not in personnel_roles.csv: {bad}",
                    failures)

    # One ORCID, one person (scripts/dedupe_people.py merges them).
    dup = conn.execute(
        """SELECT upper(orcid), list(person_id ORDER BY person_id), any_value(name)
           FROM people WHERE orcid IS NOT NULL AND orcid <> ''
           GROUP BY 1 HAVING COUNT(*) > 1 ORDER BY 1"""
    ).fetchall()
    assert_true(not dup, f"{len(dup)} ORCID(s) held by more than one people row "
                         f"(run scripts/dedupe_people.py): "
                + "; ".join(f"{n} {o} {ids}" for o, ids, n in dup[:5]), failures)

    # An ORCID a review cleared as another person's must not come back on
    # that person (enrich_people_orcid.py honours the log; this catches any
    # other writer). Only cleared-wrong*: a cleared-404 record may reappear.
    if ORCID_LOG.exists():
        back = conn.execute(
            """SELECT p.name, p.person_id, p.orcid, l.decision
               FROM people p
               JOIN read_csv(?, header=True, all_varchar=True) l
                 ON l.person_id = p.person_id
                AND upper(trim(l.orcid)) = upper(trim(p.orcid))
               WHERE l.decision LIKE 'cleared-wrong%'
               ORDER BY 1""", [str(ORCID_LOG)]).fetchall()
        assert_true(not back, f"{len(back)} people carry an ORCID that "
                              f"{ORCID_LOG.name} marks cleared-wrong for them: "
                    + "; ".join(f"{n} ({pid}) {o} [{d}]" for n, pid, o, d in back[:5]),
                    failures)

    bad_status = conn.execute(
        "SELECT status, COUNT(*) FROM people WHERE status IS NOT NULL "
        "AND status NOT IN (SELECT unnest(?::VARCHAR[])) GROUP BY 1 ORDER BY 1",
        [list(PEOPLE_STATUSES)]).fetchall()
    assert_true(not bad_status, f"people.status outside {PEOPLE_STATUSES}: {bad_status}",
                failures)

    # Contact details stay in the lake: export_parquet.EXPORT_REDACT blanks
    # people.email on the way to public/ (served to anyone, queryable from
    # the SQL tab).
    pub = lto_db.PUBLIC_PARQUET / "people.parquet"
    if pub.exists():
        n_mail = conn.execute("SELECT count(email) FROM read_parquet(?)", [str(pub)]).fetchone()[0]
        assert_true(n_mail == 0, f"{n_mail} email addresses published in {pub.name} "
                                 f"(re-run export_parquet.py)", failures)

    if table_rows(conn, "facility_personnel") <= 0:
        return
    bad_conf = conn.execute(
        "SELECT confidence, COUNT(*) FROM facility_personnel WHERE confidence IS NULL "
        "OR confidence NOT IN ('high', 'medium', 'low') GROUP BY 1 ORDER BY 1").fetchall()
    assert_true(not bad_conf, f"facility_personnel.confidence not high/medium/low: {bad_conf}",
                failures)
    for sql, what in (
        ("end_date < start_date", "end_date before start_date"),
        # Against the row's own retrieval date, not today's: a term that
        # ends in 2029 is not an error in 2029 until a source says so.
        ("is_current AND end_date <= retrieved_at",
         "is_current = true from a source retrieved on/after the row's end_date"),
        ("evidence IS NOT NULL AND (source_url IS NULL OR retrieved_at IS NULL)",
         "evidence without source_url / retrieved_at"),
    ):
        n = conn.execute(f"SELECT COUNT(*) FROM facility_personnel WHERE {sql}").fetchone()[0]
        assert_true(n == 0, f"{n} facility_personnel rows with {what}", failures)
    # A person dedupe_people.py merged away must stay gone: a loader that
    # re-mints the id (a seed CSV or research file written before the merge)
    # brings the duplicate back. Loaders map these ids through
    # load_people_research.canonical_person_id.
    merged = merge_redirects()
    back = conn.execute(
        "SELECT person_id, name FROM people WHERE person_id IN (SELECT unnest(?::VARCHAR[])) "
        "ORDER BY 1", [sorted(merged)]).fetchall() if merged else []
    assert_true(not back, f"{len(back)} people rows carry an id merged away in "
                          f"data/seed/people_merge_log.csv (a loader re-created them): "
                + "; ".join(f"{n} {pid} -> {merged[pid]}" for pid, n in back[:5]), failures)

    # Two person_ids at one facility under spellings of one name ('Ken
    # Dunton' / 'Kenneth H. Dunton') are one person filed twice; one of them
    # then reads as a former holder replaced by themselves. Merge them via
    # data/seed/people_merge_seed.csv; a reviewed pair of real namesakes
    # goes in DISTINCT_NAMESAKES.
    by_fac: dict[str, list[tuple[str, str]]] = {}
    for fid, pid, name in conn.execute(
            "SELECT DISTINCT fp.facility_id, p.person_id, p.name FROM facility_personnel fp "
            "JOIN people p USING (person_id) ORDER BY ALL").fetchall():
        by_fac.setdefault(fid, []).append((pid, name))
    twins = []
    for fid, ppl in by_fac.items():
        for i, (a, na) in enumerate(ppl):
            for b, nb in ppl[i + 1:]:
                if frozenset((a, b)) not in DISTINCT_NAMESAKES and same_person_name(na, nb):
                    twins.append(f"{na} ({a}) / {nb} ({b}) @ {fid}")
    assert_true(not twins, f"{len(twins)} same-facility people pairs under one name "
                           f"(merge via data/seed/people_merge_seed.csv): " + "; ".join(twins[:5]),
                failures)

    if roles_csv.exists():
        fan = conn.execute(
            """SELECT f.canonical_name, fp.role, COUNT(*) FROM facility_personnel fp
               JOIN facilities f USING (facility_id)
               WHERE COALESCE(fp.is_current, true)
                 AND (fp.end_date IS NULL OR fp.end_date > current_date)
                 AND fp.role IN (SELECT slug FROM read_csv_auto(?, header=True)
                                 WHERE is_leadership AND slug <> 'leadership-team')
               GROUP BY ALL HAVING COUNT(*) > ? ORDER BY 3 DESC""",
            [str(roles_csv), MAX_CURRENT_LEADERS]).fetchall()
        assert_true(not fan, f"more than {MAX_CURRENT_LEADERS} current holders of one "
                             f"leadership role at a facility (loader fan-in?): {fan[:5]}",
                    failures)

    # An area inherited from a facility needs that facility link: a merge or
    # fix that drops a person's role (or a facility's area) leaves the People
    # tab saying 'via facility' beside 'No facility roles recorded'.
    # compute_person_areas.py prunes these rows.
    if table_rows(conn, "person_areas") > 0:
        stale = conn.execute(
            """SELECT count(*), count(DISTINCT person_id) FROM person_areas pa
               WHERE source = 'facility-area-inheritance'
                 AND NOT EXISTS (SELECT 1 FROM facility_personnel fp
                                 JOIN area_links al ON al.facility_id = fp.facility_id
                                 WHERE fp.person_id = pa.person_id
                                   AND al.area_id = pa.area_id)""").fetchone()
        assert_true(stale[0] == 0,
                    f"{stale[0]} facility-area-inheritance person_areas rows ({stale[1]} "
                    "people) have no facility link carrying that area — run "
                    "scripts/compute_person_areas.py and the rest of the compute chain",
                    failures)


# Vocabulary tables loaded verbatim from schema/vocab/<table>.csv by
# ingest.py's load_vocab (same column mapping).
VOCAB_SQL = {
    "facility_types": "SELECT slug, label, description FROM read_csv_auto(?, header=True)",
    "research_areas": "SELECT slug AS area_id, label, gcmd_uri, parent_slug AS parent_id "
                      "FROM read_csv_auto(?, header=True)",
    "networks": "SELECT slug AS network_id, label, level, url FROM read_csv_auto(?, header=True)",
    **{t: "SELECT * FROM read_csv_auto(?, header=True)"
       for t in ("spheres", "ecosystem_types", "life_zones", "archive_types",
                 "data_formats", "data_licenses", "access_modes")},
}


def check_vocab_sync(conn, warnings: list[str]) -> None:
    """Each vocab table should equal its canonical CSV.

    A warning: the next ingest.py reloads the table from the CSV, so a
    difference here is a change that run (and the export after it) will
    ship. Fix whichever side is wrong before that happens.
    """
    for t, sql in VOCAB_SQL.items():
        f = VOCAB_DIR / f"{t}.csv"
        if not f.exists() or table_rows(conn, t) < 0:
            continue
        try:
            only_csv = conn.execute(f"SELECT count(*) FROM (({sql}) EXCEPT (SELECT * FROM {t}))",
                                    [str(f)]).fetchone()[0]
            only_lake = conn.execute(f"SELECT count(*) FROM ((SELECT * FROM {t}) EXCEPT ({sql}))",
                                     [str(f)]).fetchone()[0]
        except duckdb.Error as e:
            warnings.append(f"vocab {t}: cannot compare with {f.name}: {str(e).splitlines()[0]}")
            continue
        if only_csv or only_lake:
            warnings.append(f"vocab {t} differs from schema/vocab/{f.name}: {only_csv} CSV row(s) "
                            f"not in the lake, {only_lake} lake row(s) not in the CSV")


def check_registry_edges(conn, failures: list[str]) -> None:
    """Undirected-edge conventions on both registry edge tables."""
    for table in ("registry_collaborations", "coauthor_edges"):
        if table_rows(conn, table) <= 0:
            continue
        unordered = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE canonical_id_a >= canonical_id_b"
        ).fetchone()[0]
        assert_true(unordered == 0,
                    f"{unordered} {table} rows violate canonical_id_a < canonical_id_b",
                    failures)
        dangling = conn.execute(
            f"""SELECT COUNT(*) FROM {table} e
                LEFT JOIN person_registry a ON a.canonical_id = e.canonical_id_a
                LEFT JOIN person_registry b ON b.canonical_id = e.canonical_id_b
                WHERE a.canonical_id IS NULL OR b.canonical_id IS NULL"""
        ).fetchone()[0]
        assert_true(dangling == 0,
                    f"{dangling} {table} rows have an endpoint missing from person_registry",
                    failures)


def check_view_sql_types(failures: list[str]) -> None:
    """No view query may return DECIMAL or HUGEINT to the browser.

    duckdb-wasm and duckdb-python disagree about these two types, and the
    disagreement is silent:

      * DECIMAL  -> Arrow structured value in wasm, plain float in python.
                    ``Number(v)`` on it is NaN. Every ``Number(x) || 0``
                    guard in the views then yields 0.
      * HUGEINT  -> BigInt in wasm, int in python. ``Number()`` copes, but
                    any arithmetic mixing it with a JS number throws
                    "Cannot mix BigInt and other types".

    This is exactly how cod-kmap's Knowledge Map died with "invalid
    bounds": a region weight was DECIMAL(38,2) because an integer count
    was multiplied by a JS-side decimal literal, ``Number(a.weight) || 0``
    made every weight 0, and the Voronoi bounding box was NaN. The SQL
    executed fine, the file parsed fine, and duckdb-python returned a
    plain float, so the local run was clean while the browser showed a
    blank page. Casting at the SQL boundary is the fix that holds
    regardless of which client reads the parquet.
    """
    import glob                                           # noqa: F401,PLC0415
    import re                                             # noqa: PLC0415

    root = Path(__file__).resolve().parent.parent
    site = root / "public" / "parquet"
    views = sorted((root / "src" / "views").glob("*.js"))
    if not views or not site.is_dir():
        return

    conn = duckdb.connect()
    for pq in site.glob("*.parquet"):
        conn.execute(
            f"CREATE OR REPLACE VIEW {pq.stem} AS "
            f"SELECT * FROM read_parquet('{pq.as_posix()}')")

    unsafe = ("DECIMAL", "HUGEINT", "UHUGEINT")
    for path in views:
        text = path.read_text()
        # Views interpolate numeric constants into SQL; substitute them so
        # the statement parses. Anything still interpolated is skipped.
        consts = dict(re.findall(r"const (W_[A-Z_]+)\s*=\s*([0-9.]+)", text))
        for m in re.finditer(r"`(\s*(?:WITH|SELECT)\b.*?)`", text, re.S):
            sql = m.group(1)
            for k, v in consts.items():
                sql = sql.replace("${" + k + "}", v)
            if "${" in sql or "?" in sql:
                continue
            try:
                rel = conn.sql(sql)
            except Exception:                             # noqa: BLE001
                # Type-checking is not this gate's job to enforce parseability;
                # check_frontend_parses and the view smoke tests cover that.
                continue
            for name, typ in zip(rel.columns, rel.types):
                if any(u in str(typ).upper() for u in unsafe):
                    assert_true(
                        False,
                        f"{path.name} returns column '{name}' as {typ}; "
                        f"duckdb-wasm hands DECIMAL/HUGEINT to JS as a "
                        f"non-number. Wrap it in CAST(... AS DOUBLE).",
                        failures)
    conn.close()


def check_frontend_parses(failures: list[str]) -> None:
    """Every src/*.js must be syntactically valid JavaScript.

    This exists because (upstream) a SQL comment inside a JS template
    literal read ``-- OpenAlex metrics that `people` alone does not``.
    The backticks closed the template literal and the whole site died
    with "Uncaught SyntaxError" — a blank page behind "Loading data…".
    Every query in the file still ran correctly when extracted and
    executed against DuckDB, so SQL-level verification passed while the
    page was unloadable. A character-balance heuristic does NOT catch
    this: the stray backticks come in pairs. Only a parser catches it.

    node's SourceTextModule parses the file as written, as an ES module,
    exactly as the browser does — no text substitution and no wrapper, so
    failures carry a real message and a real position. Construction
    parses without executing and without resolving imports, so bare
    specifiers ('maplibre-gl') that only an importmap resolves do not
    produce a false failure.

    Skipped, with a warning, if node is unavailable — the gate must still
    run in an environment that only has the Python data stack.
    """
    import json                                           # noqa: PLC0415
    import shutil                                         # noqa: PLC0415
    import subprocess                                     # noqa: PLC0415

    node = shutil.which("node")
    if not node:
        print("[qa] node not found — skipping the JS parse check. "
              "Install node to enable it.", file=sys.stderr)
        return

    src_dir = Path(__file__).resolve().parent.parent / "src"
    files = sorted(src_dir.rglob("*.js"))
    if not files:
        failures.append("no .js files found under src/ — is the checkout complete?")
        return

    script = """
const fs = require('fs');
const vm = require('vm');
const out = [];
for (const f of process.argv.slice(1)) {
  try {
    new vm.SourceTextModule(fs.readFileSync(f, 'utf8'), { identifier: f });
  } catch (e) {
    out.push({ file: f, error: String(e && e.message || e).slice(0, 200) });
  }
}
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(                                # noqa: S603
        [node, "--experimental-vm-modules", "-e", script, "--",
         *[str(f) for f in files]],
        capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0 and not proc.stdout.strip():
        failures.append(f"JS parse check could not run: "
                        f"{proc.stderr.strip().splitlines()[-1][:160]}"
                        if proc.stderr.strip() else "JS parse check failed to run")
        return
    try:
        problems = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        failures.append("JS parse check produced unreadable output")
        return
    for p in problems:
        rel = Path(p["file"]).relative_to(src_dir.parent)
        assert_true(False, f"{rel} is not valid JavaScript: {p['error']}",
                    failures)


def check_integrity(conn, failures: list[str]) -> None:
    """Every PRIMARY KEY, UNIQUE, FOREIGN KEY, CHECK and NOT NULL in schema.sql.

    The lake stores no constraints (DuckLake rejects them), so this is the
    only place they are enforced. Generated from duckdb_constraints() of
    schema.sql run in an in-memory spec database — a constraint added to
    the schema is checked here with no change to this file.
    """
    violations = lto_db.integrity_violations(conn)
    for v in violations:
        ref = f" -> {v['ref_table']}" if v.get("ref_table") else ""
        what = {"derived": "derived-table constraint",
                "soft": "soft reference"}.get(v.get("origin"), "schema constraint")
        assert_true(False,
                    f"{what} violated: {v['table']} {v['kind']} "
                    f"{v['columns']}{ref}: {v['count']} row(s)/key(s), "
                    f"e.g. {v['sample'][:3]}", failures)
    print(f"[qa] integrity: {lto_db.constraint_count()} constraints checked "
          f"(schema.sql + derived tables + soft references) and columns compared "
          f"with schema.sql; {len(violations)} violated", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="LTO data-quality gate")
    lto_db.add_argparse_catalog(ap)
    args = ap.parse_args()

    failures: list[str] = []
    warnings: list[str] = []
    try:
        conn = lto_db.connect(read_only=True, catalog=args.catalog, data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"QA FAILED:\n  - {e}")
        return 1
    with conn:
        check_integrity(conn, failures)

        # An empty facilities table is never a valid catalogue. Without this
        # every check below passes vacuously and export_parquet.py would then
        # overwrite the committed parquet with zero rows.
        n_fac = conn.execute("SELECT COUNT(*) FROM facilities").fetchone()[0]
        assert_true(n_fac > 0, "facilities is empty — refusing to pass an empty catalogue", failures)

        null_type = conn.execute(
            "SELECT COUNT(*) FROM facilities WHERE facility_type IS NULL OR country IS NULL"
        ).fetchone()[0]
        assert_true(null_type == 0, f"{null_type} facilities with null facility_type or country", failures)

        bad_enum = conn.execute(
            "SELECT COUNT(*) FROM facilities f LEFT JOIN facility_types t ON f.facility_type = t.slug WHERE t.slug IS NULL"
        ).fetchone()[0]
        assert_true(bad_enum == 0, f"{bad_enum} facilities reference unknown facility_type", failures)

        no_prov = conn.execute(
            """SELECT COUNT(*) FROM facilities f
               LEFT JOIN provenance p ON p.record_type='facility' AND p.record_id = f.facility_id
               WHERE p.record_id IS NULL"""
        ).fetchone()[0]
        assert_true(no_prov == 0, f"{no_prov} facilities without provenance rows", failures)

        # bbox checks — a facility is misplaced only if it falls outside
        # EVERY box for its country, so an offshore territory doesn't read
        # as an error.
        for country, (min_lat, max_lat, min_lng, max_lng) in BBOX_BY_COUNTRY.items():
            boxes = [(min_lat, max_lat, min_lng, max_lng)] + EXTRA_BBOXES.get(country, [])
            outside = " AND ".join(
                "(hq_lat < ? OR hq_lat > ? OR hq_lng < ? OR hq_lng > ?)" for _ in boxes)
            params: list[float | str] = [country]
            for box in boxes:
                params.extend(box)
            count = conn.execute(
                f"""SELECT COUNT(*) FROM facilities
                    WHERE country = ? AND hq_lat IS NOT NULL AND hq_lng IS NOT NULL
                    AND ({outside})""",
                params,
            ).fetchone()[0]
            assert_true(count == 0, f"{count} {country} facilities outside the country bbox", failures)

        # LTO layered tables. Each block no-ops when its table is empty or
        # absent, so the ingest-only CI rebuild isn't failed by data it
        # never produces.
        # A lake whose columns drifted from schema.sql (reported by
        # check_integrity) can make a hand-written check's SQL fail to
        # bind; that is reported as a failure, not a traceback.
        for check, extra in (
            (check_tables_present, ()), (check_columns, ()), (check_spheres, ()),
            (check_life_zones, ()), (check_archives, ()), (check_states, ()),
            (check_projects, ()), (check_portal_products, ()),
            (check_topic_crosswalk, ()), (check_person_registry, ()),
            (check_registry_edges, ()), (check_people, (warnings,)),
            (check_facility_merges, (warnings,)), (check_funder_merges, (warnings,)),
            (check_estuary_funding, ()),
        ):
            try:
                check(conn, failures, *extra)
            except duckdb.Error as e:
                failures.append(f"{check.__name__} could not run: "
                                f"{str(e).splitlines()[0][:200]}")
        check_vocab_sync(conn, warnings)

    # Outside the DB block: these read source files, not the database,
    # and must run even on a checkout with no data.
    check_frontend_parses(failures)
    check_view_sql_types(failures)

    for w in warnings:
        print(f"[qa] WARNING: {w}")

    if failures:
        print("QA FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("QA passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
