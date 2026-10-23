#!/usr/bin/env python3
"""Resolve `people` into the unified person_registry identity space.

WARNING -- THIS SCRIPT IS DESTRUCTIVE FOR THE ARCHIVE TIER.
It DELETEs person_registry (and ALL person_identity_source rows) and
rebuilds them from ONE local table only (`people`, ~120 identifier-bearing
rows). Any archive-tier identities harvested from OpenAlex by the
field-wide scholar harvest are NOT reconstructed by any script in the
registry build chain (build_person_registry ->
compute_registry_collaborations -> link_registry_facilities ->
rank_person_registry -> qa; the harvest is not in it). Re-run the harvest
explicitly, or restore the lake to the snapshot before this run
(``SELECT * FROM person_registry AT (VERSION => n)``; every run is one
snapshot, see lake.snapshots()), if you need the archive tier back. The
archive tier is not in public/parquet, which ships tier='core' only.


In upstream cod-kmap, three human-facing layers grew independently; an
audit on 2026-07-26 found they shared 1 ORCID and 6 exact names across 843
rows, which made "who works with whom" unanswerable: the same researcher
could be three rows with three different keys and no edge between them.
lto has a single curated layer (`people`), but the same fork happens the
moment the field-wide harvest lands a researcher who already staffs a
catalogued facility — unless both resolve to one registry row.

This script seeds `person_registry` from `people`, one row per human,
keyed on a persistent identifier and carrying a role flag per cohort
(is_site_personnel here; is_scholar is set by the harvest).

Merge rule — the load-bearing one
---------------------------------
Two rows merge ONLY on ORCID equality or openalex_id equality. Names are
never compared. Upstream cod-kmap had three separate wrong-person
incidents (scripts/wipe_bad_openalex_attributions.py,
wipe_medicine_attributions.py, and upstream's
wipe_misattributed_identifiers.py, the last of which cleared 1,460
authorship rows), and every one of them started with a name match. A row
with no persistent identifier is NOT written to the registry at all; it is
reported as unresolvable so it can be curated, because a registry row that
cannot be re-resolved forks into a duplicate on the next run.

canonical_id is derived from the identifier rather than hashed from
mutable fields: 'orcid:0000-…' when an ORCID is known, else
'openalex:A…'. There is no third form — lto's qa.py requires every
registry row to carry at least one of orcid/openalex_id and rejects any
other canonical_id shape (upstream's codp: local ids do not exist here).
Re-running after an ORCID is discovered re-keys the row deliberately and
visibly, rather than silently creating a second one. qa.py asserts the id
and the ORCID agree.

Usage::

    python scripts/build_person_registry.py --dry-run
    python scripts/build_person_registry.py

The rebuild is one lake snapshot; scripts/export_parquet.py publishes it.
--export-parquet is accepted for old callers and does nothing.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_TABLES = ("person_registry", "person_identity_source",
                   "registry_collaborations", "registry_facilities")

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
OA_RE = re.compile(r"^A\d+$")


def clean_orcid(v) -> str | None:
    """Return a bare ORCID, or None. Rejects anything not ORCID-shaped.

    In upstream cod-kmap, two rows in `people` held biography prose in the
    orcid column until wipe_misattributed_identifiers.py moved it to notes;
    this guard means such a value can never key a registry row.
    """
    if not v:
        return None
    m = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", str(v))
    return m.group(1) if m else None


def clean_oa(v) -> str | None:
    if not v:
        return None
    s = str(v).rstrip("/").rsplit("/", 1)[-1].strip()
    return s if OA_RE.match(s) else None


def split_name(full: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"\s+", (full or "").strip()) if p]
    if len(parts) < 2:
        return "", (parts[0] if parts else "")
    return " ".join(parts[:-1]), parts[-1]


def ensure_tables(conn) -> None:
    """Create the registry tables if this lake predates them.

    schema.sql cannot be executed against the lake (DuckLake rejects its
    PRIMARY KEYs), so each missing table is created column-only from the
    schema.sql spec; lto_db.assert_integrity enforces the keys. Only absent
    tables are created — an existing populated table is never replaced.
    Call inside a transaction.
    """
    spec_tables = set(lto_db.spec()["tables"])
    if not all(t in spec_tables for t in REGISTRY_TABLES):
        print("[error] schema.sql has no person_registry DDL", file=sys.stderr)
        raise SystemExit(2)
    have = set(lto_db.lake_tables(conn))
    for t in REGISTRY_TABLES:
        if t not in have:
            conn.execute(lto_db.column_only_ddl(t))
            print(f"[schema] created {t} from schema/schema.sql")


class Registry:
    """Accumulates rows, merging only on identifier equality."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.by_orcid: dict[str, dict] = {}
        self.by_oa: dict[str, dict] = {}
        self.prov: list[dict] = []
        self.unresolvable: list[tuple[str, str]] = []
        self.merges = 0

    def _record(self, row: dict, field: str, value, method: str,
                evidence: str, source_url: str, confidence: str) -> None:
        self.prov.append(dict(
            canonical_id=row["canonical_id"], field=field,
            value=None if value is None else str(value), method=method,
            evidence=evidence, source_url=source_url, confidence=confidence,
            retrieved_at=date.today().isoformat()))

    def add(self, *, name: str, orcid: str | None, openalex_id: str | None,
            cohort: str | None, source: str, source_url: str, confidence: str,
            extra: dict | None = None) -> dict | None:
        """Insert or merge one source row. Returns the registry row, or None
        when the row carries no usable identifier.

        Unlike upstream cod-kmap there is no local_id escape hatch: lto's
        qa.py requires every person_registry row to carry an ORCID or an
        OpenAlex id, and canonical_id has exactly those two forms. A curated
        `people` row without either is still a real human, but a registry
        row for them could not be re-resolved or de-duplicated later, so it
        is SKIPPED here (counted and printed) rather than minted a local
        key. Run the enrichment scripts (enrich_people_orcid.py /
        enrich_people_openalex.py) or curate an identifier by hand, then
        re-run."""
        orcid = clean_orcid(orcid)
        openalex_id = clean_oa(openalex_id)
        if not orcid and not openalex_id:
            self.unresolvable.append((source, name))
            return None

        existing = (self.by_orcid.get(orcid) if orcid else None) \
            or (self.by_oa.get(openalex_id) if openalex_id else None)

        if existing is not None:
            self.merges += 1
            matched_on = "orcid" if (orcid and orcid in self.by_orcid) else "openalex_id"
            self._record(existing, "merge", name, f"{matched_on}-equality",
                         f"{source} row '{name}' merged into "
                         f"{existing['canonical_id']} on {matched_on} equality",
                         source_url, "high")
            row = existing
            # Fill identifiers this source knows and the existing row doesn't.
            if orcid and not row.get("orcid"):
                row["orcid"] = orcid
                self.by_orcid[orcid] = row
                # Re-key: an ORCID outranks an OpenAlex id for canonical_id.
                if row["canonical_id"].startswith("openalex:"):
                    row["canonical_id"] = f"orcid:{orcid}"
                self._record(row, "orcid", orcid, "seed",
                             f"supplied by {source}", source_url, "high")
            if openalex_id and not row.get("openalex_id"):
                row["openalex_id"] = openalex_id
                self.by_oa[openalex_id] = row
                self._record(row, "openalex_id", openalex_id, "seed",
                             f"supplied by {source}", source_url, "high")
        else:
            given, family = split_name(name)
            if orcid:
                cid = f"orcid:{orcid}"
            else:
                cid = f"openalex:{openalex_id}"
            row = dict(canonical_id=cid, display_name=name,
                       name_given=given, name_family=family,
                       orcid=orcid, openalex_id=openalex_id,
                       google_scholar_id=None, scopus_author_id=None,
                       wos_researcher_id=None, homepage_url=None,
                       affiliation=None, affiliation_ror=None,
                       affiliation_country=None,
                       is_site_personnel=False, is_scholar=False,
                       person_id=None,
                       works_count=None, cited_by_count=None, h_index=None,
                       i10_index=None, two_yr_mean_citedness=None,
                       lto_works_count=None, lto_share=None,
                       first_pub_year=None,
                       tier="archive", tier_rank=None, tier_score=None,
                       source=source, source_url=source_url,
                       confidence=confidence,
                       retrieved_at=date.today().isoformat(), notes=None)
            self.rows.append(row)
            if orcid:
                self.by_orcid[orcid] = row
            if openalex_id:
                self.by_oa[openalex_id] = row
            self._record(row, "canonical_id", cid, "seed",
                         f"created from {source} row '{name}'",
                         source_url, confidence)

        if cohort:
            row[f"is_{cohort}"] = True
        for k, v in (extra or {}).items():
            if v is not None and row.get(k) in (None, ""):
                row[k] = v
        return row


def load(conn, table: str, cols: str) -> list[dict]:
    try:
        cur = conn.execute(f"SELECT {cols} FROM {table}")
    except duckdb.Error:
        return []
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--export-parquet", action="store_true",
                    help="deprecated no-op: run scripts/export_parquet.py")
    args = ap.parse_args()

    # A dry run reads only; the registry tables are created (if absent)
    # inside the write transaction below, so it never writes a snapshot.
    conn = lto_db.connect(read_only=args.dry_run,
                          catalog=args.catalog, data=args.lake_data)
    reg = Registry()

    # ── people (facility staff / directory) ────────────────────────────
    people = load(conn, "people",
                  "person_id, name, orcid, openalex_id, google_scholar_id, "
                  "scopus_author_id, wos_researcher_id, homepage_url")
    staffed = {r[0] for r in conn.execute(
        "SELECT DISTINCT person_id FROM facility_personnel").fetchall()}
    # `people` is the facility directory, but not every row actually staffs a
    # catalogued facility. is_site_personnel means "staffs a site", so it is
    # set from facility_personnel rather than from mere presence in `people`;
    # the rest still enter the registry (identifier permitting) with
    # is_site_personnel=False and pick up is_scholar later if the field-wide
    # harvest claims them.
    for p in people:
        row = reg.add(name=p["name"], orcid=p["orcid"],
                      openalex_id=p["openalex_id"],
                      cohort="site_personnel" if p["person_id"] in staffed
                             else None,
                      source="people", source_url="lto:people",
                      confidence="high",
                      extra=dict(person_id=p["person_id"],
                                 google_scholar_id=p["google_scholar_id"],
                                 scopus_author_id=p["scopus_author_id"],
                                 wos_researcher_id=p["wos_researcher_id"],
                                 homepage_url=p["homepage_url"]))
        if row is not None:
            row["person_id"] = p["person_id"]

    # is_scholar is deliberately NOT set here: it belongs to the field-wide
    # OpenAlex harvest, which writes its own registry rows (and merges into
    # these on identifier equality). See the destructive-rebuild warning at
    # the top of this file.

    # ── report ─────────────────────────────────────────────────────────
    n = len(reg.rows)
    both = sum(1 for r in reg.rows
               if sum([r["is_site_personnel"], r["is_scholar"]]) > 1)
    print(f"[registry] {len(people)} people -> {n} distinct identities")
    print(f"[registry] {reg.merges} merge(s) on identifier equality; "
          f"{both} identity/identities appear in more than one cohort")
    print(f"[registry] cohorts: "
          f"site_personnel={sum(r['is_site_personnel'] for r in reg.rows)} "
          f"scholar={sum(r['is_scholar'] for r in reg.rows)}")
    if reg.unresolvable:
        by_src: dict[str, int] = {}
        for src, _ in reg.unresolvable:
            by_src[src] = by_src.get(src, 0) + 1
        print(f"[registry] {len(reg.unresolvable)} row(s) had no persistent "
              f"identifier and were NOT written: {by_src}")
        print("           (run scripts/enrich_people_orcid.py / "
              "enrich_people_openalex.py, or curate an ORCID by hand, "
              "then re-run)")

    if args.dry_run:
        conn.close()
        return 0

    cols = list(reg.rows[0].keys()) if reg.rows else []
    pcols = ["canonical_id", "field", "value", "method", "evidence",
             "source_url", "confidence", "retrieved_at"]
    with lto_db.transaction(conn, f"build_person_registry: rebuild from people "
                                  f"({n} identities, {len(reg.prov)} sources)"):
        ensure_tables(conn)
        # Stage in temp tables typed like the targets, then one INSERT each:
        # row-by-row INSERTs into the lake are slow.
        conn.execute("CREATE OR REPLACE TEMP TABLE _reg_stage AS "
                     "SELECT * FROM person_registry LIMIT 0")
        conn.execute("CREATE OR REPLACE TEMP TABLE _src_stage AS "
                     "SELECT * FROM person_identity_source LIMIT 0")
        if reg.rows:
            conn.executemany(
                f"INSERT INTO _reg_stage ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [[r[c] for c in cols] for r in reg.rows])
        if reg.prov:
            conn.executemany(
                f"INSERT INTO _src_stage ({','.join(pcols)}) "
                f"VALUES ({','.join('?' * len(pcols))})",
                [[p[c] for c in pcols] for p in reg.prov])
        conn.execute("DELETE FROM person_registry")
        conn.execute("DELETE FROM person_identity_source")
        if reg.rows:
            conn.execute(f"INSERT INTO person_registry ({','.join(cols)}) "
                         f"SELECT {','.join(cols)} FROM _reg_stage")
        if reg.prov:
            conn.execute(f"INSERT INTO person_identity_source ({','.join(pcols)}) "
                         f"SELECT {','.join(pcols)} FROM _src_stage")
        lto_db.assert_integrity(conn, ["person_registry", "person_identity_source"])
    print(f"[db] person_registry {n} rows, "
          f"person_identity_source {len(reg.prov)} rows")

    if args.export_parquet:
        print("[note] --export-parquet is a no-op now; run "
              "scripts/export_parquet.py to publish the lake")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
