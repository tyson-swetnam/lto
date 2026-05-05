#!/usr/bin/env python3
"""Resumable harvester for ArcGIS REST FeatureServer / MapServer layers.

Streams features in small pages, appending each page's NDJSON to a state
directory so re-runs can resume from where we left off if the process is
interrupted (which is common in sandboxed shell environments with short
per-call timeouts).

Source layer is identified by ``--service`` (the layer URL). The output is
two files in ``--state-dir``:

  - ``raw.ndjson``     — one GeoJSON Feature per line, in fetch order
  - ``cursor.json``    — ``{"offset": N, "total": T, "where": "...", "ts": "..."}``

When all pages are fetched, ``--out`` is written as a normal GeoJSON
FeatureCollection that combines every line of ``raw.ndjson``.

Example:
    python scripts/coastal_research/fetch_arcgis_resumable.py \
        --service "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/FWSApproved_Authoritative/FeatureServer/0" \
        --where "RSL_TYPE='NWR' OR RSL_TYPE='WMD' OR RSL_TYPE='COORD' OR RSL_TYPE='NM'" \
        --state-dir data/raw/R11_coastal_ecosystems/_state/fws_approved \
        --out network_synth_spatial_analysis/coastal_protected/fws_approved.geojson \
        --page 60 --max-seconds 35
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def _query(service: str, params: dict) -> dict:
    url = f"{service}/query?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "cod-kmap/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _count(service: str, where: str) -> int:
    d = _query(service, {"where": where, "returnCountOnly": "true", "f": "json"})
    return int(d.get("count", 0))


def _page(service: str, where: str, offset: int, page: int,
          max_offset: float | None = None,
          order_by: str = "OBJECTID") -> list[dict]:
    params = {
        "where": where,
        "outFields": "*",
        "outSR": 4326,
        "returnGeometry": "true",
        "resultOffset": offset,
        "resultRecordCount": page,
        "orderByFields": order_by,
        "f": "geojson",
    }
    if max_offset is not None:
        # Simplify geometry server-side to keep payloads small. Value is in
        # the units of outSR (degrees here): 0.001 ≈ 100 m at the equator.
        params["maxAllowableOffset"] = max_offset
    d = _query(service, params)
    if "error" in d:
        raise RuntimeError(f"ArcGIS error: {d['error']}")
    return d.get("features") or []


def _load_cursor(state_dir: str) -> dict:
    p = os.path.join(state_dir, "cursor.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def _save_cursor(state_dir: str, cur: dict) -> None:
    with open(os.path.join(state_dir, "cursor.json"), "w") as f:
        json.dump(cur, f, indent=2)


def _append(state_dir: str, feats: list[dict]) -> None:
    p = os.path.join(state_dir, "raw.ndjson")
    with open(p, "a") as f:
        for ft in feats:
            f.write(json.dumps(ft) + "\n")


def _flush_geojson(state_dir: str, out: str, service: str, where: str, total: int) -> None:
    feats: list[dict] = []
    p = os.path.join(state_dir, "raw.ndjson")
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    feats.append(json.loads(line))
    fc = {
        "type": "FeatureCollection",
        "features": feats,
        "metadata": {
            "source_service": service,
            "where": where,
            "retrieved_at": time.strftime("%Y-%m-%d"),
            "feature_count": len(feats),
            "expected_count": total,
        },
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(fc, f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--service", required=True)
    ap.add_argument("--where", default="1=1")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--page", type=int, default=60)
    ap.add_argument("--max-seconds", type=int, default=35,
                    help="Soft time budget for this invocation; resume next call.")
    ap.add_argument("--max-allowable-offset", type=float, default=None,
                    help="Server-side geometry simplification tolerance (in outSR units, "
                         "i.e. degrees for WGS84). 0.001 ≈ 100 m. Optional.")
    ap.add_argument("--order-by", default="OBJECTID",
                    help="Field to ORDER BY for stable pagination. Most ArcGIS layers "
                         "use OBJECTID; some (e.g. NEON Field_Sampling_Boundaries) "
                         "use FID. Default OBJECTID.")
    args = ap.parse_args()

    os.makedirs(args.state_dir, exist_ok=True)
    cur = _load_cursor(args.state_dir)

    if cur.get("where") != args.where or cur.get("service") != args.service:
        # New job — wipe state
        for fn in ("raw.ndjson", "cursor.json"):
            p = os.path.join(args.state_dir, fn)
            if os.path.exists(p):
                os.remove(p)
        cur = {}

    if not cur:
        total = _count(args.service, args.where)
        cur = {
            "service": args.service,
            "where": args.where,
            "total": total,
            "offset": 0,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save_cursor(args.state_dir, cur)
        print(f"[harvest] starting: {total} features expected", file=sys.stderr)

    started = time.time()
    while cur["offset"] < cur["total"]:
        if time.time() - started > args.max_seconds:
            print(f"[harvest] time budget reached at offset={cur['offset']}/{cur['total']} — resume next call", file=sys.stderr)
            break
        for attempt in range(3):
            try:
                feats = _page(args.service, args.where, cur["offset"], args.page,
                              max_offset=args.max_allowable_offset,
                              order_by=args.order_by)
                _append(args.state_dir, feats)
                cur["offset"] += args.page
                cur["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                _save_cursor(args.state_dir, cur)
                print(f"[harvest] offset={cur['offset']}/{cur['total']} +{len(feats)}", file=sys.stderr)
                if len(feats) < args.page:
                    cur["offset"] = cur["total"]  # finished early
                    _save_cursor(args.state_dir, cur)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[harvest] attempt {attempt+1} failed: {exc}", file=sys.stderr)
                time.sleep(2 ** attempt)
        else:
            print("[harvest] giving up this invocation", file=sys.stderr)
            break

    _flush_geojson(args.state_dir, args.out, args.service, args.where, cur["total"])
    done = cur["offset"] >= cur["total"]
    print(f"[harvest] {'COMPLETE' if done else 'PARTIAL'} — {cur['offset']}/{cur['total']} written to {args.out}", file=sys.stderr)
    return 0 if done else 2


if __name__ == "__main__":
    sys.exit(main())
