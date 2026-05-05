#!/usr/bin/env python3
"""Patch antimeridian-crossing features in public/overlays/coastal-fws-units.geojson.

The original ``filter_coastal.py`` runs `geom.convex_hull` on dissolved
multi-part polygons. For Alaska Maritime National Wildlife Refuge —
which covers the Aleutian chain spanning both sides of the
international date line — the convex hull went *the wrong way around
the globe*: a ~359° longitude span instead of the small ~30° arc the
refuge actually occupies.

This script:

  1. Re-reads the raw FWS source
     (``network_synth_spatial_analysis/coastal_protected/fws_approved.geojson``).
  2. Finds every record whose dissolved bounding box crosses the
     antimeridian (longitude range ≥ 180°, but most of the points
     live at the extremes).
  3. Recomputes a date-line-aware envelope: shift western longitudes
     by +360 so the points are contiguous, take the convex hull, then
     split the hull back into two polygons clipped at the antimeridian
     (one west of +180°, one east of -180°). Output is a
     MultiPolygon that renders correctly on a Mercator basemap.
  4. Patches the matching feature in
     ``public/overlays/coastal-fws-units.geojson`` in place.

Idempotent — re-running on a previously-patched file is a no-op.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import (
    shape, mapping, Polygon, MultiPolygon, box, Point,
)
from shapely.ops import unary_union, transform
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "network_synth_spatial_analysis" / "coastal_protected" / "fws_approved.geojson"
OVERLAY = ROOT / "public" / "overlays" / "coastal-fws-units.geojson"

# Names whose source geometry is known to span the antimeridian. We
# match against the raw ORGNAME (uppercase) and the overlay name (Title
# Case'd by build_r11_facilities.py).
ANTIMERIDIAN_UNITS = {
    "ALASKA MARITIME NATIONAL WILDLIFE REFUGE",
}


def shift_west_to_east(lon: float, lat: float):
    """Shift longitudes < 0 by +360 so a feature spanning the date
    line becomes contiguous in [0, 360]."""
    return (lon + 360 if lon < 0 else lon, lat)


def split_back(geom):
    """Take a polygon expressed in [0, 360] longitudes and split it
    into two polygons clipped at lon = 180. Western points (>180) are
    shifted back by -360 so the output is in standard [-180, 180]."""
    east = geom.intersection(box(-1, -90, 180, 90))
    west_in_360 = geom.intersection(box(180, -90, 360, 90))
    pieces = []
    if not east.is_empty:
        pieces.append(east)
    if not west_in_360.is_empty:
        west = transform(lambda x, y, z=None: (x - 360, y), west_in_360)
        pieces.append(west)
    out = unary_union(pieces)
    if out.geom_type == "Polygon":
        return MultiPolygon([out])
    return out


def find_raw_geometry_for(name: str) -> object | None:
    """Dissolve every parcel of the named refuge in the raw FWS file
    and return a single Shapely geometry (with antimeridian-aware
    longitude shift applied)."""
    with RAW.open() as f:
        d = json.load(f)
    parts = []
    for ft in d.get("features") or []:
        org = (ft.get("properties") or {}).get("ORGNAME", "")
        if org != name:
            continue
        try:
            g = shape(ft["geometry"])
            if not g.is_valid:
                g = make_valid(g)
            # Shift western longitudes into [180, 360] so the dissolve
            # treats date-line-spanning parcels as contiguous.
            g_shift = transform(shift_west_to_east, g)
            parts.append(g_shift)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip] bad geometry: {exc}", file=sys.stderr)
    if not parts:
        return None
    merged = unary_union(parts)
    return merged.convex_hull   # tight envelope, but in [0, 360] space


def patch_overlay() -> int:
    if not OVERLAY.exists():
        print(f"[err] overlay file not found: {OVERLAY}", file=sys.stderr)
        return 2
    if not RAW.exists():
        print(f"[err] raw FWS file not found: {RAW}", file=sys.stderr)
        return 2

    with OVERLAY.open() as f:
        overlay = json.load(f)

    fixed = 0
    skipped = 0
    for ft in overlay.get("features") or []:
        nm = (ft["properties"].get("name") or "").upper()
        if nm not in ANTIMERIDIAN_UNITS:
            continue
        # Quick check: is the current geometry pathologically wide?
        g = shape(ft["geometry"])
        bx = g.bounds   # (minx, miny, maxx, maxy)
        if (bx[2] - bx[0]) < 180:
            print(f"[skip] {nm} already looks fine (lon span {bx[2]-bx[0]:.1f}°)",
                  file=sys.stderr)
            skipped += 1
            continue
        print(f"[fix ] {nm}: lon span {bx[2]-bx[0]:.1f}° → recomputing")

        hull_in_360 = find_raw_geometry_for(nm)
        if hull_in_360 is None:
            print(f"  [warn] no source parcels found for {nm}", file=sys.stderr)
            continue
        # Split back into two polygons at the antimeridian.
        new_geom = split_back(hull_in_360)
        # Sanity print
        new_lons = []
        if new_geom.geom_type == "MultiPolygon":
            for p in new_geom.geoms:
                new_lons += [pt[0] for pt in p.exterior.coords]
        else:
            new_lons = [pt[0] for pt in new_geom.exterior.coords]
        print(f"  new lon range: {min(new_lons):.2f} ... {max(new_lons):.2f}")
        ft["geometry"] = mapping(new_geom)
        ft["properties"]["geometry_simplified"] = "convex_hull_per_hemisphere"
        fixed += 1

    if fixed == 0:
        print("[done] nothing to fix.", file=sys.stderr)
        return 0
    OVERLAY.write_text(json.dumps(overlay))
    print(f"[done] patched {fixed} feature(s); {skipped} already OK. "
          f"Wrote {OVERLAY.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(patch_overlay())
