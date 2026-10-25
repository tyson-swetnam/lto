#!/usr/bin/env python3
"""Load Wave-J data-archive JSON outputs into the LTO database.

Reads every `data/raw/J-*/<artifact>.json` produced by the Wave-J
research agents (per `agents/J-DATA.md`) — and by fetch scripts that
write the same shapes, such as `scripts/fetch_envirodata_nm.py` — and
upserts into:

  data_archives        ←  archives.json
  facility_archives    ←  facility_archives.json
  data_products        ←  data_products.json
  api_endpoints        ←  api_endpoints.json
  cloud_buckets        ←  cloud_buckets.json

Idempotent on deterministic ID hashes so re-runs upsert. One run is one
DuckLake snapshot (scripts/lto_db.py). The lake does not check foreign
keys, so each row is checked before it is written (row_error below); a
row that fails is skipped and counted, as before.

Usage::

    python scripts/load_lto_archives.py
    python scripts/load_lto_archives.py --catalog db/lto_catalog.sqlite --verbose
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

DOI_RE = re.compile(r"^10\.\d{4,9}/[\w./()<>:;-]+$")


def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def resolve_facility(conn, name: str | None, acronym: str | None,
                     facility_id: str | None = None) -> str | None:
    # An explicit facility_id pins the link: it is used when that facility
    # exists and the record is skipped when it does not. There is no name or
    # fuzzy fallback, because a fuzzy hit would silently move the link to a
    # different facility (a "Connecticut National Estuarine Research Reserve"
    # record against a lake without that row resolved to Wells NERR at
    # token_set_ratio >= 85 and overwrote its CDMO scope_id).
    if facility_id:
        row = conn.execute(
            "SELECT facility_id FROM facilities WHERE facility_id = ? LIMIT 1",
            [facility_id.strip()],
        ).fetchone()
        return row[0] if row else None
    if not (name or acronym):
        return None
    # If both name and acronym are provided, try the most specific match first:
    # exact name, then name+acronym join, then name ILIKE, then acronym alone.
    # cod-kmap heritage data assigned generic acronyms (acronym="NERR" for all
    # the reserves, until data/seed/facility_fixes.csv gave each its own or
    # NULL), so resolving by a shared acronym alone can collapse
    # distinct facilities to a single row — we fall back to acronym only when
    # no name is provided.
    if name:
        row = conn.execute(
            "SELECT facility_id FROM facilities WHERE lower(canonical_name) = lower(?) LIMIT 1",
            [name],
        ).fetchone()
        if row:
            return row[0]
        rows = conn.execute(
            "SELECT facility_id FROM facilities WHERE canonical_name ILIKE ? LIMIT 2",
            [f"%{name}%"],
        ).fetchall()
        if len(rows) == 1:
            return rows[0][0]
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            return None
        cands = conn.execute("SELECT facility_id, canonical_name FROM facilities").fetchall()
        nm_to_row = {c[1]: c for c in cands}
        best = process.extractOne(
            name, list(nm_to_row.keys()),
            scorer=fuzz.token_set_ratio, score_cutoff=85,
        )
        if best:
            return nm_to_row[best[0]][0]
    # No name provided — fall back to acronym alone. Only safe when the
    # acronym is unique (skip obviously-generic ones).
    GENERIC = {"NERR", "NEP", "NMS", "NWR", "LTER", "LTREB", "LTAR", "EFR",
               "BR", "MAB", "NPS", "USGS", "USFS", "NWRS", "RNA"}
    if acronym and acronym.upper() not in GENERIC:
        row = conn.execute(
            "SELECT facility_id FROM facilities WHERE upper(acronym) = upper(?) LIMIT 1",
            [acronym],
        ).fetchone()
        if row:
            return row[0]
    return None


# ── row gate ─────────────────────────────────────────────────────────────
# DuckDB used to reject a bad row (an unknown vocab slug, a NULL title, a
# date that does not parse) at INSERT, and each handler's caller skipped
# it. The lake checks NOT NULL and types but no keys, and inside
# lto_db.transaction() any failed statement aborts the whole run. So each
# row is tried first against an empty in-memory copy of its table (types,
# NOT NULL) and its foreign keys are looked up in the lake.
# (Local to this script; a candidate for lto_db.)
_probe: duckdb.DuckDBPyConnection | None = None


def row_error(conn, table: str, row: dict, fks: bool = True) -> str | None:
    """Why `row` could not be written to `table`, or None if it can.
    fks=False skips the foreign-key lookups (the caller checks them)."""
    global _probe
    if _probe is None:
        _probe = duckdb.connect()
    if not lto_db.table_exists(_probe, table, catalog="memory"):
        _probe.execute(lto_db.column_only_ddl(table))
    cols = ", ".join(lto_db.qident(c) for c in row)
    _probe.execute("BEGIN")
    try:
        _probe.execute(f"INSERT INTO {lto_db.qident(table)} ({cols}) "
                       f"VALUES ({', '.join('?' * len(row))})", list(row.values()))
    except duckdb.Error as e:
        return str(e).splitlines()[0]
    finally:
        _probe.execute("ROLLBACK")
    for d in lto_db.spec()["constraints"] if fks else []:
        if d["table"] != table or d["kind"] != "FOREIGN KEY":
            continue
        vals = [row.get(c) for c in d["columns"]]
        if any(v is None for v in vals):
            continue
        on = " AND ".join(f"{lto_db.qident(c)} = ?" for c in d["ref_columns"])
        if not lto_db.rows(conn, f"SELECT 1 FROM {lto_db.qident(d['ref_table'])} "
                                 f"WHERE {on} LIMIT 1", vals):
            return (f"foreign key {d['columns']} -> {d['ref_table']}: "
                    f"{vals} does not exist")
    return None


def cast_error(table: str, col: str, value) -> str | None:
    """Why `value` could not be stored in `table`.`col` (an UPDATE's
    check; the probe row of row_error() would trip other NOT NULLs)."""
    global _probe
    if _probe is None:
        _probe = duckdb.connect()
    try:
        _probe.execute(f"SELECT CAST(? AS {_coltype(table, col)})", [value]).fetchall()
    except duckdb.Error as e:
        return str(e).splitlines()[0]
    return None


class RowRejected(Exception):
    """A row failed row_error(); main() counts it as skipped."""


def write_row(conn, table: str, row: dict, key: list[str] | None = None,
              insert_only: bool = False, checked: bool = False) -> None:
    """Check `row` (unless the caller already has), then write it: merge on
    `key` (INSERT OR REPLACE, or INSERT OR IGNORE with insert_only), or a
    plain INSERT without one."""
    err = None if checked else row_error(conn, table, row)
    if err:
        raise RowRejected(err)
    if key is None:
        conn.execute(f"INSERT INTO {lto_db.qident(table)} "
                     f"({', '.join(lto_db.qident(c) for c in row)}) "
                     f"VALUES ({', '.join('?' * len(row))})", list(row.values()))
        return
    lto_db.merge_upsert(
        conn, table, key,
        "SELECT " + ", ".join(f"?::{_coltype(table, c)} AS {lto_db.qident(c)}" for c in row),
        params=list(row.values()), insert_only=insert_only)


def _coltype(table: str, col: str) -> str:
    for name, typ, _nullable, _default in lto_db.spec()["columns"][table]:
        if name == col:
            return typ
    raise KeyError(f"{table}.{col}")


def safe_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    return doi if DOI_RE.match(doi) else None


def upsert_archive(conn, agent: str, a: dict) -> bool:
    aid = a.get("archive_id")
    if not aid:
        return False
    aid = aid.strip().lower()
    write_row(conn, "data_archives", {
        "archive_id": aid, "name": a.get("name"), "organization": a.get("organization"),
        "archive_type": a.get("archive_type"), "base_url": a.get("base_url"),
        "api_url": a.get("api_url"), "api_doc_url": a.get("api_doc_url"),
        "api_type": a.get("api_type"), "license_slug": a.get("license_slug"),
        "doi_prefix": a.get("doi_prefix"),
        "notes": (a.get("notes") or "") + (f" [via {agent}]" if agent else ""),
    }, key=["archive_id"], insert_only=True)
    return True


def upsert_facility_archive(conn, agent: str, fa: dict) -> bool:
    fac_id = resolve_facility(conn, fa.get("facility_canonical_name"), fa.get("facility_acronym"),
                              fa.get("facility_id"))
    aid = (fa.get("archive_id") or "").strip().lower()
    if not (fac_id and aid):
        return False
    write_row(conn, "facility_archives", {
        "facility_id": fac_id, "archive_id": aid,
        "role": fa.get("role") or "primary",
        "scope_url": fa.get("scope_url"), "scope_id": fa.get("scope_id"),
        "sample_doi": safe_doi(fa.get("sample_doi")),
        "notes": (fa.get("notes") or "") + (f" [via {agent}]" if agent else ""),
    }, key=["facility_id", "archive_id"])
    return True


def upsert_product(conn, agent: str, p: dict) -> bool:
    aid = (p.get("archive_id") or "").strip().lower() or None
    fac_id = resolve_facility(conn, p.get("facility_canonical_name"), p.get("facility_acronym"),
                              p.get("facility_id"))
    title = p.get("title")
    if not title:
        return False
    doi = safe_doi(p.get("doi"))
    ident = p.get("identifier") or doi or title
    pid = sha16(f"{aid or ''}|{ident}")
    row = {
        "product_id": pid, "archive_id": aid, "facility_id": fac_id, "title": title,
        "doi": doi, "identifier": p.get("identifier"), "url": p.get("url"),
        "format_slug": p.get("format_slug"), "license_slug": p.get("license_slug"),
        "temporal_start": p.get("temporal_start"), "temporal_end": p.get("temporal_end"),
        "bbox_min_lon": p.get("bbox_min_lon"), "bbox_min_lat": p.get("bbox_min_lat"),
        "bbox_max_lon": p.get("bbox_max_lon"), "bbox_max_lat": p.get("bbox_max_lat"),
        "variables_text": p.get("variables_text"), "citation": p.get("citation"),
        "cited_by_count": p.get("cited_by_count"),
        "source": agent or p.get("source"),
        "retrieved_at": p.get("retrieved_at") or "2026-05-05",
        "confidence": p.get("confidence") or "medium",
        "notes": p.get("notes"),
        "description": p.get("description"), "category": p.get("category"),
        "api_url": p.get("api_url"),
    }
    err = row_error(conn, "data_products", row)
    if err:
        raise RowRejected(err)
    # DELETE-then-INSERT to honour the (product_id) PK + (doi) uniqueness.
    # The row being replaced keeps its created_at (its own id first, else
    # the DOI holder's), so re-running on unchanged inputs changes nothing
    # and the weekly refresh does not open a timestamp-only diff.
    prev = lto_db.rows(conn, "SELECT created_at FROM data_products "
                             "WHERE product_id = ? OR (doi = ? AND ? IS NOT NULL) "
                             "ORDER BY product_id = ? DESC LIMIT 1", [pid, doi, doi, pid])
    if prev and prev[0][0] is not None:
        row["created_at"] = prev[0][0]
    if doi:
        conn.execute("DELETE FROM data_products WHERE doi = ?", [doi])
    conn.execute("DELETE FROM data_products WHERE product_id = ?", [pid])
    write_row(conn, "data_products", row, checked=True)
    return True


def upsert_endpoint(conn, agent: str, e: dict) -> bool:
    aid = (e.get("archive_id") or "").strip().lower() or None
    fac_id = resolve_facility(conn, e.get("facility_canonical_name"), e.get("facility_acronym"),
                              e.get("facility_id"))
    path = e.get("path_or_url")
    if not path:
        return False
    eid = sha16(f"{aid or ''}|{path}")
    write_row(conn, "api_endpoints", {
        "endpoint_id": eid, "archive_id": aid, "facility_id": fac_id,
        "path_or_url": path, "method": e.get("method") or "GET",
        "purpose": e.get("purpose"), "response_format": e.get("response_format"),
        "schema_url": e.get("schema_url"), "example_call": e.get("example_call"),
        "notes": (e.get("notes") or "") + (f" [via {agent}]" if agent else ""),
    }, key=["endpoint_id"])
    return True


def upsert_bucket(conn, agent: str, b: dict) -> bool:
    aid = (b.get("archive_id") or "").strip().lower() or None
    fac_id = resolve_facility(conn, b.get("facility_canonical_name"), b.get("facility_acronym"),
                              b.get("facility_id"))
    bname = (b.get("bucket_name") or "").strip()
    provider = (b.get("provider") or "s3").strip().lower()
    if not bname:
        return False
    bid = sha16(f"{provider}|{bname}|{b.get('region') or ''}")
    write_row(conn, "cloud_buckets", {
        "bucket_id": bid, "archive_id": aid, "facility_id": fac_id,
        "provider": provider, "bucket_name": bname, "region": b.get("region"),
        "access_mode": b.get("access_mode") or "unknown",
        "documentation_url": b.get("documentation_url"),
        "sample_prefix": b.get("sample_prefix"),
        "notes": (b.get("notes") or "") + (f" [via {agent}]" if agent else ""),
    }, key=["bucket_id"])
    return True


VOCAB_DIR = ROOT / "schema" / "vocab"
VOCAB_TABLES = ("archive_types", "data_formats", "data_licenses", "access_modes")


def sync_vocab(conn) -> None:
    """Add vocab rows the CSVs have gained since the DB's parquet was written.

    A database rebuilt from parquet carries the vocab as it was at the
    last export, so a slug added to schema/vocab/ for a new agent would
    otherwise fail the foreign key on its first load.
    """
    for table in VOCAB_TABLES:
        csv_path = VOCAB_DIR / f"{table}.csv"
        if csv_path.exists():
            lto_db.merge_upsert(
                conn, table, ["slug"],
                "SELECT * FROM read_csv_auto(?, header=True, all_varchar=True)",
                params=[str(csv_path)], insert_only=True,
            )


HANDLERS = {
    "archives.json": upsert_archive,
    "facility_archives.json": upsert_facility_archive,
    "data_products.json": upsert_product,
    "api_endpoints.json": upsert_endpoint,
    "cloud_buckets.json": upsert_bucket,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path, help="deprecated alias of --catalog")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    counts = {k: {"in": 0, "ok": 0, "skip": 0} for k in HANDLERS}
    warnings: list[str] = []

    # Load order matters: archives.json must finish across ALL folders
    # before any facility_archives / data_products / api_endpoints /
    # cloud_buckets row tries to FK-reference an archive_id. Iterate by
    # filename outer, folder inner.
    agents = sorted({d.name for d in RAW_DIR.glob("[JKMO]-*")})
    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    with lto_db.transaction(conn, f"load_lto_archives: Wave-J archives + products from "
                                  f"{', '.join(agents) or 'no agent dirs'}"):
        sync_vocab(conn)
        for fname, fn in HANDLERS.items():
            for d in sorted(set(
                    list(RAW_DIR.glob("J-*")) +
                    list(RAW_DIR.glob("K-*")) +
                    list(RAW_DIR.glob("M-*")) +
                    list(RAW_DIR.glob("O-*"))
            )):
                agent = d.name
                p = d / fname
                if not p.exists():
                    continue
                try:
                    rows = json.loads(p.read_text())
                except json.JSONDecodeError as e:
                    print(f"[skip] {p}: {e}", file=sys.stderr)
                    continue
                if not isinstance(rows, list):
                    print(f"[skip] {p}: not a JSON array", file=sys.stderr)
                    continue
                for r in rows:
                    counts[fname]["in"] += 1
                    try:
                        if fn(conn, agent, r):
                            counts[fname]["ok"] += 1
                        else:
                            counts[fname]["skip"] += 1
                            warnings.append(f"  {agent}/{fname}: skipped {str(r)[:80]}")
                    except RowRejected as e:
                        counts[fname]["skip"] += 1
                        warnings.append(f"  {agent}/{fname} insert error: {e}")
        lto_db.assert_integrity(conn, ["archive_types", "data_formats", "data_licenses",
                                       "access_modes", "data_archives", "facility_archives",
                                       "data_products", "api_endpoints", "cloud_buckets"])
    conn.close()

    print("[load_lto_archives] summary")
    for k, v in counts.items():
        print(f"  {k:24s}  read {v['in']:4d}  ok {v['ok']:4d}  skipped {v['skip']:4d}")
    if args.verbose and warnings:
        for w in warnings[:30]:
            print(w)
        if len(warnings) > 30:
            print(f"  … {len(warnings)-30} more suppressed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
