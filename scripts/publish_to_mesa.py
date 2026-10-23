#!/usr/bin/env python3
"""Publish the LTO data artifacts to the MESA project on the CyVerse Data Store.

Target collection:  /iplant/home/tswetnam/lto   (enrolled MESA project;
its ``.mesa/ducklake/`` history is maintained server-side from AVU writes).

What a publish is
-----------------
1.  **Preflight** — the set of parquet files in ``public/parquet/`` must
    exactly match the ``TABLES`` list in ``scripts/export_parquet.py``.
    The export now fails hard on a missing table, but a stray or stale
    file left in ``public/parquet/`` is still only caught here.
2.  **Lake snapshot** — reads (read-only) the newest snapshot of the
    DuckLake store of record (``scripts/lto_db.py``: ``db/lto_catalog.sqlite``
    + ``db/lake/``) and records its id, time, author and commit message in
    ``MANIFEST.json``, so a publish names the lake state it came from.
    This used to build a *separate* lake (``db/lto_lake.ducklake``) by
    copying the parquet on every publish — a copy, not the store — and
    swallowed every error. Now a missing or unreadable lake stops the
    publish; ``--skip-lake`` records ``"lake": null`` deliberately (e.g.
    publishing from a checkout that never built a lake). Snapshot ids are
    local to one machine's lake; the parquet sha256s are what identify
    the published data.
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
    python scripts/publish_to_mesa.py --skip-lake      # no lake on this machine
    python scripts/publish_to_mesa.py --catalog /path/to/cat.sqlite
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


def lake_snapshot(catalog: Path | None, data: Path | None) -> dict:
    """Newest snapshot of the store-of-record lake (read-only).

    Raises (LakeNotFound, duckdb.Error) rather than returning None: a
    publish that claims lake provenance must actually have it.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import lto_db  # noqa: PLC0415

    con = lto_db.connect(read_only=True, catalog=catalog, data=data)
    try:
        snap = lto_db.latest_snapshot(con)
        cat = lto_db.catalog_path(catalog)
        # Repo-relative when it is the usual lake; never a home-dir path.
        snap["catalog"] = (str(cat.relative_to(ROOT)) if cat.is_relative_to(ROOT)
                           else cat.name)
        snap["ducklake_version"] = lto_db.scalar(
            con, "SELECT value FROM lake.options() WHERE option_name = 'version'")
    finally:
        con.close()
    print(f"[lake] snapshot {snap.get('snapshot_id')} "
          f"({snap.get('snapshot_time')}): {snap.get('commit_message')!r}")
    return snap


def stage(tables: list[str], staging: Path, lake: dict | None) -> dict:
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
        # Store-of-record lake state this publish was exported from (None
        # only with --skip-lake). snapshot_id is local to that machine's lake.
        "lake": lake,
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
    ap.add_argument("--skip-lake", action="store_true",
                    help="do not record the lake snapshot (MANIFEST gets \"lake\": null)")
    ap.add_argument("--catalog", type=Path, default=None,
                    help="DuckLake catalog (default: $LTO_LAKE_CATALOG or db/lto_catalog.sqlite)")
    ap.add_argument("--lake-data", type=Path, default=None,
                    help="DuckLake data dir (default: $LTO_LAKE_DATA or <catalog dir>/lake)")
    ap.add_argument("--staging", type=Path, default=ROOT / ".mesa_publish")
    args = ap.parse_args()

    tables = preflight()
    if args.skip_lake:
        print("[lake] --skip-lake: MANIFEST records no lake snapshot", file=sys.stderr)
        lake = None
    else:
        try:
            lake = lake_snapshot(args.catalog, args.lake_data)
        except Exception as e:  # noqa: BLE001 — reported, then the publish stops
            print(f"[lake] FAILED to read the lake: {type(e).__name__}: {e}\n"
                  "[lake] build it (scripts/rebuild_lake_from_parquet.py) or pass "
                  "--skip-lake to publish without lake provenance.", file=sys.stderr)
            return 1
    manifest = stage(tables, args.staging, lake)

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
        **({"lto.publish.lake_snapshot": str(manifest["lake"]["snapshot_id"])}
           if manifest.get("lake") else {}),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
