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
    bytes, git commit, branch, UTC timestamp, table count, lake snapshot).
    The staging dir contains no ``.git`` by construction — the CSI/FUSE
    mount must never see git metadata.
4.  **Upload** — ``gocmd sync .mesa_publish i:/iplant/home/tswetnam/lto
    --no_root`` (differential: unchanged files are skipped, so re-runs are
    idempotent). ``--freeze`` additionally uploads a frozen copy to
    ``snapshots/<YYYYMMDD>-<shortsha>/``.
5.  **Stamp** — prints the ``lto.publish.*`` AVU set for the collection
    root. A Python script cannot call MCP tools; the operator (usually
    Claude) applies them with one batched ``ds_add_avus`` call, which the
    MESA server mirrors into ``.mesa/ducklake/`` as the publish history.

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


def stage(tables: list[str], staging: Path, lake_snapshot: str | None) -> dict:
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
    lake_snapshot = None if args.skip_lake else build_local_lake(tables)
    manifest = stage(tables, args.staging, lake_snapshot)

    if args.dry_run:
        print("[dry-run] skipping upload + stamp")
        return 0

    upload(args.staging, args.freeze, manifest)

    manifest_sha = hashlib.sha256(
        (args.staging / "MANIFEST.json").read_bytes()
    ).hexdigest()
    print("\n[stamp] apply these AVUs to /iplant/home/tswetnam/lto with ONE "
          "batched ds_add_avus call (one call = one .mesa/ducklake snapshot):")
    print(json.dumps({
        "lto.publish.commit": manifest["git_commit"],
        "lto.publish.timestamp": manifest["timestamp_utc"],
        "lto.publish.manifest_sha256": manifest_sha,
        "lto.publish.tables": str(manifest["table_count"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
