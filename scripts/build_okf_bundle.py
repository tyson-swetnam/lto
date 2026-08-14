#!/usr/bin/env python3
"""Generate the OKF bundle: one concept doc per data archive.

Emits Open Knowledge Format v0.2 concept documents (see
github.com/GoogleCloudPlatform/knowledge-catalog, okf/SPEC.md) into
docs/okf/ — the bundle the Docs tab serves as "Data Access (OKF)":

  docs/okf/index.md            bundle root (okf_version frontmatter only)
  docs/okf/log.md              date-grouped update history
  docs/okf/archive-<slug>.md   one generated concept per data archive
  docs/okf/access-*.md         curated access-method guides (hand-written,
                               NOT touched by this script)

Reads ONLY public/parquet/ through an in-memory DuckDB connection, so it
is safe to run while a harvest holds the db/lto.duckdb write lock, and
every figure in the generated docs is re-derivable from committed
parquet — the repo's standing rule for documentation claims.

Idempotent: output depends only on the parquet inputs and the pinned
generator id; re-running on unchanged data rewrites identical files
(the `generated.at` stamp is derived from the newest input parquet's
mtime, not the wall clock, precisely so re-runs don't churn git).

Usage::

    python scripts/build_okf_bundle.py
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "public" / "parquet"
OUT = ROOT / "docs" / "okf"
GENERATOR = "claude-opus-5/lto-okf-generator"

# api_type → curated access guide (None: no guide; the URL stands alone).
GUIDE = {
    "erddap": "access-erddap.md",
    "thredds": "access-thredds.md",
    "dataone": "access-dataone.md",
    "ckan": "access-ckan.md",
    "oai-pmh": "access-ckan.md",
    "rest": "access-rest.md",
    "soap": "access-rest.md",
    "wms": "access-rest.md",
    "graphql": "access-rest.md",
}


def slugify(s: str) -> str:
    """Match src/views/docs.js slug rules: lowercase, runs of anything
    that is not [a-z0-9] collapse to '-'."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s).lower())).strip("-")


def yq(s) -> str:
    """YAML-quote a scalar."""
    if s is None:
        return '""'
    s = str(s).replace('"', "'")
    return f'"{s}"'


def esc_cell(s) -> str:
    """Escape a markdown table cell."""
    if s is None:
        return ""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def main() -> int:
    if not PARQUET.is_dir():
        print(f"[error] {PARQUET} not found", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect()

    def pq(name: str) -> str:
        return f"read_parquet('{PARQUET / name}.parquet')"

    # generated.at from input mtimes — see module docstring.
    inputs = ["data_archives", "api_endpoints", "cloud_buckets",
              "facility_archives", "data_products", "facilities"]
    stamp = dt.datetime.fromtimestamp(
        max((PARQUET / f"{t}.parquet").stat().st_mtime for t in inputs),
        tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    archives = conn.execute(f"""
        SELECT a.*,
               COALESCE(p.n_products, 0)  AS n_products,
               COALESCE(p.total_cites, 0) AS total_cites
        FROM {pq('data_archives')} a
        LEFT JOIN (
          SELECT archive_id,
                 CAST(COUNT(*) AS DOUBLE) AS n_products,
                 CAST(COALESCE(SUM(cited_by_count), 0) AS DOUBLE) AS total_cites
          FROM {pq('data_products')} WHERE archive_id IS NOT NULL
          GROUP BY archive_id
        ) p USING (archive_id)
        ORDER BY a.name
    """).fetchdf().to_dict("records")
    # fetchdf turns SQL NULL into float NaN, which is truthy and prints
    # as 'nan' — normalise every scalar back to None.
    archives = [
        {k: (None if (isinstance(v, float) and v != v) else v)
         for k, v in a.items()}
        for a in archives
    ]

    eps = {}
    for r in conn.execute(f"""
        SELECT archive_id, purpose, method, response_format, path_or_url,
               example_call
        FROM {pq('api_endpoints')} ORDER BY archive_id, purpose
    """).fetchall():
        eps.setdefault(r[0], []).append(r[1:])

    buckets = {}
    for r in conn.execute(f"""
        SELECT archive_id, provider, bucket_name, region, access_mode,
               documentation_url, sample_prefix
        FROM {pq('cloud_buckets')} ORDER BY archive_id, provider, bucket_name
    """).fetchall():
        buckets.setdefault(r[0], []).append(r[1:])

    facs = {}
    for r in conn.execute(f"""
        SELECT fa.archive_id, f.canonical_name, f.acronym, fa.role
        FROM {pq('facility_archives')} fa
        JOIN {pq('facilities')} f USING (facility_id)
        ORDER BY fa.archive_id,
                 CASE fa.role WHEN 'primary' THEN 0 WHEN 'host' THEN 1
                              WHEN 'secondary' THEN 2 ELSE 3 END,
                 f.canonical_name
    """).fetchall():
        facs.setdefault(r[0], []).append(r[1:])

    prods = {}
    for r in conn.execute(f"""
        SELECT archive_id, title, doi, url, format_slug,
               temporal_start, temporal_end, cited_by_count
        FROM (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY archive_id
            ORDER BY cited_by_count DESC NULLS LAST, title) AS rk
          FROM {pq('data_products')} WHERE archive_id IS NOT NULL
        ) WHERE rk <= 10
        ORDER BY archive_id, rk
    """).fetchall():
        prods.setdefault(r[0], []).append(r[1:])

    by_type: dict[str, list[tuple[str, str]]] = {}
    for a in archives:
        slug = f"archive-{slugify(a['archive_id'])}"
        by_type.setdefault(a["archive_type"] or "other", []).append(
            (a["name"], f"./{slug}.md"))
        api_type = a.get("api_type")
        guide = GUIDE.get(api_type)
        lines = [
            "---",
            'type: Data Archive',
            f"title: {yq(a['name'])}",
            f"description: {yq((a.get('organization') or 'Unattributed') + ' — ' + (a['archive_type'] or 'archive') + ' holding long-term observatory records.')}",
            f"resource: {yq(a.get('base_url'))}",
            f"tags: [{a['archive_type'] or 'archive'}"
            + (f", {api_type}" if api_type else "")
            + (f", {a['license_slug']}" if a.get("license_slug") else "") + "]",
            f"generated: {{ by: {yq(GENERATOR)}, at: {stamp} }}",
            "status: stable",
            "---",
            "",
        ]
        if a.get("notes"):
            lines += [str(a["notes"]).strip(), ""]

        lines.append("# Access")
        lines.append("")
        if a.get("base_url"):
            lines.append(f"- Archive home: <{a['base_url']}>")
        if a.get("api_url"):
            g = f" — see the [{api_type} guide](./{guide})" if guide else ""
            lines.append(f"- API root (`{api_type or 'api'}`): <{a['api_url']}>{g}")
        if a.get("api_doc_url"):
            lines.append(f"- API documentation: <{a['api_doc_url']}>")
        if a.get("doi_prefix"):
            lines.append(f"- DOIs minted here start with `{a['doi_prefix']}`")
        if not (a.get("api_url") or buckets.get(a["archive_id"])):
            lines.append("- No machine access recorded — landing page only.")
        lines.append("")

        if eps.get(a["archive_id"]):
            lines += ["# Documented calls", "",
                      "| Purpose | Method | Format | URL | Example |",
                      "|---|---|---|---|---|"]
            for purpose, method, fmt, url, example in eps[a["archive_id"]]:
                lines.append(
                    f"| {esc_cell(purpose)} | {esc_cell(method)} | {esc_cell(fmt)} "
                    f"| <{url}> | {esc_cell(example) or '—'} |")
            lines.append("")

        if buckets.get(a["archive_id"]):
            lines += ["# Cloud buckets", "",
                      "See the [cloud-bucket guide](./access-buckets.md) for "
                      "anonymous / requester-pays recipes.", "",
                      "| Provider | Bucket | Region | Access | Sample prefix |",
                      "|---|---|---|---|---|"]
            for provider, name, region, mode, docs, prefix in buckets[a["archive_id"]]:
                b = f"[{esc_cell(name)}]({docs})" if docs else esc_cell(name)
                lines.append(f"| {esc_cell(provider)} | {b} | {esc_cell(region)} "
                             f"| {esc_cell(mode)} | `{esc_cell(prefix) or '—'}` |")
            lines.append("")

        if facs.get(a["archive_id"]):
            lines += ["# Depositing facilities", ""]
            for name, acronym, role in facs[a["archive_id"]]:
                label = f"**{acronym}** {name}" if acronym and acronym != name else name
                lines.append(f"- {label} ({role})")
            lines.append("")

        if prods.get(a["archive_id"]):
            n = int(a["n_products"])
            cites = int(a["total_cites"])
            lines += ["# Data products", "",
                      f"{n} addressable product{'s' if n != 1 else ''} catalogued"
                      + (f", {cites:,} tracked citations" if cites else "")
                      + ". Top by citations:", "",
                      "| Product | Format | Coverage | Citations |",
                      "|---|---|---|---|"]
            for title, doi, url, fmt, t0, t1, cited in prods[a["archive_id"]]:
                href = (f"https://doi.org/{doi}" if doi and not str(doi).startswith("http")
                        else (doi or url))
                cell = f"[{esc_cell(title)}]({href})" if href else esc_cell(title)
                cov = f"{t0}–{t1 or 'present'}" if t0 else "—"
                lines.append(f"| {cell} | {esc_cell(fmt) or '—'} | {cov} "
                             f"| {int(cited) if cited is not None else 'n/a'} |")
            lines.append("")

        (OUT / f"{slug}.md").write_text("\n".join(lines))

    # Bundle root. Per spec §reserved-filenames, index.md carries no
    # frontmatter except okf_version at the bundle root.
    n_arch = len(archives)
    idx = [
        "---", 'okf_version: "0.2"', "---", "",
        "# LTO data access — OKF bundle", "",
        f"How to reach the data behind the catalogue: {n_arch} archives, "
        "each with a generated concept document listing its machine access "
        "points, depositing facilities, and addressable products. All "
        "figures are re-derivable from `public/parquet/` "
        "(`scripts/build_okf_bundle.py`); the access-method guides are "
        "curated by hand.", "",
        "## Access-method guides", "",
        "- [ERDDAP — griddap & tabledap](./access-erddap.md)",
        "- [THREDDS / OPeNDAP](./access-thredds.md)",
        "- [REST APIs](./access-rest.md)",
        "- [DataONE / EDI](./access-dataone.md)",
        "- [CKAN & OAI-PMH portals](./access-ckan.md)",
        "- [Cloud buckets (S3 / GCS / Azure)](./access-buckets.md)", "",
        "## Archives", "",
    ]
    for atype in sorted(by_type, key=lambda t: -len(by_type[t])):
        idx.append(f"### {atype} ({len(by_type[atype])})")
        idx.append("")
        for name, link in sorted(by_type[atype]):
            idx.append(f"- [{name}]({link})")
        idx.append("")
    (OUT / "index.md").write_text("\n".join(idx))

    # log.md — date-grouped history; append today's entry once per day.
    log = OUT / "log.md"
    today = dt.date.today().isoformat()
    entry = (f"## {today}\n\n- Regenerated {n_arch} archive concept docs "
             f"from public/parquet (generator {GENERATOR}).\n")
    if not log.exists():
        log.write_text("# Update log\n\n" + entry)
    elif f"## {today}" not in log.read_text():
        log.write_text(log.read_text().rstrip() + "\n\n" + entry)

    print(f"[ok] wrote {n_arch} archive concept docs + index + log -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
