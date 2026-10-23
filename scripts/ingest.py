"""cod-kmap ingest pipeline (D2 deliverable).

Reads all research-agent JSON under data/raw/R*/, normalizes and deduplicates
records, geocodes missing coordinates, upserts everything into the DuckLake
store of record (db/lto_catalog.sqlite + db/lake/, see scripts/lto_db.py)
per schema/schema.sql, and records provenance.

The lake must exist (scripts/rebuild_lake_from_parquet.py). This is an
upsert, not a rebuild: the national raw inputs are not in the repo, so
facilities already in the lake and absent from data/raw stay as they are.
One run is one lake snapshot; populate_regions (unless --skip-regions)
writes a second.

Usage:
    python scripts/ingest.py                # upsert data/raw/R*/ into the lake
    python scripts/ingest.py --skip-geocode # use cache only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from geocode import Geocoder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
VOCAB_DIR = ROOT / "schema" / "vocab"


def facility_id(name: str, acronym: str | None) -> str:
    key = (name or "").strip().lower() + "|" + (acronym or "").strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def funder_id(name: str) -> str:
    return hashlib.sha1(name.strip().lower().encode("utf-8")).hexdigest()[:16]


def location_id(fid: str, label: str | None) -> str:
    return hashlib.sha1((fid + "|" + (label or "")).encode("utf-8")).hexdigest()[:16]


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


@dataclass
class Record:
    agent: str
    raw: dict
    fid: str = ""
    merged_from: list[str] = field(default_factory=list)


def load_raw_records() -> list[Record]:
    # Skip the cod-kmap heritage non-US directories (R5 Canada, R6 Mexico/
    # Central America, R7 South America, R8 Northern Caribbean) — their
    # U.S. + territory + U.S.-funded Antarctic subset has already been
    # extracted into R-AQ-OCEAN-CULL/facilities_ocean_us.json, so re-loading
    # them here would just resurrect the non-US records the cull dropped.
    SKIP_DIRS = {"R5", "R6", "R7", "R8"}
    records: list[Record] = []
    for agent_dir in sorted(RAW_DIR.glob("R*")):
        if agent_dir.name in SKIP_DIRS:
            continue
        agent = agent_dir.name
        for path in sorted(agent_dir.glob("facilities_*.json")):
            try:
                with path.open() as f:
                    payload = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[warn] {path} is not valid JSON: {e}", file=sys.stderr)
                continue
            if not isinstance(payload, list):
                print(f"[warn] {path} is not a JSON array, skipping", file=sys.stderr)
                continue
            for rec in payload:
                rec["_source_file"] = str(path.relative_to(ROOT))
                records.append(Record(agent=agent, raw=rec))
    return records


def assign_ids(records: list[Record]) -> None:
    for r in records:
        r.fid = facility_id(r.raw.get("canonical_name", ""), r.raw.get("acronym"))


def dedup(records: list[Record]) -> list[Record]:
    """Merge records across agents using id / url / fuzzy-name + proximity."""
    by_key: dict[str, Record] = {}
    url_index: dict[str, Record] = {}

    for r in records:
        name = (r.raw.get("canonical_name") or "").strip()
        url = (r.raw.get("url") or "").strip().lower() or None

        match: Record | None = by_key.get(r.fid)
        if match is None and url and url in url_index:
            match = url_index[url]
        if match is None:
            for cand in by_key.values():
                if fuzz.token_set_ratio(name, cand.raw.get("canonical_name", "")) >= 92:
                    try:
                        a = (float(r.raw["hq"]["lat"]), float(r.raw["hq"]["lng"]))
                        b = (float(cand.raw["hq"]["lat"]), float(cand.raw["hq"]["lng"]))
                        if haversine_km(a, b) < 5:
                            match = cand
                            break
                    except (KeyError, TypeError, ValueError):
                        continue

        if match is None:
            by_key[r.fid] = r
            if url:
                url_index[url] = r
            continue

        # merge r into match, preferring higher-confidence source.
        merged = merge(match.raw, r.raw)
        match.raw = merged
        match.merged_from.append(r.agent)

    return list(by_key.values())


CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}


def pick(a: Any, b: Any, prov_a: dict | None, prov_b: dict | None) -> Any:
    if a in (None, "", []):
        return b
    if b in (None, "", []):
        return a
    ra = CONFIDENCE_RANK.get((prov_a or {}).get("confidence"))
    rb = CONFIDENCE_RANK.get((prov_b or {}).get("confidence"))
    return a if ra >= rb else b


def merge(dst: dict, src: dict) -> dict:
    pa, pb = dst.get("provenance"), src.get("provenance")
    out = dict(dst)
    for k in [
        "canonical_name", "acronym", "parent_org", "facility_type", "country",
        "region", "url", "contact", "established",
    ]:
        out[k] = pick(dst.get(k), src.get(k), pa, pb)

    # HQ
    hq_a, hq_b = dst.get("hq") or {}, src.get("hq") or {}
    out["hq"] = {
        "address": pick(hq_a.get("address"), hq_b.get("address"), pa, pb),
        "lat": pick(hq_a.get("lat"), hq_b.get("lat"), pa, pb),
        "lng": pick(hq_a.get("lng"), hq_b.get("lng"), pa, pb),
    }

    # Union list fields
    def union(key: str) -> list:
        seen, result = set(), []
        for item in (dst.get(key) or []) + (src.get(key) or []):
            marker = json.dumps(item, sort_keys=True) if isinstance(item, dict) else item
            if marker not in seen:
                seen.add(marker)
                result.append(item)
        return result

    out["locations"] = union("locations")
    out["research_areas"] = union("research_areas")
    out["networks"] = union("networks")
    out["funders"] = union("funders")
    out["provenance"] = dst.get("provenance") or src.get("provenance")
    return out


def geocode_missing(records: list[Record], skip: bool) -> None:
    if skip:
        return
    gc = Geocoder()
    for r in records:
        hq = r.raw.setdefault("hq", {})
        if (hq.get("lat") is None or hq.get("lng") is None) and hq.get("address"):
            coords = gc.lookup(hq["address"])
            if coords:
                hq["lat"], hq["lng"] = coords


def load_spatial(conn: duckdb.DuckDBPyConnection) -> None:
    try:
        conn.execute("INSTALL spatial; LOAD spatial;")
    except duckdb.Error as e:
        print(f"[warn] spatial extension unavailable ({e}); continuing without geom support")


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    # schema.sql cannot run against the lake (it fails on the first
    # PRIMARY KEY); lto_db.ensure_schema adds whatever tables or columns
    # it has gained since the lake was built, and never drops anything.
    for change in lto_db.ensure_schema(conn):
        print(f"[schema] {change}")


def load_vocab(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DELETE FROM main.facility_types")
    conn.execute(
        "INSERT INTO main.facility_types SELECT * FROM read_csv_auto(?, header=True)",
        [str(VOCAB_DIR / "facility_types.csv")],
    )
    conn.execute("DELETE FROM main.research_areas")
    conn.execute(
        """
        INSERT INTO main.research_areas
        SELECT slug AS area_id, label, gcmd_uri, parent_slug AS parent_id
        FROM read_csv_auto(?, header=True)
        """,
        [str(VOCAB_DIR / "research_areas.csv")],
    )
    conn.execute("DELETE FROM main.networks")
    conn.execute(
        """
        INSERT INTO main.networks
        SELECT slug AS network_id, label, level, url
        FROM read_csv_auto(?, header=True)
        """,
        [str(VOCAB_DIR / "networks.csv")],
    )

    # LTO vocab tables (load only if CSVs are present).
    for tbl in ("spheres", "ecosystem_types", "life_zones",
                "archive_types", "data_formats", "data_licenses", "access_modes"):
        csv_path = VOCAB_DIR / f"{tbl}.csv"
        if not csv_path.exists():
            continue
        conn.execute(f"DELETE FROM main.{tbl}")
        conn.execute(
            f"INSERT INTO main.{tbl} SELECT * FROM read_csv_auto(?, header=True)",
            [str(csv_path)],
        )


def _stage(conn: duckdb.DuckDBPyConnection, name: str, cols: str, rows: list[tuple]) -> None:
    """A TEMP table of rows from Python, with a `_seq` column in input
    order so merge_upsert can keep the first (INSERT OR IGNORE) or the
    last (INSERT OR REPLACE) of two rows with the same key."""
    conn.execute(f"CREATE OR REPLACE TEMP TABLE {name} ({cols}, _seq INTEGER)")
    if rows:
        n = cols.count(",") + 2
        conn.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * n)})",
                         [(*r, i) for i, r in enumerate(rows)])


def insert_records(conn: duckdb.DuckDBPyConnection, records: list[Record]) -> dict:
    """Upsert the records and their link rows. Returns merge_upsert stats
    per table.

    Rows are collected per table and written with one MERGE each. The
    lake checks no foreign keys, so the link rows whose vocab slug is
    unknown, which DuckDB used to reject one by one, are filtered out
    by a join against the vocab table instead (still silently: a single
    typo in an R-agent's output doesn't tank the ingest)."""
    today = datetime.now(timezone.utc).date()

    fac, spheres, ecos, lzs, locs, areas, nets = [], [], [], [], [], [], []
    funders, events, prov = [], [], []
    for r in records:
        d = r.raw
        hq = d.get("hq") or {}
        fac.append((
            r.fid, d.get("canonical_name"), d.get("acronym"), d.get("parent_org"),
            d.get("facility_type"), d.get("country"), d.get("region"),
            hq.get("address"), hq.get("lat"), hq.get("lng"), d.get("url"),
            d.get("contact"), d.get("established"), d.get("record_length_years"),
            d.get("long_term_threshold_met"), d.get("data_portal_url"),
        ))

        # LTO sphere / ecosystem / life-zone link tables.
        primary = d.get("primary_sphere")
        if primary:
            spheres.append((r.fid, primary, "primary"))
        for sec in d.get("secondary_spheres") or []:
            if sec and sec != primary:
                spheres.append((r.fid, sec, "secondary"))
        ecos += [(r.fid, eco) for eco in d.get("ecosystem_types") or []]
        lzs += [(r.fid, lz) for lz in d.get("life_zones") or []]

        locations: list[dict] = d.get("locations") or []
        if not locations and d.get("hq"):
            locations = [{
                "label": d.get("canonical_name"),
                "address": d["hq"].get("address"),
                "lat": d["hq"].get("lat"),
                "lng": d["hq"].get("lng"),
                "role": "headquarters",
            }]
        for loc in locations:
            locs.append((
                location_id(r.fid, loc.get("label")), r.fid, loc.get("label"),
                loc.get("address"), loc.get("lat"), loc.get("lng"),
                loc.get("role") or "headquarters",
            ))

        areas += [(r.fid, area) for area in d.get("research_areas") or []]
        for net in d.get("networks") or []:
            nets.append((r.fid, net.lower() if isinstance(net, str) else str(net).lower()))

        for funder in d.get("funders") or []:
            fname = funder.get("name") if isinstance(funder, dict) else str(funder)
            if not fname:
                continue
            fuid = funder_id(fname)
            funders.append((fuid, fname))
            # funding_links is a backwards-compat view over funding_events
            # in the LTO schema. Insert into funding_events directly.
            events.append((
                location_id(fuid, r.fid),  # deterministic event_id stub
                fuid,
                r.fid,
                (funder.get("relation") if isinstance(funder, dict) else None),
                d.get("provenance", {}).get("source_url"),
            ))

        p = d.get("provenance") or {}
        prov.append((
            "facility", r.fid, p.get("source_url"),
            p.get("retrieved_at") or today.isoformat(),
            p.get("confidence", "medium"), r.agent,
        ))

    stats: dict[str, dict] = {}
    up = lto_db.merge_upsert

    # Named columns, not positional: the table has gained columns (ror,
    # state) that raw records don't carry. Those, and created_at, keep
    # their lake values on a match; a new row gets created_at = now.
    _stage(conn, "_s_facilities",
           "facility_id VARCHAR, canonical_name VARCHAR, acronym VARCHAR, "
           "parent_org VARCHAR, facility_type VARCHAR, country VARCHAR, region VARCHAR, "
           "hq_address VARCHAR, hq_lat DOUBLE, hq_lng DOUBLE, url VARCHAR, contact VARCHAR, "
           "established INTEGER, record_length_years INTEGER, "
           "long_term_threshold_met BOOLEAN, data_portal_url VARCHAR", fac)
    stats["facilities"] = up(conn, "facilities", ["facility_id"], "_s_facilities",
                             order_by="_seq DESC")

    def links(table: str, cols: str, rows: list[tuple], key: list[str],
              vocab: str, vocab_col: str, ref_col: str,
              replace_for: set[str] | None = None, insert_only: bool = True) -> None:
        """Write one link table. ``replace_for``: facilities whose raw
        record carries this field, so the record is the whole truth for
        it — their existing rows are deleted first and a link the record
        dropped does not linger. (Before the lake, ingest re-created every
        table from schema.sql, so links always matched the raw data.)"""
        _stage(conn, f"_s_{table}", cols, rows)
        if replace_for:
            conn.execute(f"DELETE FROM main.{table} WHERE facility_id IN "
                         f"(SELECT unnest(?::VARCHAR[]))", [sorted(replace_for)])
        stats[table] = up(
            conn, table, key,
            f"SELECT s.* FROM _s_{table} s WHERE EXISTS "
            f"(SELECT 1 FROM main.{vocab} v WHERE v.{vocab_col} = s.{ref_col})",
            insert_only=insert_only, order_by="_seq")
        stats[table]["unknown_slug"] = len(rows) - stats[table]["source_rows"]

    def carrying(*fields: str) -> set[str]:
        return {r.fid for r in records if any(f in r.raw for f in fields)}

    # Spheres: the raw record's primary/secondary set replaces the
    # facility's rows. That includes the 'arid' rows scripts/add_arid_sphere.py
    # adds, so re-run it (idempotent) after an ingest, as before.
    links("facility_spheres", "facility_id VARCHAR, sphere_slug VARCHAR, role VARCHAR",
          spheres, ["facility_id", "sphere_slug"], "spheres", "slug", "sphere_slug",
          replace_for=carrying("primary_sphere", "secondary_spheres"))
    links("facility_ecosystems", "facility_id VARCHAR, ecosystem_slug VARCHAR",
          ecos, ["facility_id", "ecosystem_slug"], "ecosystem_types", "slug", "ecosystem_slug",
          replace_for=carrying("ecosystem_types"))
    links("facility_life_zones", "facility_id VARCHAR, life_zone_slug VARCHAR",
          lzs, ["facility_id", "life_zone_slug"], "life_zones", "slug", "life_zone_slug",
          replace_for=carrying("life_zones"))
    links("area_links", "facility_id VARCHAR, area_id VARCHAR",
          areas, ["facility_id", "area_id"], "research_areas", "area_id", "area_id",
          replace_for=carrying("research_areas"))
    # Not replaced: other loaders add memberships to ingested facilities
    # (load_arid.py's arid-unm rows), and the raw records do not know them.
    links("network_membership", "facility_id VARCHAR, network_id VARCHAR",
          nets, ["facility_id", "network_id"], "networks", "network_id", "network_id")

    _stage(conn, "_s_locations",
           "location_id VARCHAR, facility_id VARCHAR, label VARCHAR, address VARCHAR, "
           "lat DOUBLE, lng DOUBLE, role VARCHAR", locs)
    stats["locations"] = up(conn, "locations", ["location_id"], "_s_locations",
                            order_by="_seq DESC")

    _stage(conn, "_s_funders", "funder_id VARCHAR, name VARCHAR", funders)
    stats["funders"] = up(conn, "funders", ["funder_id"], "_s_funders",
                          insert_only=True, order_by="_seq")
    _stage(conn, "_s_events",
           "event_id VARCHAR, funder_id VARCHAR, facility_id VARCHAR, relation VARCHAR, "
           "source_url VARCHAR", events)
    stats["funding_events"] = up(
        conn, "funding_events", ["event_id"],
        "SELECT *, CURRENT_DATE AS retrieved_at, 'low' AS confidence FROM _s_events",
        insert_only=True, order_by="_seq")

    # provenance has no key; replace this agent's row for each facility so
    # a re-run does not stack duplicates.
    _stage(conn, "_s_provenance",
           "record_type VARCHAR, record_id VARCHAR, source_url VARCHAR, "
           "retrieved_at DATE, confidence VARCHAR, agent VARCHAR", prov)
    conn.execute(
        "DELETE FROM main.provenance p WHERE EXISTS (SELECT 1 FROM _s_provenance s "
        "WHERE s.record_type = p.record_type AND s.record_id = p.record_id "
        "AND s.agent IS NOT DISTINCT FROM p.agent)")
    conn.execute("INSERT INTO main.provenance SELECT * EXCLUDE (_seq) FROM _s_provenance")
    stats["provenance"] = {"inserted": len(prov)}
    return stats


def log_run(conn: duckdb.DuckDBPyConnection, started: datetime, count: int, status: str) -> None:
    run_id = started.strftime("%Y%m%d-%H%M%S")
    conn.execute(
        "INSERT INTO main.ingest_runs VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)",
        [run_id, started, os.environ.get("GITHUB_SHA"), count, status],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-geocode", action="store_true")
    parser.add_argument("--skip-regions",  action="store_true",
                        help="Don't rebuild the regions / facility_regions "
                             "tables from public/overlays/ (saves time if "
                             "overlays haven't changed).")
    lto_db.add_argparse_catalog(parser)
    args = parser.parse_args()

    started = datetime.now(timezone.utc)

    records = load_raw_records()
    if not records:
        print("[info] no raw records found — refreshing schema and vocab only")
    assign_ids(records)
    records = dedup(records)
    geocode_missing(records, args.skip_geocode)

    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    try:
        load_spatial(conn)
        with lto_db.transaction(conn, f"ingest: {len(records)} facilities from data/raw/R*"):
            ensure_schema(conn)
            load_vocab(conn)
            stats = insert_records(conn, records)
            log_run(conn, started, len(records), "success")
            lto_db.assert_integrity(conn, [
                "facility_types", "research_areas", "networks", "spheres",
                "ecosystem_types", "life_zones", "archive_types", "data_formats",
                "data_licenses", "access_modes", "facilities", "locations",
                "funders", "funding_events", "area_links", "network_membership",
                "facility_spheres", "facility_ecosystems", "facility_life_zones",
                "provenance", "ingest_runs",
            ])
        for table, st in stats.items():
            print(f"  {table:20s} {st}")
        print(f"[ok] wrote {len(records)} facilities to {lto_db.catalog_path(args.catalog)}")

        # Rebuild the overlay-derived tables unless the caller opted out.
        if not args.skip_regions:
            try:
                # Import lazily so the ingest step doesn't require shapely
                # unless the user asks for the regions pass.
                from populate_regions import populate as populate_regions
                populate_regions(conn)
            except Exception as e:
                print(f"[warn] populate_regions failed ({e!r}); continuing")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
