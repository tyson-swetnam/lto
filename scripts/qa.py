"""Data-quality assertions run after ingest.

Exits non-zero on any failure so CI workflows can gate deploys.

Two checks read source files rather than the database and run even on a
checkout with no data:

  * check_frontend_parses — every src/**/*.js must parse as an ES module
    (node vm.SourceTextModule; skipped with a warning when node is absent).
  * check_view_sql_types — no SQL template literal in src/views/*.js may
    return DECIMAL/HUGEINT to the browser (duckdb-wasm hands those to JS
    as non-numbers; the silent failure mode is a blank view).

Both are ported from cod-kmap, where each exists because of a shipped
incident documented in its docstring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "cod_kmap.duckdb"

# Territories that fall outside their country's main bounding box. Guam
# and the Northern Marianas sit at ~+145 EAST longitude and Palmyra at
# ~6 N, none of which a single US rectangle can express. Directly
# relevant to LTO: NEON's PUUM (Hawaii) and GUAN (Guam) domains, PacIOOS,
# and the Papahānaumokuākea sites all live in these boxes.
EXTRA_BBOXES = {
    "US": [
        (13.0, 21.0, 144.0, 146.5),      # Guam + Northern Mariana Islands
        (-15.0, 0.0, -172.0, -168.0),    # American Samoa
        (5.0, 7.0, -163.0, -161.0),      # Palmyra Atoll / Line Islands
        (18.0, 29.0, -178.5, -154.0),    # Hawaii + NW Hawaiian Islands
    ],
}

BBOX_BY_COUNTRY = {
    # (min_lat, max_lat, min_lng, max_lng) — generous continental boxes
    "US": (17.0, 72.0, -180.0, -64.0),
    "CA": (41.0, 84.0, -142.0, -52.0),
    "MX": (14.0, 33.0, -118.0, -86.0),
    "CU": (19.5, 23.5, -85.5, -74.0),
    "JM": (17.5, 18.7, -78.5, -76.0),
    "BS": (20.5, 27.5, -79.5, -72.5),
    "DO": (17.5, 20.0, -72.0, -68.0),
    "HT": (17.5, 20.0, -74.5, -71.5),
    "PR": (17.8, 18.6, -67.3, -65.2),
    "VI": (17.6, 18.5, -65.1, -64.5),
    "CO": (-4.3, 13.0, -81.8, -66.8),
    "BR": (-34.0, 5.3, -74.0, -28.6),
    "AR": (-55.2, -21.8, -73.6, -53.6),
    "CL": (-56.0, -17.5, -75.7, -66.4),
    "PE": (-18.4, -0.1, -81.4, -68.6),
    "EC": (-5.1, 1.7, -92.1, -75.2),
    "UY": (-35.0, -30.0, -58.5, -53.0),
    "VE": (0.6, 12.3, -73.4, -59.8),
    "PA": (7.2, 9.7, -83.0, -77.2),
    "CR": (8.0, 11.3, -86.0, -82.5),
    "GT": (13.7, 17.9, -92.3, -88.2),
    "BZ": (15.9, 18.5, -89.3, -87.3),
    "HN": (12.9, 16.6, -89.4, -83.1),
    "NI": (10.7, 15.1, -87.7, -82.6),
    "SV": (12.9, 14.5, -90.2, -87.6),
    "BB": (13.0, 13.4, -60.0, -59.3),
    "TT": (10.0, 11.5, -62.0, -60.4),
    "KY": (19.2, 19.9, -81.5, -79.7),
    "TC": (20.9, 22.0, -72.5, -71.0),
}


def assert_true(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)


# Columns each LTO table must still have. Duplicated from schema.sql on
# purpose: the point of a gate is to fail when the schema and the
# expectation drift apart, which a shared constant would hide.
EXPECTED_COLUMNS = {
    "spheres": {"slug", "label", "description"},
    "ecosystem_types": {"slug", "label", "source", "description"},
    "life_zones": {"slug", "label", "holdridge_class"},
    "facility_spheres": {"facility_id", "sphere_slug", "role"},
    "facility_ecosystems": {"facility_id", "ecosystem_slug"},
    "facility_life_zones": {"facility_id", "life_zone_slug"},
    "data_archives": {
        "archive_id", "name", "organization", "archive_type", "base_url",
        "api_url", "api_type", "license_slug",
    },
    "facility_archives": {"facility_id", "archive_id", "role", "scope_url"},
    "data_products": {
        "product_id", "archive_id", "facility_id", "title", "doi", "url",
        "format_slug", "license_slug", "source", "confidence",
    },
    "api_endpoints": {"endpoint_id", "archive_id", "path_or_url", "method"},
    "cloud_buckets": {"bucket_id", "archive_id", "provider", "bucket_name"},
}


def table_rows(conn, table: str) -> int:
    """Row count, or -1 when the table isn't in this database.

    The weekly refresh workflow rebuilds a DB from ingest.py alone, where
    the layered tables are empty (their data lives in committed parquet
    that ingest never touches). Gating on this keeps that run green
    instead of failing on absent data it was never asked to produce.
    """
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except duckdb.Error:
        return -1


def check_tables_present(conn, failures: list[str]) -> None:
    """If any of the layered tables has rows, they must all exist.

    Every check below no-ops on an empty table, which means an
    accidentally *dropped* table looked exactly like an empty one and
    silenced its invariants. Once one of the group is populated we know
    this is a full database, so a missing sibling is a real fault.
    """
    counts = {t: table_rows(conn, t) for t in EXPECTED_COLUMNS}
    if not any(n > 0 for n in counts.values()):
        return
    absent = sorted(t for t, n in counts.items() if n < 0)
    assert_true(not absent,
                f"table(s) missing from a populated database: {absent}", failures)


def check_columns(conn, failures: list[str]) -> None:
    for table, expected in EXPECTED_COLUMNS.items():
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
        except duckdb.Error:
            continue          # table absent — the row-count gates report it
        if not cols:
            continue
        missing = expected - cols
        assert_true(not missing, f"{table} missing column(s): {sorted(missing)}", failures)


def check_spheres(conn, failures: list[str]) -> None:
    """Six-sphere layer invariants."""
    if table_rows(conn, "facility_spheres") <= 0:
        return
    bad_slug = conn.execute(
        """SELECT COUNT(*) FROM facility_spheres fs
           LEFT JOIN spheres s ON fs.sphere_slug = s.slug
           WHERE s.slug IS NULL"""
    ).fetchone()[0]
    assert_true(bad_slug == 0,
                f"{bad_slug} facility_spheres rows reference unknown sphere_slug", failures)

    multi_primary = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT facility_id FROM facility_spheres
             WHERE role = 'primary'
             GROUP BY facility_id HAVING COUNT(*) > 1)"""
    ).fetchone()[0]
    assert_true(multi_primary == 0,
                f"{multi_primary} facilities have more than one primary sphere", failures)

    orphan = conn.execute(
        """SELECT COUNT(*) FROM facility_spheres fs
           LEFT JOIN facilities f ON fs.facility_id = f.facility_id
           WHERE f.facility_id IS NULL"""
    ).fetchone()[0]
    assert_true(orphan == 0,
                f"{orphan} facility_spheres rows point at unknown facilities", failures)


def check_life_zones(conn, failures: list[str]) -> None:
    """Holdridge life-zone layer invariants (ecosystem facet checked too)."""
    if table_rows(conn, "facility_life_zones") > 0:
        bad = conn.execute(
            """SELECT COUNT(*) FROM facility_life_zones fl
               LEFT JOIN life_zones z ON fl.life_zone_slug = z.slug
               WHERE z.slug IS NULL"""
        ).fetchone()[0]
        assert_true(bad == 0,
                    f"{bad} facility_life_zones rows reference unknown life_zone_slug",
                    failures)
    if table_rows(conn, "facility_ecosystems") > 0:
        bad = conn.execute(
            """SELECT COUNT(*) FROM facility_ecosystems fe
               LEFT JOIN ecosystem_types e ON fe.ecosystem_slug = e.slug
               WHERE e.slug IS NULL"""
        ).fetchone()[0]
        assert_true(bad == 0,
                    f"{bad} facility_ecosystems rows reference unknown ecosystem_slug",
                    failures)


def check_archives(conn, failures: list[str]) -> None:
    """Wave-J data-archive layer invariants."""
    if table_rows(conn, "facility_archives") > 0:
        orphan_archive = conn.execute(
            """SELECT COUNT(*) FROM facility_archives fa
               LEFT JOIN data_archives a ON fa.archive_id = a.archive_id
               WHERE a.archive_id IS NULL"""
        ).fetchone()[0]
        assert_true(orphan_archive == 0,
                    f"{orphan_archive} facility_archives rows point at unknown archives",
                    failures)
        orphan_fac = conn.execute(
            """SELECT COUNT(*) FROM facility_archives fa
               LEFT JOIN facilities f ON fa.facility_id = f.facility_id
               WHERE f.facility_id IS NULL"""
        ).fetchone()[0]
        assert_true(orphan_fac == 0,
                    f"{orphan_fac} facility_archives rows point at unknown facilities",
                    failures)
    if table_rows(conn, "data_archives") > 0:
        no_url = conn.execute(
            "SELECT COUNT(*) FROM data_archives WHERE base_url IS NULL OR base_url = ''"
        ).fetchone()[0]
        assert_true(no_url == 0,
                    f"{no_url} data_archives rows have no base_url", failures)
    if table_rows(conn, "data_products") > 0:
        orphan = conn.execute(
            """SELECT COUNT(*) FROM data_products p
               LEFT JOIN data_archives a ON p.archive_id = a.archive_id
               WHERE p.archive_id IS NOT NULL AND a.archive_id IS NULL"""
        ).fetchone()[0]
        assert_true(orphan == 0,
                    f"{orphan} data_products rows point at unknown archives", failures)


def check_view_sql_types(failures: list[str]) -> None:
    """No view query may return DECIMAL or HUGEINT to the browser.

    duckdb-wasm and duckdb-python disagree about these two types, and the
    disagreement is silent:

      * DECIMAL  -> Arrow structured value in wasm, plain float in python.
                    ``Number(v)`` on it is NaN. Every ``Number(x) || 0``
                    guard in the views then yields 0.
      * HUGEINT  -> BigInt in wasm, int in python. ``Number()`` copes, but
                    any arithmetic mixing it with a JS number throws
                    "Cannot mix BigInt and other types".

    This is exactly how cod-kmap's Knowledge Map died with "invalid
    bounds": a region weight was DECIMAL(38,2) because an integer count
    was multiplied by a JS-side decimal literal, ``Number(a.weight) || 0``
    made every weight 0, and the Voronoi bounding box was NaN. The SQL
    executed fine, the file parsed fine, and duckdb-python returned a
    plain float, so the local run was clean while the browser showed a
    blank page. Casting at the SQL boundary is the fix that holds
    regardless of which client reads the parquet.
    """
    import glob                                           # noqa: F401,PLC0415
    import re                                             # noqa: PLC0415

    root = Path(__file__).resolve().parent.parent
    site = root / "public" / "parquet"
    views = sorted((root / "src" / "views").glob("*.js"))
    if not views or not site.is_dir():
        return

    conn = duckdb.connect()
    for pq in site.glob("*.parquet"):
        conn.execute(
            f"CREATE OR REPLACE VIEW {pq.stem} AS "
            f"SELECT * FROM read_parquet('{pq.as_posix()}')")

    unsafe = ("DECIMAL", "HUGEINT", "UHUGEINT")
    for path in views:
        text = path.read_text()
        # Views interpolate numeric constants into SQL; substitute them so
        # the statement parses. Anything still interpolated is skipped.
        consts = dict(re.findall(r"const (W_[A-Z_]+)\s*=\s*([0-9.]+)", text))
        for m in re.finditer(r"`(\s*(?:WITH|SELECT)\b.*?)`", text, re.S):
            sql = m.group(1)
            for k, v in consts.items():
                sql = sql.replace("${" + k + "}", v)
            if "${" in sql or "?" in sql:
                continue
            try:
                rel = conn.sql(sql)
            except Exception:                             # noqa: BLE001
                # Type-checking is not this gate's job to enforce parseability;
                # check_frontend_parses and the view smoke tests cover that.
                continue
            for name, typ in zip(rel.columns, rel.types):
                if any(u in str(typ).upper() for u in unsafe):
                    assert_true(
                        False,
                        f"{path.name} returns column '{name}' as {typ}; "
                        f"duckdb-wasm hands DECIMAL/HUGEINT to JS as a "
                        f"non-number. Wrap it in CAST(... AS DOUBLE).",
                        failures)
    conn.close()


def check_frontend_parses(failures: list[str]) -> None:
    """Every src/*.js must be syntactically valid JavaScript.

    This exists because (upstream) a SQL comment inside a JS template
    literal read ``-- OpenAlex metrics that `people` alone does not``.
    The backticks closed the template literal and the whole site died
    with "Uncaught SyntaxError" — a blank page behind "Loading data…".
    Every query in the file still ran correctly when extracted and
    executed against DuckDB, so SQL-level verification passed while the
    page was unloadable. A character-balance heuristic does NOT catch
    this: the stray backticks come in pairs. Only a parser catches it.

    node's SourceTextModule parses the file as written, as an ES module,
    exactly as the browser does — no text substitution and no wrapper, so
    failures carry a real message and a real position. Construction
    parses without executing and without resolving imports, so bare
    specifiers ('maplibre-gl') that only an importmap resolves do not
    produce a false failure.

    Skipped, with a warning, if node is unavailable — the gate must still
    run in an environment that only has the Python data stack.
    """
    import json                                           # noqa: PLC0415
    import shutil                                         # noqa: PLC0415
    import subprocess                                     # noqa: PLC0415

    node = shutil.which("node")
    if not node:
        print("[qa] node not found — skipping the JS parse check. "
              "Install node to enable it.", file=sys.stderr)
        return

    src_dir = Path(__file__).resolve().parent.parent / "src"
    files = sorted(src_dir.rglob("*.js"))
    if not files:
        failures.append("no .js files found under src/ — is the checkout complete?")
        return

    script = """
const fs = require('fs');
const vm = require('vm');
const out = [];
for (const f of process.argv.slice(1)) {
  try {
    new vm.SourceTextModule(fs.readFileSync(f, 'utf8'), { identifier: f });
  } catch (e) {
    out.push({ file: f, error: String(e && e.message || e).slice(0, 200) });
  }
}
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(                                # noqa: S603
        [node, "--experimental-vm-modules", "-e", script, "--",
         *[str(f) for f in files]],
        capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0 and not proc.stdout.strip():
        failures.append(f"JS parse check could not run: "
                        f"{proc.stderr.strip().splitlines()[-1][:160]}"
                        if proc.stderr.strip() else "JS parse check failed to run")
        return
    try:
        problems = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        failures.append("JS parse check produced unreadable output")
        return
    for p in problems:
        rel = Path(p["file"]).relative_to(src_dir.parent)
        assert_true(False, f"{rel} is not valid JavaScript: {p['error']}",
                    failures)


def main() -> int:
    failures: list[str] = []
    with duckdb.connect(str(DB_PATH)) as conn:
        conn.execute("SET search_path = main;")

        null_type = conn.execute(
            "SELECT COUNT(*) FROM facilities WHERE facility_type IS NULL OR country IS NULL"
        ).fetchone()[0]
        assert_true(null_type == 0, f"{null_type} facilities with null facility_type or country", failures)

        bad_enum = conn.execute(
            "SELECT COUNT(*) FROM facilities f LEFT JOIN facility_types t ON f.facility_type = t.slug WHERE t.slug IS NULL"
        ).fetchone()[0]
        assert_true(bad_enum == 0, f"{bad_enum} facilities reference unknown facility_type", failures)

        no_prov = conn.execute(
            """SELECT COUNT(*) FROM facilities f
               LEFT JOIN provenance p ON p.record_type='facility' AND p.record_id = f.facility_id
               WHERE p.record_id IS NULL"""
        ).fetchone()[0]
        assert_true(no_prov == 0, f"{no_prov} facilities without provenance rows", failures)

        # bbox checks — a facility is misplaced only if it falls outside
        # EVERY box for its country, so an offshore territory doesn't read
        # as an error.
        for country, (min_lat, max_lat, min_lng, max_lng) in BBOX_BY_COUNTRY.items():
            boxes = [(min_lat, max_lat, min_lng, max_lng)] + EXTRA_BBOXES.get(country, [])
            outside = " AND ".join(
                "(hq_lat < ? OR hq_lat > ? OR hq_lng < ? OR hq_lng > ?)" for _ in boxes)
            params: list[float | str] = [country]
            for box in boxes:
                params.extend(box)
            count = conn.execute(
                f"""SELECT COUNT(*) FROM facilities
                    WHERE country = ? AND hq_lat IS NOT NULL AND hq_lng IS NOT NULL
                    AND ({outside})""",
                params,
            ).fetchone()[0]
            assert_true(count == 0, f"{count} {country} facilities outside the country bbox", failures)

        # LTO layered tables. Each block no-ops when its table is empty or
        # absent, so the ingest-only CI rebuild isn't failed by data it
        # never produces.
        check_tables_present(conn, failures)
        check_columns(conn, failures)
        check_spheres(conn, failures)
        check_life_zones(conn, failures)
        check_archives(conn, failures)

    # Outside the DB block: these read source files, not the database,
    # and must run even on a checkout with no data.
    check_frontend_parses(failures)
    check_view_sql_types(failures)

    if failures:
        print("QA FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("QA passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
