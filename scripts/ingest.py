"""cod-kmap ingest pipeline (D2 deliverable).

Reads all research-agent JSON under data/raw/R*/, normalizes and deduplicates
records, geocodes missing coordinates, loads everything into
db/cod_kmap.duckdb per schema/schema.sql, and records provenance.

Usage:
    python scripts/ingest.py                # full rebuild
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

from geocode import Geocoder

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SCHEMA_SQL = ROOT / "schema" / "schema.sql"
VOCAB_DIR = ROOT / "schema" / "vocab"
DB_PATH = ROOT / "db" / "cod_kmap.duckdb"


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
    records: list[Record] = []
    for agent_dir in sorted(RAW_DIR.glob("R*")):
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


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    try:
        conn.execute("INSTALL spatial; LOAD spatial;")
    except duckdb.Error as e:
        print(f"[warn] spatial extension unavailable ({e}); continuing without geom support")
    conn.execute(SCHEMA_SQL.read_text())


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


def insert_records(conn: duckdb.DuckDBPyConnection, records: list[Record]) -> None:
    today = datetime.now(timezone.utc).date()

    for r in records:
        d = r.raw
        conn.execute(
            """INSERT OR REPLACE INTO main.facilities VALUES
               (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [
                r.fid,
                d.get("canonical_name"),
                d.get("acronym"),
                d.get("parent_org"),
                d.get("facility_type"),
                d.get("country"),
                d.get("region"),
                (d.get("hq") or {}).get("address"),
                (d.get("hq") or {}).get("lat"),
                (d.get("hq") or {}).get("lng"),
                d.get("url"),
                d.get("contact"),
                d.get("established"),
            ],
        )

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
            conn.execute(
                "INSERT OR REPLACE INTO main.locations VALUES (?,?,?,?,?,?,?)",
                [
                    location_id(r.fid, loc.get("label")),
                    r.fid,
                    loc.get("label"),
                    loc.get("address"),
                    loc.get("lat"),
                    loc.get("lng"),
                    loc.get("role") or "headquarters",
                ],
            )

        for area in d.get("research_areas") or []:
            conn.execute(
                "INSERT OR IGNORE INTO main.area_links VALUES (?, ?)",
                [r.fid, area],
            )

        for net in d.get("networks") or []:
            net_slug = net.lower() if isinstance(net, str) else str(net).lower()
            conn.execute(
                "INSERT OR IGNORE INTO main.network_membership VALUES (?, ?, ?)",
                [r.fid, net_slug, None],
            )

        for funder in d.get("funders") or []:
            fname = funder.get("name") if isinstance(funder, dict) else str(funder)
            if not fname:
                continue
            fuid = funder_id(fname)
            conn.execute(
                "INSERT OR IGNORE INTO main.funders VALUES (?, ?, NULL, NULL, NULL, NULL)",
                [fuid, fname],
            )
            conn.execute(
                "INSERT INTO main.funding_links VALUES (?, ?, NULL, NULL, NULL, ?, ?)",
                [
                    fuid,
                    r.fid,
                    (funder.get("relation") if isinstance(funder, dict) else None),
                    d.get("provenance", {}).get("source_url"),
                ],
            )

        prov = d.get("provenance") or {}
        conn.execute(
            "INSERT INTO main.provenance VALUES (?, ?, ?, ?, ?, ?)",
            [
                "facility",
                r.fid,
                prov.get("source_url"),
                prov.get("retrieved_at") or today.isoformat(),
                prov.get("confidence", "medium"),
                r.agent,
            ],
        )


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
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    records = load_raw_records()
    if not records:
        print("[info] no raw records found — creating empty schema only")
    assign_ids(records)
    records = dedup(records)
    geocode_missing(records, args.skip_geocode)

    with duckdb.connect(str(DB_PATH)) as conn:
        ensure_schema(conn)
        load_vocab(conn)
        insert_records(conn, records)
        log_run(conn, started, len(records), "success")

    print(f"[ok] wrote {len(records)} facilities to {DB_PATH}")

    # Rebuild the overlay-derived tables unless the caller opted out.
    if not args.skip_regions:
        try:
            # Import lazily so the ingest step doesn't require shapely
            # unless the user asks for the regions pass.
            from populate_regions import populate as populate_regions
            populate_regions(DB_PATH)
        except Exception as e:
            print(f"[warn] populate_regions failed ({e!r}); continuing")

    return 0


if __name__ == "__main__":
    sys.exit(main())
