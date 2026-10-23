#!/usr/bin/env python3
"""Publish the LTO data artifacts to the MESA project on the CyVerse Data Store.

Target collection:  /iplant/home/tswetnam/lto   (enrolled MESA project;
its ``.mesa/ducklake/`` history is maintained server-side from AVU writes).

What a publish is
-----------------
1.  **Preflight** — the set of parquet files in ``public/parquet/`` must
    exactly match the ``TABLES`` list in ``scripts/export_parquet.py``.
    ``export_parquet.py`` *fails soft* (a missing table is skipped and the
    stale parquet stays on disk), so this check is what turns "the export
    said ok" into "the export actually covered every table".
2.  **Local DuckLake snapshot** (optional, ``--skip-lake`` or automatic
    fallback) — loads every table into ``db/lto_lake.ducklake`` so data
    history is queryable locally::

        ATTACH 'ducklake:db/lto_lake.ducklake' AS lake (DATA_PATH 'db/ducklake_data/');
        SELECT * FROM lake.snapshots();

    Catalogue + data dir are gitignored; losing them costs nothing (the
    committed parquet is canonical). If the ducklake extension can't load
    the publish continues — a fallback run is not a degraded run.
3.  **Stage** — copies parquet/, facilities.geojson, public/cache/*.json,
    schema/vocab/* (+ data/vocab_crosswalk/*.csv if present), docs/*.md
    into ``.mesa_publish/`` and writes ``MANIFEST.json`` (per-file sha256 +
    bytes, git commit, branch, UTC timestamp, table count, lake snapshot)
    and ``TABLES.json`` (per table: description, kind, generating script,
    row count, columns — from ``schema/table_descriptions.csv`` and the
    parquet itself). The staging dir contains no ``.git`` by construction
    — the CSI/FUSE mount must never see git metadata.
4.  **Upload** — ``gocmd sync .mesa_publish i:/iplant/home/tswetnam/lto
    --no_root`` (differential: unchanged files are skipped, so re-runs are
    idempotent). ``--freeze`` additionally uploads a frozen copy to
    ``snapshots/<YYYYMMDD>-<shortsha>/``.
5.  **Stamp** — writes ``.mesa_publish_avus.json``: the ``lto.publish.*``
    set for the collection root and an ``lto.table.*`` set for every
    parquet file. A Python script cannot call MCP tools; the operator
    (usually Claude) applies each set with one batched ``ds_add_avus``
    call, which mesa-mcp mirrors into ``.mesa/ducklake/`` as one snapshot.

AVU rules this script follows
-----------------------------
* **iRODS adds, it never replaces.** Writing a new ``lto.publish.commit``
  leaves the old one in place. Before stamping, delete the previous
  ``lto.publish.*`` values from the root (``ds_delete_avu``), or they
  pile up; six publishes once left six sets.
* **Table AVUs hold only what does not change between publishes** —
  name, description, kind, generator, column names. Re-applying an
  unchanged value is a no-op. Row counts and checksums change on every
  publish, so they live in ``TABLES.json`` and ``MANIFEST.json`` instead
  of becoming stale duplicate AVUs. When a description or column list
  does change, delete the old value on that file first.
* **Keep AVU values short.** Writes with values near 900 characters lost
  their server response through mesa-mcp (the write landed, the DuckLake
  mirror did not). Column lists are capped at ``AVU_VALUE_MAX``.
* **History needs the catalog.** mesa-mcp mirrors AVU writes only for a
  project registered in its DuckLake catalog. That catalog is a local
  file per machine (``~/.mesa/ducklake/catalog.duckdb``): on a new
  machine run ``mesa_ducklake_init_project`` once (idempotent) first.

Usage::

    python scripts/publish_to_mesa.py --dry-run
    python scripts/publish_to_mesa.py
    python scripts/publish_to_mesa.py --freeze      # milestone (merge-to-main)
    python scripts/publish_to_mesa.py --skip-lake
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARQUET_DIR = ROOT / "public" / "parquet"
GEOJSON = ROOT / "public" / "facilities.geojson"
CACHE_DIR = ROOT / "public" / "cache"
VOCAB_DIR = ROOT / "schema" / "vocab"
CROSSWALK_DIR = ROOT / "data" / "vocab_crosswalk"
DOCS_DIR = ROOT / "docs"
LAKE_CATALOG = ROOT / "db" / "lto_lake.ducklake"
LAKE_DATA = ROOT / "db" / "ducklake_data"
IRODS_DEST = "i:/iplant/home/tswetnam/lto"
TABLE_DESCRIPTIONS = ROOT / "schema" / "table_descriptions.csv"
AVU_PLAN = ROOT / ".mesa_publish_avus.json"
AVU_VALUE_MAX = 400


def sh(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def export_tables_list() -> list[str]:
    """Parse the TABLES list out of export_parquet.py (single source of truth)."""
    import ast

    tree = ast.parse((ROOT / "scripts" / "export_parquet.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TABLES":
                    return [ast.literal_eval(el) for el in node.value.elts]
    raise RuntimeError("TABLES list not found in scripts/export_parquet.py")


def table_descriptions() -> dict[str, dict]:
    import csv

    with TABLE_DESCRIPTIONS.open(newline="") as fh:
        return {r["table"]: r for r in csv.DictReader(fh)}


def table_catalog(tables: list[str]) -> dict[str, dict]:
    """Per-table facts for TABLES.json: curated text + what the parquet says."""
    import duckdb

    desc = table_descriptions()
    conn = duckdb.connect()
    out = {}
    for t in tables:
        f = PARQUET_DIR / f"{t}.parquet"
        cols = [r[0] for r in conn.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{f}')").fetchall()]
        rows = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{f}')").fetchone()[0]
        out[t] = {
            "description": desc[t]["description"],
            "kind": desc[t]["kind"],
            "generator": desc[t]["generator"],
            "rows": rows,
            "columns": cols,
        }
    return out


def capped(value: str) -> str:
    if len(value) <= AVU_VALUE_MAX:
        return value
    return value[:AVU_VALUE_MAX].rsplit(",", 1)[0] + ", …"


def avu_plan(manifest: dict, catalog: dict[str, dict], manifest_sha: str) -> dict:
    """What the operator applies with ds_add_avus, one call per target."""
    root = IRODS_DEST[2:]
    plan = {
        "note": "Apply each target with ONE ds_add_avus call. Delete the root's "
                "previous lto.publish.* values first; see this script's docstring.",
        "root": {
            "target": root,
            "avus": [
                {"attribute": "lto.publish.commit", "value": manifest["git_commit"]},
                {"attribute": "lto.publish.timestamp", "value": manifest["timestamp_utc"]},
                {"attribute": "lto.publish.manifest_sha256", "value": manifest_sha},
                {"attribute": "lto.publish.tables", "value": str(manifest["table_count"])},
            ],
        },
        "tables": [],
    }
    for t, info in catalog.items():
        plan["tables"].append({
            "target": f"{root}/parquet/{t}.parquet",
            "avus": [
                {"attribute": "lto.table.name", "value": t},
                {"attribute": "lto.table.description", "value": info["description"]},
                {"attribute": "lto.table.kind", "value": info["kind"]},
                {"attribute": "lto.table.generator", "value": info["generator"]},
                {"attribute": "lto.table.columns", "value": capped(", ".join(info["columns"]))},
            ],
        })
    return plan


def preflight() -> list[str]:
    tables = export_tables_list()
    on_disk = {p.stem for p in PARQUET_DIR.glob("*.parquet")}
    missing = sorted(set(tables) - on_disk)
    extra = sorted(on_disk - set(tables))
    problems = []
    if missing:
        problems.append(f"tables in TABLES but missing from public/parquet/: {missing}")
    if extra:
        problems.append(f"parquet on disk but not in TABLES (stale?): {extra}")
    for f in [GEOJSON, CACHE_DIR / "browse_cards.json", CACHE_DIR / "people_cards.json"]:
        if not f.exists():
            problems.append(f"missing publishable: {f.relative_to(ROOT)}")
    described = set(table_descriptions())
    undescribed = sorted(set(tables) - described)
    if undescribed:
        problems.append(f"tables with no row in {TABLE_DESCRIPTIONS.relative_to(ROOT)}: "
                        f"{undescribed}")
    orphaned = sorted(described - set(tables))
    if orphaned:
        problems.append(f"{TABLE_DESCRIPTIONS.name} describes tables not in TABLES: {orphaned}")
    if problems:
        for p in problems:
            print(f"[preflight] FAIL {p}", file=sys.stderr)
        raise SystemExit(1)
    dirty = sh("git", "-C", str(ROOT), "status", "--porcelain")
    if dirty:
        print("[preflight] warn: git tree is dirty — MANIFEST records HEAD, not the tree",
              file=sys.stderr)
    return tables


def build_local_lake(tables: list[str]) -> str | None:
    """Snapshot every table into the local DuckLake. Returns snapshot id or None."""
    try:
        import duckdb

        conn = duckdb.connect()
        conn.execute("INSTALL ducklake; LOAD ducklake;")
        LAKE_DATA.mkdir(parents=True, exist_ok=True)
        conn.execute(
            f"ATTACH 'ducklake:{LAKE_CATALOG}' AS lake (DATA_PATH '{LAKE_DATA}/')"
        )
        for t in tables:
            conn.execute(
                f"CREATE OR REPLACE TABLE lake.{t} AS "
                f"SELECT * FROM read_parquet('{PARQUET_DIR / t}.parquet')"
            )
        snap = conn.execute(
            "SELECT max(snapshot_id) FROM lake.snapshots()"
        ).fetchone()[0]
        print(f"[lake] snapshot {snap} recorded ({len(tables)} tables)")
        return str(snap)
    except Exception as e:  # extension unavailable, no network, etc.
        print(f"[lake] skipped — {type(e).__name__}: {e}", file=sys.stderr)
        print("[lake] the publish is NOT degraded; committed parquet stays canonical",
              file=sys.stderr)
        return None


def stage(tables: list[str], staging: Path, lake_snapshot: str | None,
          catalog: dict[str, dict]) -> dict:
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "parquet").mkdir(parents=True)
    (staging / "geojson").mkdir()
    (staging / "cache").mkdir()
    (staging / "vocab").mkdir()
    (staging / "docs").mkdir()

    for t in tables:
        shutil.copyfile(PARQUET_DIR / f"{t}.parquet", staging / "parquet" / f"{t}.parquet")
    shutil.copyfile(GEOJSON, staging / "geojson" / GEOJSON.name)
    for f in CACHE_DIR.glob("*.json"):
        shutil.copyfile(f, staging / "cache" / f.name)
    for f in list(VOCAB_DIR.glob("*.csv")) + [VOCAB_DIR / "VERSION"]:
        if f.exists():
            shutil.copyfile(f, staging / "vocab" / f.name)
    if CROSSWALK_DIR.is_dir():
        for f in CROSSWALK_DIR.glob("*.csv"):
            shutil.copyfile(f, staging / "vocab" / f.name)
    for f in DOCS_DIR.glob("*.md"):
        shutil.copyfile(f, staging / "docs" / f.name)
    (staging / "TABLES.json").write_text(json.dumps(catalog, indent=2) + "\n")

    files = sorted(p for p in staging.rglob("*") if p.is_file())
    manifest = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": sh("git", "-C", str(ROOT), "rev-parse", "HEAD"),
        "git_branch": sh("git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"),
        "table_count": len(tables),
        "lake_snapshot": lake_snapshot,
        "files": {
            str(p.relative_to(staging)): {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in files
        },
    }
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    total_mb = sum(f["bytes"] for f in manifest["files"].values()) / 1e6
    print(f"[stage] {len(manifest['files'])} files, {total_mb:.1f} MB → {staging}")
    return manifest


def upload(staging: Path, freeze: bool, manifest: dict) -> None:
    if shutil.which("gocmd") is None:
        raise SystemExit(
            "[upload] gocmd is not installed. mesa-mcp cannot upload files itself "
            "(ds_upload_file only returns instructions), so install GoCommands "
            "(https://github.com/cyverse/gocommands), run `gocmd init` once, and "
            f"re-run. Staged files are in {staging}.")
    subprocess.run(
        ["gocmd", "sync", str(staging), IRODS_DEST, "--no_root", "--no_hash"],
        check=True,
    )
    print(f"[upload] synced → {IRODS_DEST[2:]}")
    if freeze:
        stamp = (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
                 + "-" + manifest["git_commit"][:7])
        subprocess.run(
            ["gocmd", "sync", str(staging), f"{IRODS_DEST}/snapshots/{stamp}",
             "--no_root", "--no_hash"],
            check=True,
        )
        print(f"[upload] frozen milestone copy → snapshots/{stamp}/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="preflight + stage only")
    ap.add_argument("--freeze", action="store_true",
                    help="also write a frozen copy under snapshots/<date>-<sha>/")
    ap.add_argument("--skip-lake", action="store_true", help="skip the local DuckLake")
    ap.add_argument("--staging", type=Path, default=ROOT / ".mesa_publish")
    args = ap.parse_args()

    tables = preflight()
    catalog = table_catalog(tables)
    lake_snapshot = None if args.skip_lake else build_local_lake(tables)
    manifest = stage(tables, args.staging, lake_snapshot, catalog)

    manifest_sha = hashlib.sha256(
        (args.staging / "MANIFEST.json").read_bytes()
    ).hexdigest()
    AVU_PLAN.write_text(json.dumps(avu_plan(manifest, catalog, manifest_sha), indent=2) + "\n")
    print(f"[stamp] AVU plan for the root and {len(catalog)} tables → "
          f"{AVU_PLAN.relative_to(ROOT)}")

    if args.dry_run:
        print("[dry-run] skipping upload; the AVU plan above is for inspection only")
        return 0

    upload(args.staging, args.freeze, manifest)

    print("\n[stamp] now apply the AVU plan through mesa-mcp: delete the root's "
          "previous lto.publish.* values, then one ds_add_avus call per target "
          "(one call = one .mesa/ducklake snapshot).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
