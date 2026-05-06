#!/usr/bin/env python3
"""Load Wave-J data-archive JSON outputs into the LTO database.

Reads every `data/raw/J-*/<artifact>.json` produced by the Wave-J
research agents (per `agents/J-DATA.md`) and upserts into:

  data_archives        ←  archives.json
  facility_archives    ←  facility_archives.json
  data_products        ←  data_products.json
  api_endpoints        ←  api_endpoints.json
  cloud_buckets        ←  cloud_buckets.json

Idempotent on deterministic ID hashes so re-runs upsert.

Usage::

    python scripts/load_lto_archives.py
    python scripts/load_lto_archives.py --db db/cod_kmap.duckdb --verbose
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
RAW_DIR = ROOT / "data" / "raw"

DOI_RE = re.compile(r"^10\.\d{4,9}/[\w./()<>:;-]+$")


def sha16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def resolve_facility(conn, name: str | None, acronym: str | None) -> str | None:
    if not (name or acronym):
        return None
    if acronym:
        row = conn.execute(
            "SELECT facility_id FROM facilities WHERE upper(acronym) = upper(?) LIMIT 1",
            [acronym],
        ).fetchone()
        if row:
            return row[0]
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
    return None


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
    conn.execute(
        """
        INSERT OR REPLACE INTO data_archives
            (archive_id, name, organization, archive_type, base_url, api_url,
             api_doc_url, api_type, license_slug, doi_prefix, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            aid, a.get("name"), a.get("organization"), a.get("archive_type"),
            a.get("base_url"), a.get("api_url"), a.get("api_doc_url"),
            a.get("api_type"), a.get("license_slug"), a.get("doi_prefix"),
            (a.get("notes") or "") + (f" [via {agent}]" if agent else ""),
        ],
    )
    return True


def upsert_facility_archive(conn, agent: str, fa: dict) -> bool:
    fac_id = resolve_facility(conn, fa.get("facility_canonical_name"), fa.get("facility_acronym"))
    aid = (fa.get("archive_id") or "").strip().lower()
    if not (fac_id and aid):
        return False
    conn.execute(
        """
        INSERT OR REPLACE INTO facility_archives
            (facility_id, archive_id, role, scope_url, scope_id, sample_doi, notes)
        VALUES (?,?,?,?,?,?,?)
        """,
        [
            fac_id, aid,
            fa.get("role") or "primary",
            fa.get("scope_url"), fa.get("scope_id"),
            safe_doi(fa.get("sample_doi")),
            (fa.get("notes") or "") + (f" [via {agent}]" if agent else ""),
        ],
    )
    return True


def upsert_product(conn, agent: str, p: dict) -> bool:
    aid = (p.get("archive_id") or "").strip().lower() or None
    fac_id = resolve_facility(conn, p.get("facility_canonical_name"), p.get("facility_acronym"))
    title = p.get("title")
    if not title:
        return False
    doi = safe_doi(p.get("doi"))
    ident = p.get("identifier") or doi or title
    pid = sha16(f"{aid or ''}|{ident}")
    # DELETE-then-INSERT to honour the (publication_id) PK + (doi) uniqueness.
    if doi:
        conn.execute("DELETE FROM data_products WHERE doi = ?", [doi])
    conn.execute("DELETE FROM data_products WHERE product_id = ?", [pid])
    conn.execute(
        """
        INSERT INTO data_products
            (product_id, archive_id, facility_id, title, doi, identifier, url,
             format_slug, license_slug,
             temporal_start, temporal_end,
             bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat,
             variables_text, citation, cited_by_count,
             source, retrieved_at, confidence, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            pid, aid, fac_id, title, doi, p.get("identifier"), p.get("url"),
            p.get("format_slug"), p.get("license_slug"),
            p.get("temporal_start"), p.get("temporal_end"),
            p.get("bbox_min_lon"), p.get("bbox_min_lat"),
            p.get("bbox_max_lon"), p.get("bbox_max_lat"),
            p.get("variables_text"), p.get("citation"),
            p.get("cited_by_count"),
            agent or p.get("source"),
            p.get("retrieved_at") or "2026-05-05",
            p.get("confidence") or "medium",
            p.get("notes"),
        ],
    )
    return True


def upsert_endpoint(conn, agent: str, e: dict) -> bool:
    aid = (e.get("archive_id") or "").strip().lower() or None
    fac_id = resolve_facility(conn, e.get("facility_canonical_name"), e.get("facility_acronym"))
    path = e.get("path_or_url")
    if not path:
        return False
    eid = sha16(f"{aid or ''}|{path}")
    conn.execute(
        """
        INSERT OR REPLACE INTO api_endpoints
            (endpoint_id, archive_id, facility_id, path_or_url, method,
             purpose, response_format, schema_url, example_call, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        [
            eid, aid, fac_id, path,
            e.get("method") or "GET",
            e.get("purpose"), e.get("response_format"),
            e.get("schema_url"), e.get("example_call"),
            (e.get("notes") or "") + (f" [via {agent}]" if agent else ""),
        ],
    )
    return True


def upsert_bucket(conn, agent: str, b: dict) -> bool:
    aid = (b.get("archive_id") or "").strip().lower() or None
    fac_id = resolve_facility(conn, b.get("facility_canonical_name"), b.get("facility_acronym"))
    bname = (b.get("bucket_name") or "").strip()
    provider = (b.get("provider") or "s3").strip().lower()
    if not bname:
        return False
    bid = sha16(f"{provider}|{bname}|{b.get('region') or ''}")
    conn.execute(
        """
        INSERT OR REPLACE INTO cloud_buckets
            (bucket_id, archive_id, facility_id, provider, bucket_name,
             region, access_mode, documentation_url, sample_prefix, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        [
            bid, aid, fac_id, provider, bname,
            b.get("region"), b.get("access_mode") or "unknown",
            b.get("documentation_url"), b.get("sample_prefix"),
            (b.get("notes") or "") + (f" [via {agent}]" if agent else ""),
        ],
    )
    return True


HANDLERS = {
    "archives.json": upsert_archive,
    "facility_archives.json": upsert_facility_archive,
    "data_products.json": upsert_product,
    "api_endpoints.json": upsert_endpoint,
    "cloud_buckets.json": upsert_bucket,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    counts = {k: {"in": 0, "ok": 0, "skip": 0} for k in HANDLERS}
    warnings: list[str] = []

    # Load order matters: archives.json must finish across ALL folders
    # before any facility_archives / data_products / api_endpoints /
    # cloud_buckets row tries to FK-reference an archive_id. Iterate by
    # filename outer, folder inner.
    with duckdb.connect(str(args.db)) as conn:
        for fname, fn in HANDLERS.items():
            for d in sorted(RAW_DIR.glob("J-*")):
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
                    except duckdb.Error as e:
                        counts[fname]["skip"] += 1
                        warnings.append(f"  {agent}/{fname} insert error: {e}")

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
