#!/usr/bin/env python3
"""HTTP HEAD verification of every URL in the LTO database.

Runs in CI where the network is unrestricted (sandbox blocks every
external host). For each URL in:

  people.homepage_url
  facilities.url
  facilities.data_portal_url
  data_archives.base_url
  data_archives.api_url
  data_products.url
  cloud_buckets.documentation_url
  funding_events.source_url

…it does an HTTP HEAD (with GET fallback for hosts that block HEAD)
and records:

  url, status_code, final_url (after redirects), checked_at

…into `data/seed/url_health_check.csv`. The companion
`scripts/url_hygiene.py` reads this and NULLs / rewrites broken URLs
in the next ingest.

Usage (in CI)::

    pip install requests
    python scripts/check_url_health.py --concurrency 16 --timeout 8

Sandbox-mode dry-run (no requests, just enumerate URLs)::

    python scripts/check_url_health.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import duckdb

try:
    import requests
except ImportError:
    requests = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
OUT = ROOT / "data" / "seed" / "url_health_check.csv"

URL_SOURCES = [
    ("people", "person_id", "name", "homepage_url"),
    ("facilities", "facility_id", "canonical_name", "url"),
    ("facilities", "facility_id", "canonical_name", "data_portal_url"),
    ("data_archives", "archive_id", "name", "base_url"),
    ("data_archives", "archive_id", "name", "api_url"),
    ("data_archives", "archive_id", "name", "api_doc_url"),
    ("data_products", "product_id", "title", "url"),
    ("cloud_buckets", "bucket_id", "bucket_name", "documentation_url"),
    ("funding_events", "event_id", "award_title", "source_url"),
]


def collect_urls(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = []
    for table, id_col, name_col, url_col in URL_SOURCES:
        try:
            res = conn.execute(
                f"SELECT {id_col}, {name_col}, {url_col} FROM {table} "
                f"WHERE {url_col} IS NOT NULL AND length({url_col}) > 8"
            ).fetchall()
        except duckdb.Error:
            continue
        for r in res:
            rows.append({
                "table": table, "id": r[0], "name": r[1] or "",
                "field": url_col, "url": r[2],
            })
    return rows


def check_one(row: dict, timeout: int) -> dict:
    if requests is None:
        return {**row, "status_code": -1, "final_url": "", "error": "requests-not-installed"}
    headers = {"User-Agent": "lto-url-health-check/1.0 (+https://github.com/tyson-swetnam/lto)"}
    try:
        r = requests.head(row["url"], allow_redirects=True, timeout=timeout, headers=headers)
        if r.status_code in (405, 403):
            # Some hosts (e.g. NSF, NASA Earthdata) block HEAD; retry with
            # a Range-limited GET to avoid downloading the body.
            r = requests.get(row["url"], allow_redirects=True, timeout=timeout,
                             headers={**headers, "Range": "bytes=0-1023"})
        return {
            **row,
            "status_code": r.status_code,
            "final_url": r.url,
            "error": "",
        }
    except requests.exceptions.Timeout:
        return {**row, "status_code": -2, "final_url": "", "error": "timeout"}
    except requests.exceptions.ConnectionError as e:
        return {**row, "status_code": -3, "final_url": "", "error": f"conn:{type(e).__name__}"}
    except Exception as e:
        return {**row, "status_code": -9, "final_url": "", "error": f"{type(e).__name__}:{e}"[:120]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with duckdb.connect(str(args.db), read_only=True) as conn:
        urls = collect_urls(conn)
    print(f"[check_url_health] collected {len(urls)} URLs across {len(URL_SOURCES)} fields")

    if args.dry_run or requests is None:
        if requests is None:
            print("[check_url_health] requests not installed — dry-run only")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "table", "id", "name", "field", "url",
                "status_code", "final_url", "error", "checked_at",
            ])
            w.writeheader()
            for row in urls:
                w.writerow({**row, "status_code": -1, "final_url": "",
                            "error": "dry-run", "checked_at": date.today().isoformat()})
        print(f"[check_url_health] wrote {len(urls)} dry-run rows → {OUT.relative_to(ROOT)}")
        return 0

    results = []
    today = date.today().isoformat()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(check_one, r, args.timeout) for r in urls]
        for i, fut in enumerate(as_completed(futures)):
            res = fut.result()
            res["checked_at"] = today
            results.append(res)
            if (i + 1) % 50 == 0:
                print(f"  …{i+1}/{len(urls)} checked")

    # Tally
    from collections import Counter
    code_counts = Counter(r["status_code"] for r in results)
    print("[check_url_health] status code breakdown:")
    for code, n in sorted(code_counts.items()):
        print(f"  {code}: {n}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "table", "id", "name", "field", "url",
            "status_code", "final_url", "error", "checked_at",
        ])
        w.writeheader()
        for row in results:
            w.writerow(row)
    print(f"[check_url_health] wrote {len(results)} rows → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
