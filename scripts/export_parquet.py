"""Export the lake's tables to Parquet for DuckDB-Wasm HTTP-range reads.

This is the ONLY writer of ``public/parquet/`` (and ``public/
facilities.geojson``). Everything upstream — loaders, enrichers, the
``compute_*`` scripts, ``build_mvg_layout.py`` — writes into the DuckLake
store of record (``scripts/lto_db.py``); this script reads it read-only
and publishes.

Produces::

    public/parquet/<table>.parquet     (what the static site serves; committed)
    public/facilities.geojson          (lightweight first-paint fallback)

``--db-out DIR`` also writes a second copy of the parquet there (off by
default; the rebuild never reads ``db/parquet/`` unless told to, so a
default second copy only went stale after a pull).

Scratch lakes do not publish. When the catalog is not the default
``db/lto_catalog.sqlite`` (``--catalog`` or ``$LTO_LAKE_CATALOG``), the
defaults for ``--out`` and ``--geojson`` become ``<catalog dir>/export/
parquet/`` and ``<catalog dir>/export/facilities.geojson``, so an
experiment cannot overwrite the committed ``public/`` files. Pass
``--out public/parquet --geojson public/facilities.geojson`` explicitly
to publish from a non-default lake.

Rules, each fixing a way the old export could ship the wrong thing:

  * **A table in TABLES that the lake does not have is a hard failure.**
    The old export swallowed the CatalogException and left whatever stale
    parquet was on disk, so a "successful" export could ship old data.
    Existence is checked for every table before any file is written, so a
    failed export writes nothing. ``ALLOW_MISSING`` is the explicit,
    commented exception list (empty today).
  * **PASSTHROUGH tables are not exported from the lake** (empty today).
    A table whose parquet another script writes directly would go here;
    its file must exist, and when ``--out`` points elsewhere it is copied
    there so the output is a complete set. ``url_health`` used to be one;
    ``check_url_health.py`` now writes the lake table, so it is exported
    like any other.
  * **Row order is deterministic.** Every COPY is ``ORDER BY`` the table's
    primary key from schema.sql, then every other column (tables without
    a PK sort by all columns), and the GeoJSON is ordered by facility id.
    Re-exporting unchanged data therefore produces the same rows in the
    same order on any DuckDB version, and diffs show real changes only.
  * Files are written to a temp name and renamed, so an interrupted run
    never leaves a truncated parquet behind.

COPY uses DuckDB's default parquet options (SNAPPY, format v1), which
DuckDB 1.1 (inside duckdb-wasm 1.29) and later read. Every column is
written OPTIONAL, as DuckDB 1.x wrote them (see ``copy_table``): DuckDB 2.0
would otherwise mark a column REQUIRED whenever the lake's current physical
layout lets it prove there are no NULLs, so the bytes would change with
compaction even when the rows did not.

Usage::

    python scripts/export_parquet.py
    python scripts/export_parquet.py --out /tmp/x/parquet \
        --geojson /tmp/x/facilities.geojson          # export elsewhere
    python scripts/export_parquet.py --catalog /tmp/x/cat.sqlite
                                     # -> /tmp/x/export/{parquet/,facilities.geojson}
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DB = ROOT / "db" / "parquet"
OUT_WEB = ROOT / "public" / "parquet"
GEOJSON_OUT = ROOT / "public" / "facilities.geojson"

TABLES = [
    "facilities",
    "locations",
    "funders",
    "funding_events",
    "funding_links",
    "research_areas",
    "area_links",
    "networks",
    "network_membership",
    "facility_types",
    "provenance",
    # Region-side tables (regions = one row per overlay polygon,
    # region_area_links = region ↔ research_area many-to-many, and
    # facility_regions = which facilities sit inside which regions).
    "regions",
    "region_area_links",
    "facility_regions",
    # LTO six-sphere extension tables.
    "spheres",
    "ecosystem_types",
    "life_zones",
    "facility_spheres",
    "facility_ecosystems",
    "facility_life_zones",
    # People tables (Wave F).
    "people",
    "facility_personnel",
    "publications",
    "publication_topics",        # often empty until OpenAlex enrichment;
                                 # ship anyway so DuckDB-Wasm can register
                                 # the view without a fetch failure.
    "authorship",
    "person_areas",
    "collaborations",
    # Derived tables — produced by compute_primary_groups.py /
    # compute_area_metrics.py / compute_lto_person_metrics.py, which write
    # them INTO the lake (CREATE OR REPLACE TABLE). This export is the only
    # writer of public/parquet; a derived table missing from the lake is a
    # hard failure, not a silent skip.
    "research_areas_active",
    "facility_primary_groups",
    "person_primary_groups",
    "person_area_metrics",
    "facility_area_funding",
    "funder_area_funding",
    "area_coverage_matrix",
    # URL health sweep — check_url_health.py writes the lake's url_health
    # table (replace_table); exported from the lake like everything else.
    "url_health",
    # MVG knowledge-map layout — produced by scripts/build_mvg_layout.py.
    # Loaded into the lake by the rebuild; exported from the lake.
    "mvg_node_layout",
    "mvg_area_polygons",
    "mvg_layout_metrics",
    "scholar_area_assignments",
    # Wave J data-archive layer.
    "archive_types",
    "data_formats",
    "data_licenses",
    "access_modes",
    "data_archives",
    "facility_archives",
    "data_products",
    "api_endpoints",
    "cloud_buckets",
    # ARID wave — projects, their teams, and the facilities they involve.
    "projects",
    "project_personnel",
    "project_facilities",
    # Unified person identity (KMAP alignment). Ship zero-row parquet until
    # build_person_registry.py / the harvest populate them, so DuckDB-Wasm
    # registration never 404s. Only tier='core' rows are exported for
    # person_registry — see the WHERE override below.
    "person_registry",
    "person_identity_source",
    "registry_collaborations",
    "registry_facilities",
    "person_validation",
    "coauthor_edges",
    "coauthor_candidates",
]

# Tables that ship filtered. person_registry's archive tier can reach 100k+
# rows after the OpenAlex harvest; the browser only ever renders the core
# tier, so only core ships. The full population stays in db/parquet is NOT
# true here — db/parquet gets the same filtered copy; the full population
# lives only in the local lake (gitignored), exactly like upstream.
EXPORT_WHERE = {
    "person_registry": "WHERE tier = 'core'",
    # Edges/links only ship when both endpoints ship.
    "registry_collaborations":
        "WHERE canonical_id_a IN (SELECT canonical_id FROM person_registry WHERE tier='core')"
        "  AND canonical_id_b IN (SELECT canonical_id FROM person_registry WHERE tier='core')",
    "coauthor_edges":
        "WHERE canonical_id_a IN (SELECT canonical_id FROM person_registry WHERE tier='core')"
        "  AND canonical_id_b IN (SELECT canonical_id FROM person_registry WHERE tier='core')",
    "registry_facilities":
        "WHERE canonical_id IN (SELECT canonical_id FROM person_registry WHERE tier='core')",
}

# Columns that stay in the lake but never ship: public/parquet is served to
# anyone (and queryable from the SQL tab). Personal contact details are not
# published; the column is kept, all NULL, so the parquet keeps the
# schema.sql shape and a rebuilt lake has the column.
EXPORT_REDACT = {
    "people": {"email": "CAST(NULL AS VARCHAR)"},
}

# Tables whose parquet another script writes directly; never exported from
# the lake (see the module docstring). Empty: check_url_health.py writes the
# lake's url_health table now.
PASSTHROUGH: dict[str, str] = {}

# Tables allowed to be absent from the lake (their existing parquet is left
# as is). Every entry needs a reason and should be temporary.
ALLOW_MISSING: dict[str, str] = {}


def order_by(con, table: str) -> str:
    """ORDER BY: schema.sql primary key first, then every remaining column."""
    cols = [d[0] for d in con.execute(
        f"SELECT * FROM {lto_db.qident(table)} LIMIT 0").description]
    pk = lto_db.primary_key(table) or []
    keys = pk + [c for c in cols if c not in pk]
    return ", ".join(lto_db.qident(c) for c in keys)


def copy_table(con, table: str, where: str, dest: Path,
               redact: dict[str, str] | None = None) -> int:
    """COPY one table, sorted, with every parquet column OPTIONAL.

    DuckDB 2.0 writes a column as REQUIRED whenever the planner's
    statistics say it holds no NULLs. Those statistics depend on the
    lake's physical state (inlined rows, delete files, compaction), so the
    same rows exported before and after ``lake_maintenance.py`` came out
    with different REQUIRED flags — different bytes, and a binary diff in
    git for an unchanged table. Routing the rows through the nullable side
    of a LEFT JOIN drops that statistic, so every column is OPTIONAL, as
    every DuckDB 1.x export (all the committed files) was. The LIMIT drops
    the one all-NULL row the join yields for an empty table; unlike a
    WHERE, it does not give the planner its not-NULL statistic back.
    """
    tmp = dest.with_name(f".{dest.name}.tmp")
    repl = (" REPLACE (" + ", ".join(f"{e} AS {lto_db.qident(c)}" for c, e in redact.items()) + ")"
            if redact else "")
    src = f"(SELECT *{repl} FROM {lto_db.qident(table)} {where})"
    con.execute(
        f"COPY (SELECT _t.* FROM (SELECT 1 AS __lto_one) _d LEFT JOIN {src} _t ON true "
        f"ORDER BY {order_by(con, table)} "
        f"LIMIT (SELECT count(*) FROM {src})) TO '{tmp.as_posix()}' (FORMAT PARQUET)")
    os.replace(tmp, dest)
    return lto_db.scalar(con, "SELECT count(*) FROM read_parquet(?)", [str(dest)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--out", type=Path, default=None,
                    help="parquet output dir (default: public/parquet; "
                         "<catalog dir>/export/parquet for a non-default catalog)")
    ap.add_argument("--db-out", default="none",
                    help=f"also write a second copy of the parquet here, e.g. "
                         f"{OUT_DB.relative_to(ROOT)} (default: none)")
    ap.add_argument("--geojson", type=Path, default=None,
                    help="GeoJSON output (default: public/facilities.geojson; "
                         "<catalog dir>/export/facilities.geojson for a non-default catalog)")
    args = ap.parse_args()
    if lto_db.is_default_catalog(args.catalog):
        out_default, geo_default = OUT_WEB, GEOJSON_OUT
    else:
        scratch = lto_db.catalog_path(args.catalog).parent / "export"
        out_default, geo_default = scratch / "parquet", scratch / "facilities.geojson"
        if args.out is None or args.geojson is None:
            print(f"[note] non-default catalog: writing to {scratch} rather than public/ "
                  "(pass --out/--geojson to override)", file=sys.stderr)
    args.out = args.out or out_default
    args.geojson = args.geojson or geo_default
    out = args.out.resolve()
    db_out = None if args.db_out.lower() == "none" else Path(args.db_out).resolve()

    try:
        conn = lto_db.connect(read_only=True, catalog=args.catalog, data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    with conn:
        # 1. Everything must be there before anything is written.
        missing = [t for t in TABLES
                   if t not in PASSTHROUGH and not lto_db.table_exists(conn, t)]
        fatal = [t for t in missing if t not in ALLOW_MISSING]
        if fatal:
            print(f"[error] in TABLES but not in the lake: {', '.join(fatal)}\n"
                  "        Run the script that produces them (or rebuild the lake); "
                  "nothing was written.", file=sys.stderr)
            return 1
        for t in PASSTHROUGH:
            if not (OUT_WEB / f"{t}.parquet").exists():
                print(f"[error] passthrough table {t} has no {OUT_WEB / t}.parquet "
                      f"({PASSTHROUGH[t]}); nothing was written.", file=sys.stderr)
                return 1

        out.mkdir(parents=True, exist_ok=True)
        if db_out:
            db_out.mkdir(parents=True, exist_ok=True)

        exported: dict[str, int] = {}
        for t in TABLES:
            if t in missing or t in PASSTHROUGH:
                continue
            exported[t] = copy_table(conn, t, EXPORT_WHERE.get(t, ""), out / f"{t}.parquet",
                                     EXPORT_REDACT.get(t))
            if db_out:
                shutil.copyfile(out / f"{t}.parquet", db_out / f"{t}.parquet")
        for t in PASSTHROUGH:
            src = OUT_WEB / f"{t}.parquet"
            for d in (out, db_out):
                if d and (d / src.name).resolve() != src.resolve():
                    shutil.copyfile(src, d / src.name)

        # lightweight geojson — facility map points enriched with the
        # primary_sphere from facility_spheres so the LTO sphere-color
        # legend works without DuckDB-Wasm having to load every parquet.
        rows = conn.execute(
            # state / has_arid_sphere / in_arid_network feed the scope lens
            # (src/filters.js) so it also works in this fallback tier,
            # before DuckDB-Wasm is up.
            """SELECT v.id, v.name, v.acronym, v.type, v.country, v.lat, v.lng,
                      v.url, v.parent_org, f.established,
                      f.record_length_years, f.long_term_threshold_met,
                      fs.sphere_slug AS primary_sphere,
                      f.state,
                      EXISTS (SELECT 1 FROM facility_spheres a
                              WHERE a.facility_id = v.id AND a.sphere_slug = 'arid'),
                      EXISTS (SELECT 1 FROM network_membership m
                              WHERE m.facility_id = v.id AND m.network_id = 'arid-unm')
               FROM v_facility_map v
               JOIN facilities f ON f.facility_id = v.id
               LEFT JOIN facility_spheres fs
                 ON fs.facility_id = v.id AND fs.role = 'primary'
               ORDER BY v.id, fs.sphere_slug"""
        ).fetchall()
        not_exported = sorted(set(lto_db.lake_tables(conn)) - set(TABLES))
        snap = lto_db.latest_snapshot(conn)

    features = []
    for r in rows:
        (fid, name, acronym, ftype, country, lat, lng, url, parent, established,
         rly, ltm, primary_sphere, state, has_arid_sphere, in_arid_network) = r
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": fid,
                "name": name,
                "acronym": acronym,
                "type": ftype,
                "country": country,
                "url": url,
                "parent_org": parent,
                "established": established,
                "record_length_years": rly,
                "long_term_threshold_met": ltm,
                "primary_sphere": primary_sphere,
                "state": state,
                "has_arid_sphere": has_arid_sphere,
                "in_arid_network": in_arid_network,
            },
        })

    args.geojson.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.geojson.with_name(f".{args.geojson.name}.tmp")
    tmp.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=0)
    )
    os.replace(tmp, args.geojson)

    print(f"[ok] exported {len(exported)} of {len(TABLES)} parquet tables from lake "
          f"snapshot {snap.get('snapshot_id')} and {len(features)} features to GeoJSON "
          f"-> {out}")
    if PASSTHROUGH:
        print(f"[passthrough] left as written by their producer: {', '.join(PASSTHROUGH)}")
    if missing:
        print(f"[allowed-missing] not in the lake, existing parquet left as is: "
              f"{', '.join(missing)}")
    if not_exported:
        print(f"[info] lake tables not in TABLES (not published): {', '.join(not_exported)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
