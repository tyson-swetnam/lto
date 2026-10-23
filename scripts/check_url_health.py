#!/usr/bin/env python3
"""HTTP HEAD verification of every URL in the LTO lake.

Runs in CI where the network is unrestricted (sandbox blocks every
external host). For each URL in:

  people.homepage_url
  facilities.url
  facilities.data_portal_url
  data_archives.base_url
  data_archives.api_url
  data_archives.api_doc_url
  data_products.url
  api_endpoints.path_or_url
  cloud_buckets.documentation_url
  funding_events.source_url

…it does an HTTP HEAD (with GET fallback for hosts that block HEAD)
and records:

  url, status_code, final_url (after redirects), checked_at

plus a coarse `status` label and bare `http_code` — into
`data/seed/url_health_check.csv` (full audit columns) AND the lake's
`url_health` table (url, status, http_code, checked_at only — the table
src/views/datasets.js joins to paint the endpoint health dots on the
Data tab). export_parquet.py publishes that table as
public/parquet/url_health.parquet; this script no longer writes
public/parquet itself.

Endpoint templates with `{PLACEHOLDER}` segments (AmeriFlux's
`{SITE_ID}`, ARM's `{YYYY-MM-DD}`, …) are never requested — a literal
GET of the template is guaranteed 4xx and would smear red over rows
that are perfectly healthy once substituted. They record as
`template-skipped` with no http_code.

The table is replaced in one lake snapshot (commit message
``check_url_health: …``) after the sweep. URL collection prefers the
lake (CI runs this right after rebuild_lake_from_parquet.py) but falls
back to reading public/parquet/ directly when the lake cannot be opened;
force that path with --from-parquet. A real run still needs the lake to
write into, and checks for it before sending any request.

Usage (in CI)::

    pip install requests
    python scripts/check_url_health.py --concurrency 16 --timeout 8

Sandbox-mode dry-run (no requests, just enumerate URLs)::

    python scripts/check_url_health.py --dry-run [--from-parquet]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

try:
    import requests
except ImportError:
    requests = None

ROOT = Path(__file__).resolve().parent.parent
PARQUET_DIR = ROOT / "public" / "parquet"
OUT = ROOT / "data" / "seed" / "url_health_check.csv"

URL_SOURCES = [
    ("people", "person_id", "name", "homepage_url"),
    ("facilities", "facility_id", "canonical_name", "url"),
    ("facilities", "facility_id", "canonical_name", "data_portal_url"),
    ("data_archives", "archive_id", "name", "base_url"),
    ("data_archives", "archive_id", "name", "api_url"),
    ("data_archives", "archive_id", "name", "api_doc_url"),
    ("data_products", "product_id", "title", "url"),
    ("api_endpoints", "endpoint_id", "purpose", "path_or_url"),
    ("cloud_buckets", "bucket_id", "bucket_name", "documentation_url"),
    ("funding_events", "event_id", "award_title", "source_url"),
]

CSV_FIELDS = [
    "table", "id", "name", "field", "url",
    "status", "http_code", "status_code", "final_url", "error", "checked_at",
]

# {SITE_ID}, {YYYY-MM-DD}, {USER}:{TOKEN}… — endpoint templates, not
# fetchable URLs. Anything matching this is classified template-skipped.
TEMPLATE_RE = re.compile(r"\{[^}]*\}")


def status_label(status_code: int | None) -> str:
    """Coarse verdict the frontend keys its health dots on.

    Sentinel codes (<100) come from check_one below: -1 dry-run /
    requests missing, -2 timeout, -3 connection failure, -9 anything
    else (SSL, malformed URL, redirect loop).
    """
    if status_code is None:
        return "template-skipped"
    if 200 <= status_code < 300:
        return "ok"
    if 300 <= status_code < 400:
        return "redirect"
    if 400 <= status_code < 500:
        return "client-error"
    if status_code >= 500:
        return "server-error"
    if status_code in (-2, -3):
        return "timeout"
    if status_code == -1:
        return "unchecked"
    return "server-error"


def http_code(status_code: int | None) -> int | None:
    """Real HTTP code, or None for sentinels / skipped templates."""
    return status_code if status_code is not None and status_code >= 100 else None


def collect_urls(conn: duckdb.DuckDBPyConnection,
                 rel_for=lambda table: table) -> list[dict]:
    """Enumerate every checkable URL.

    `rel_for` maps a logical table name to a FROM-clause relation —
    the bare table name against the lake, a read_parquet() call against
    public/parquet/ (see collect_from_parquet).
    """
    rows = []
    for table, id_col, name_col, url_col in URL_SOURCES:
        try:
            res = conn.execute(
                f"SELECT {id_col}, {name_col}, {url_col} FROM {rel_for(table)} "
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


def collect_from_parquet() -> list[dict]:
    """URL collection without the lake — read public/parquet/ directly.

    Used when the lake hasn't been built in this checkout (the parquet
    files, not the lake, are the committed artifact).
    """
    with duckdb.connect() as conn:  # in-memory
        return collect_urls(
            conn,
            rel_for=lambda t: f"read_parquet('{(PARQUET_DIR / t).as_posix()}.parquet')",
        )


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


def finalise(row: dict, checked_at: str) -> dict:
    """Attach the derived status/http_code/checked_at columns."""
    code = row.get("status_code")
    return {
        **row,
        "status": status_label(code),
        "http_code": http_code(code),
        "checked_at": checked_at,
    }


def write_csv(rows: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"[check_url_health] wrote {len(rows)} rows → {OUT.relative_to(ROOT)}")


def write_lake(rows: list[dict], catalog: Path | None = None,
               data: Path | None = None) -> None:
    """Per-URL verdicts → the lake's url_health table (one snapshot).

    One row per distinct URL (the same URL can appear under several
    table/field pairs — base_url doubling as api_url is common); a real
    check beats a template-skipped/unchecked duplicate. url_health is a
    derived table (not in schema.sql), so it is replaced wholesale.
    """
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["url"])
        if cur is None or (cur.get("http_code") is None and r.get("http_code") is not None):
            best[r["url"]] = r
    with lto_db.connect(catalog=catalog, data=data) as conn:
        with lto_db.transaction(conn, f"check_url_health: url_health, "
                                      f"{len(best)} URLs checked"):
            conn.execute(
                "CREATE OR REPLACE TEMP TABLE _url_health "
                "(url VARCHAR, status VARCHAR, http_code INTEGER, checked_at VARCHAR)")
            if best:
                conn.executemany(
                    "INSERT INTO _url_health VALUES (?, ?, ?, ?)",
                    [(r["url"], r["status"], r["http_code"], r["checked_at"])
                     for r in best.values()])
            n = lto_db.replace_table(conn, "url_health", "SELECT * FROM _url_health")
            conn.execute("DROP TABLE _url_health")
    print(f"[check_url_health] wrote {n} URLs → lake url_health "
          "(run export_parquet.py to publish)")


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-parquet", action="store_true",
                    help="collect URLs from public/parquet/ instead of the lake "
                         "(automatic when the lake is absent)")
    args = ap.parse_args()

    if not (args.dry_run or requests is None):
        # The sweep takes minutes; fail before it if there is nowhere to
        # write the result.
        cat = lto_db.catalog_path(args.catalog)
        if not cat.exists():
            raise lto_db.LakeNotFound(
                f"DuckLake catalog not found: {cat}\n"
                f"  Build it first:  python scripts/rebuild_lake_from_parquet.py")

    if args.from_parquet:
        urls = collect_from_parquet()
    else:
        try:
            with lto_db.connect(read_only=True, catalog=args.catalog,
                                data=args.lake_data) as conn:
                urls = collect_urls(conn)
        except (lto_db.LakeNotFound, duckdb.Error) as e:
            print(f"[check_url_health] cannot open the lake "
                  f"({type(e).__name__}: {e}) — falling back to public/parquet/")
            urls = collect_from_parquet()
    print(f"[check_url_health] collected {len(urls)} URLs across {len(URL_SOURCES)} fields")

    today = date.today().isoformat()
    templated = [u for u in urls if TEMPLATE_RE.search(u["url"])]
    checkable = [u for u in urls if not TEMPLATE_RE.search(u["url"])]
    if templated:
        print(f"[check_url_health] {len(templated)} template URLs "
              f"({{PLACEHOLDER}} segments) marked template-skipped, not requested")
    skipped_rows = [
        finalise({**u, "status_code": None, "final_url": "", "error": "template-skipped"},
                 today)
        for u in templated
    ]

    if args.dry_run or requests is None:
        if requests is None:
            print("[check_url_health] requests not installed — dry-run only")
        rows = skipped_rows + [
            finalise({**u, "status_code": -1, "final_url": "", "error": "dry-run"}, today)
            for u in checkable
        ]
        # CSV only: a dry-run must not clobber the url_health table (and
        # so the shipped url_health.parquet) with all-'unchecked' rows.
        write_csv(rows)
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(check_one, r, args.timeout) for r in checkable]
        for i, fut in enumerate(as_completed(futures)):
            results.append(finalise(fut.result(), today))
            if (i + 1) % 50 == 0:
                print(f"  …{i+1}/{len(checkable)} checked")
    results.extend(skipped_rows)

    # Tally
    from collections import Counter
    status_counts = Counter(r["status"] for r in results)
    print("[check_url_health] status breakdown:")
    for status, n in sorted(status_counts.items()):
        print(f"  {status}: {n}")

    write_csv(results)
    write_lake(results, args.catalog, args.lake_data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
