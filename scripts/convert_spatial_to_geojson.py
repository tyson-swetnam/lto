"""Convert all .shp / .gdb / .kmz / .kml under network_synth_spatial_analysis/
into MapLibre-ready GeoJSON (EPSG:4326, RFC 7946) alongside each source.

Usage:
    python scripts/convert_spatial_to_geojson.py
    python scripts/convert_spatial_to_geojson.py --root path/to/other/dir
    python scripts/convert_spatial_to_geojson.py --dry-run
    python scripts/convert_spatial_to_geojson.py --overwrite

Naming:
    foo.shp  -> foo.geojson            (same directory)
    foo.kmz  -> foo.geojson            (same directory; one per layer if multi)
    foo.gdb  -> foo__<layer>.geojson   (same parent directory, one per layer)

Layer names are slugified for filesystem safety.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

# Auto-regenerate .shx when a shapefile's index is missing.
gdal.SetConfigOption("SHAPE_RESTORE_SHX", "YES")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = ROOT / "network_synth_spatial_analysis"

FILE_EXTS = {".shp", ".kmz", ".kml"}
GDB_EXT = ".gdb"


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-") or "layer"


def iter_sources(root: Path):
    """Yield (path, kind) for every convertible source under `root`.

    kind is 'file' for .shp/.kmz/.kml and 'gdb' for .gdb directories.

    When a directory has a .shp and a .kml/.kmz sharing the same stem, the
    .kml/.kmz is skipped: the shapefile is authoritative and has a proper CRS.
    """
    sources: list[tuple[Path, str]] = []
    for p in root.rglob("*"):
        if p.is_dir() and p.suffix.lower() == GDB_EXT:
            sources.append((p, "gdb"))
        elif p.is_file() and p.suffix.lower() in FILE_EXTS:
            sources.append((p, "file"))

    shp_stems = {
        (p.parent, p.stem)
        for p, _ in sources
        if p.is_file() and p.suffix.lower() == ".shp"
    }

    for p, kind in sorted(sources, key=lambda x: str(x[0])):
        if kind == "file" and p.suffix.lower() in {".kml", ".kmz"}:
            if (p.parent, p.stem) in shp_stems:
                continue
        yield p, kind


def open_source(path: Path):
    try:
        return ogr.Open(str(path))
    except RuntimeError as e:
        print(f"  open failed: {e}", file=sys.stderr)
        return None


def convert_source(path: Path, kind: str, overwrite: bool, dry_run: bool) -> tuple[int, int]:
    """Convert every non-empty layer in `path` to GeoJSON next to it.

    Returns (written, skipped).
    """
    ds = open_source(path)
    if ds is None:
        print(f"  ERROR: could not open {path}", file=sys.stderr)
        return 0, 0

    n_layers = ds.GetLayerCount()
    if n_layers == 0:
        print(f"  no layers in {path.name}")
        return 0, 0

    parent = path.parent
    stem = path.stem
    written = skipped = 0

    # Pre-scan non-empty layers so we know whether to use multi-layer naming.
    candidates: list[tuple[int, str, int]] = []
    for i in range(n_layers):
        layer = ds.GetLayerByIndex(i)
        lname = layer.GetName()
        fcount = layer.GetFeatureCount()
        if fcount <= 0:
            print(f"  skip empty layer {stem}::{lname}")
            skipped += 1
            continue
        candidates.append((i, lname, fcount))

    multi = kind == "gdb" or len(candidates) > 1

    # Close and re-open per-layer; VectorTranslate is easier from a path than a ds handle.
    ds = None

    for _idx, lname, fcount in candidates:
        out_name = f"{stem}__{slugify(lname)}.geojson" if multi else f"{stem}.geojson"
        out_path = parent / out_name

        if out_path.exists() and not overwrite:
            print(f"  exists, skip: {out_path.relative_to(ROOT)}")
            skipped += 1
            continue

        if dry_run:
            print(f"  would write: {out_path.relative_to(ROOT)} ({fcount} feat, layer {lname!r})")
            written += 1
            continue

        opts = gdal.VectorTranslateOptions(
            format="GeoJSON",
            layers=[lname],
            dstSRS="EPSG:4326",
            reproject=True,
            accessMode="overwrite",
            layerCreationOptions=["RFC7946=YES", "WRITE_NAME=NO"],
            makeValid=True,
        )
        try:
            result = gdal.VectorTranslate(str(out_path), str(path), options=opts)
        except RuntimeError as e:
            print(f"  ERROR converting {path.name}::{lname}: {e}", file=sys.stderr)
            skipped += 1
            continue

        if result is None:
            print(f"  ERROR: VectorTranslate returned None for {path.name}::{lname}", file=sys.stderr)
            skipped += 1
            continue
        result = None  # flush + close

        if not out_path.exists() or out_path.stat().st_size == 0:
            print(f"  ERROR: empty output for {path.name}::{lname}", file=sys.stderr)
            try:
                out_path.unlink(missing_ok=True)
            except OSError:
                pass
            skipped += 1
            continue

        # Also drop outputs that wrote 0 features (e.g. malformed shapefile
        # where GDAL silently produced an empty FeatureCollection).
        try:
            import json
            doc = json.loads(out_path.read_text())
            if not doc.get("features"):
                print(f"  ERROR: zero-feature output for {path.name}::{lname}, removing", file=sys.stderr)
                out_path.unlink(missing_ok=True)
                skipped += 1
                continue
        except Exception as e:
            print(f"  WARN: could not validate {out_path.name}: {e}", file=sys.stderr)

        rel = out_path.relative_to(ROOT)
        print(f"  wrote {rel} ({fcount} feat)")
        written += 1

    return written, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=DEFAULT_TARGET,
                    help="Folder to scan (default: network_synth_spatial_analysis)")
    ap.add_argument("--dry-run", action="store_true", help="Report planned conversions, do not write")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing .geojson outputs")
    args = ap.parse_args()

    root: Path = args.root.resolve()
    if not root.exists():
        print(f"root does not exist: {root}", file=sys.stderr)
        return 2

    print(f"scanning {root}")
    sources = list(iter_sources(root))
    print(f"found {len(sources)} source(s)")

    total_written = total_skipped = total_errors = 0
    for path, kind in sources:
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"- {rel}  [{kind}]")
        try:
            w, s = convert_source(path, kind, args.overwrite, args.dry_run)
        except Exception as e:
            print(f"  FATAL: {e}", file=sys.stderr)
            total_errors += 1
            continue
        total_written += w
        total_skipped += s

    print("---")
    print(f"wrote: {total_written}  skipped: {total_skipped}  errors: {total_errors}")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
