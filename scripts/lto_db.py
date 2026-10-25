"""One way in to the LTO store of record: a DuckLake with a SQLite catalog.

What the store is
-----------------
The project's working database is a DuckLake (spec 1.1, the DuckDB 2.0
default), not a single ``.duckdb`` file:

  * ``db/lto_catalog.sqlite``  — the DuckLake catalog: table definitions,
    snapshot history, commit messages, small inlined writes.
  * ``db/lake/``               — the lake's parquet data files.

Both are gitignored. The committed, canonical artifact is still
``public/parquet/*.parquet`` (the browser contract and the fresh-clone
seed); ``scripts/rebuild_lake_from_parquet.py`` turns that folder back
into a lake, and ``scripts/export_parquet.py`` is the only script that
writes it. ``db/lto.duckdb`` is retired.

Why a lake, and why a SQLite catalog:

  * DuckDB's native file blocked ``UPDATE``/``INSERT OR REPLACE`` on any
    row another table pointed at ("still referenced by a foreign key").
    A lake has no such block.
  * Every write is a snapshot with an author and a commit message, so
    "what did load_arid.py change last Tuesday" is a query
    (``lake.snapshots()``, ``ducklake_table_changes(...)``, ``AT (VERSION
    => n)``).
  * A SQLite catalog has no DuckDB storage-version trap (a DuckDB-file
    catalog written by 2.0 is unreadable by 1.5.x), and readers never
    block: any number of processes can read the lake while one writes.

Writers are serialised. ``transaction()`` takes an exclusive ``flock`` on
``<catalog>.lock`` before ``BEGIN`` and releases it after ``COMMIT`` or
``ROLLBACK``, so a second writer queues instead of committing alongside
the first. Without the lock two concurrent transactions each see only
their own snapshot: two insert-if-absent writes both commit a duplicate
key, and a DELETE of a parent in one plus an INSERT of a child in the
other both pass ``assert_integrity`` and commit an orphan. DuckLake's own
conflict detection catches neither (it only aborts some same-table
write/write conflicts, and then the script fails instead of waiting).
So every lake write belongs inside ``transaction()``; an autocommit
statement outside one is not serialised.

What a lake does NOT do: DuckLake rejects PRIMARY KEY, UNIQUE, FOREIGN
KEY, CHECK, indexes and sequences. ``schema/schema.sql`` therefore stays
the *logical* schema, constraints and all; it is executed only in a
throwaway in-memory "spec" database. The lake is created column-only
(types, NOT NULL, DEFAULT — those DuckLake does enforce) from that spec,
and the constraints are enforced after the fact by
``integrity_violations()`` / ``assert_integrity()`` here, which ``qa.py``
runs as a hard gate. Nothing stops a duplicate key or an orphan at write
time, which is why ``merge_upsert()`` always de-duplicates its source.
The same check also covers the derived tables (``DERIVED_CONSTRAINTS``),
the soft references schema.sql leaves undeclared (``SOFT_REFERENCES``)
and column drift between the lake and schema.sql.

Using it
--------
::

    import lto_db

    con = lto_db.connect()                         # read-write
    con = lto_db.connect(read_only=True)           # exporters, QA
    con = lto_db.connect(snapshot=118)             # time travel (read-only)

    with lto_db.transaction(con, "load_arid: ARID people + projects"):
        con.execute("CREATE TEMP TABLE stage AS SELECT ...")
        lto_db.merge_upsert(con, "people", ["person_id"], "stage")
        lto_db.assert_integrity(con, ["people", "facility_personnel"])

    with lto_db.transaction(con, "compute_area_metrics: per-area metrics"):
        lto_db.replace_table(con, "person_area_metrics", "SELECT ...")

    with lto_db.transaction(con, "schema: people.bio_source_url"):
        lto_db.ensure_schema(con)          # add what schema.sql gained

    n = lto_db.scalar(con, "SELECT count(*) FROM facilities")

The connection has ``USE lake`` applied, so unqualified table names,
``main.<t>`` and ``lake.main.<t>`` all resolve to the lake. TEMP tables
live in DuckDB's own temp catalog and can be written in the same
transaction as the lake.

Pointing a script at a different lake (tests, CI, scratch experiments)
does not need code changes: set ``LTO_LAKE_CATALOG`` (path to the
``.sqlite`` catalog) and optionally ``LTO_LAKE_DATA`` (the data
directory; defaults to ``<catalog dir>/lake``), or pass ``--catalog`` to
any script that calls ``add_argparse_catalog()``. An explicit
``--catalog`` ignores ``$LTO_LAKE_DATA`` (its data is ``--lake-data`` or
``<catalog dir>/lake``), so a scratch catalog can never be paired with
the main lake's data directory by a stale environment variable. The
exporters write into ``<catalog dir>/export/`` rather than ``public/``
when the catalog is not the default one (``is_default_catalog()``).

Gotchas this module exists to absorb
------------------------------------
  * ``ATTACH`` does not create parent directories, and a *relative*
    ``DATA_PATH`` resolves against the process cwd, not the catalog. Both
    paths are made absolute here and ``OVERRIDE_DATA_PATH true`` is always
    passed, so a script works from any directory and a lake can be moved.
  * ``ATTACH`` on a missing catalog silently creates an *empty* lake. On a
    fresh clone that turns "you forgot to rebuild" into a confusing
    "table does not exist" three scripts later, so ``connect()`` refuses
    a missing catalog unless ``create=True`` (only the rebuild passes it).
  * ``INSERT OR REPLACE``, ``INSERT OR IGNORE`` and ``ON CONFLICT`` all
    need a primary key and fail on DuckLake ("There are no UNIQUE/PRIMARY
    KEY constraints that refer to this table"). Use ``merge_upsert()``.
  * A ``MERGE`` whose source repeats a key inserts *both* rows. Hence the
    ``DISTINCT ON`` in ``merge_upsert()``.
  * Each autocommit statement is its own snapshot (and, past the inlining
    limit, its own data file). Wrap loader writes in ``transaction()`` so
    one loader run is one snapshot with one commit message.
  * ``count(*)`` is answered from catalog statistics and can hide a
    missing data file; smoke tests should read a column (``sum(x)``).
  * Fetching a ``TIMESTAMPTZ`` (e.g. ``snapshot_time``) into Python needs
    ``pytz``; it is in requirements.txt, and ``latest_snapshot()`` casts
    to VARCHAR anyway.
  * DuckDB 2.0 Python: a half-read ``execute()`` result blocks relation
    API calls (``.sql()``, ``.register()``, ...) on the same connection.
    ``scalar()`` / ``rows()`` always drain with ``fetchall()``.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import functools
import hashlib
import os
import sys
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = ROOT / "schema" / "schema.sql"
PUBLIC_PARQUET = ROOT / "public" / "parquet"
LOCAL_PARQUET = ROOT / "db" / "parquet"

DEFAULT_CATALOG = ROOT / "db" / "lto_catalog.sqlite"
DEFAULT_DATA = ROOT / "db" / "lake"
LAKE = "lake"                       # the ATTACH alias every script sees

ENV_CATALOG = "LTO_LAKE_CATALOG"
ENV_DATA = "LTO_LAKE_DATA"


class LakeNotFound(RuntimeError):
    """The catalog file does not exist (run rebuild_lake_from_parquet.py)."""


class IntegrityError(RuntimeError):
    """schema.sql constraints violated; ``.violations`` holds the details."""

    def __init__(self, violations: list[dict]):
        self.violations = violations
        super().__init__(format_violations(violations))


# ---------------------------------------------------------------------------
# Paths and connection
# ---------------------------------------------------------------------------

def catalog_path(catalog: str | os.PathLike | None = None) -> Path:
    """Resolve the catalog: explicit argument > $LTO_LAKE_CATALOG > default."""
    raw = catalog or os.environ.get(ENV_CATALOG) or DEFAULT_CATALOG
    return Path(raw).expanduser().resolve()


def data_path(catalog: str | os.PathLike | None = None,
              data: str | os.PathLike | None = None) -> Path:
    """Resolve the data dir: explicit > $LTO_LAKE_DATA > ``<catalog dir>/lake``.

    The fallback keeps a catalog and its data side by side, which is also
    what the default layout is (``db/lto_catalog.sqlite`` + ``db/lake/``).

    ``$LTO_LAKE_DATA`` is ignored when ``catalog`` is passed explicitly:
    the env var belongs to the env-var/default catalog, and pairing a
    scratch ``--catalog`` with it once made a scratch rebuild delete the
    main lake's data files.
    """
    if data:
        return Path(data).expanduser().resolve()
    raw = None if catalog else os.environ.get(ENV_DATA)
    if raw:
        return Path(raw).expanduser().resolve()
    return catalog_path(catalog).parent / "lake"


def is_default_catalog(catalog: str | os.PathLike | None = None) -> bool:
    """True when ``catalog`` (after env/default resolution) is the repo lake."""
    return catalog_path(catalog) == DEFAULT_CATALOG.resolve()


def _load_extensions(con: duckdb.DuckDBPyConnection) -> None:
    # LOAD works offline once the extension is installed; INSTALL needs
    # extensions.duckdb.org the first time only.
    for ext in ("ducklake", "sqlite"):
        try:
            con.execute(f"LOAD {ext}")
        except duckdb.Error:
            con.execute(f"INSTALL {ext}")
            con.execute(f"LOAD {ext}")


def _sql_str(s: str | Path) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def connect(read_only: bool = False,
            snapshot: int | None = None,
            catalog: str | os.PathLike | None = None,
            data: str | os.PathLike | None = None,
            create: bool = False) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB with the lake attached as ``lake`` and USE'd.

    read_only  attach READ_ONLY (exporters, QA, anything that only reads).
    snapshot   attach at ``SNAPSHOT_VERSION n`` — always read-only.
    catalog    path to the SQLite catalog (default: $LTO_LAKE_CATALOG or
               db/lto_catalog.sqlite).
    data       data directory (default: $LTO_LAKE_DATA or <catalog dir>/lake).
    create     allow attaching a catalog that does not exist yet, which
               creates an empty lake. Only the rebuild should pass this.
    """
    cat = catalog_path(catalog)
    dat = data_path(catalog, data)
    if not cat.exists() and not create:
        raise LakeNotFound(
            f"DuckLake catalog not found: {cat}\n"
            f"  Build it first:  python scripts/rebuild_lake_from_parquet.py"
            + (f" --catalog {cat}" if cat != DEFAULT_CATALOG.resolve() else ""))
    cat.parent.mkdir(parents=True, exist_ok=True)
    if not (read_only or snapshot is not None):
        dat.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    _load_extensions(con)
    opts = [f"DATA_PATH {_sql_str(str(dat) + '/')}", "OVERRIDE_DATA_PATH true"]
    if read_only or snapshot is not None:
        opts.append("READ_ONLY")
    if snapshot is not None:
        opts.append(f"SNAPSHOT_VERSION {int(snapshot)}")
    con.execute(f"ATTACH {_sql_str('ducklake:sqlite:' + str(cat))} AS {LAKE} "
                f"({', '.join(opts)})")
    con.execute(f"USE {LAKE}")
    return con


def add_argparse_catalog(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add ``--catalog`` / ``--lake-data`` to a script's argument parser.

    Both default to None so connect() falls through to the env vars and
    then the repo defaults. Use as::

        lto_db.add_argparse_catalog(ap)
        args = ap.parse_args()
        con = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    """
    parser.add_argument(
        "--catalog", type=Path, default=None,
        help=f"DuckLake SQLite catalog (default: ${ENV_CATALOG} or "
             f"{DEFAULT_CATALOG.relative_to(ROOT)})")
    parser.add_argument(
        "--lake-data", type=Path, default=None,
        help=f"DuckLake data directory (default: ${ENV_DATA} or "
             f"<catalog dir>/lake)")
    return parser


# ---------------------------------------------------------------------------
# Small query helpers (always drain the result)
# ---------------------------------------------------------------------------

def rows(con, sql: str, params: Sequence | None = None) -> list[tuple]:
    return con.execute(sql, list(params or [])).fetchall()


def scalar(con, sql: str, params: Sequence | None = None):
    """First column of the first row, or None. Drains the result."""
    r = con.execute(sql, list(params or [])).fetchall()
    return r[0][0] if r else None


def table_exists(con, table: str, catalog: str = LAKE) -> bool:
    return bool(scalar(
        con,
        "SELECT count(*) FROM duckdb_tables() WHERE database_name = ? "
        "AND schema_name = 'main' AND table_name = ?", [catalog, table])) or bool(scalar(
        con,
        "SELECT count(*) FROM duckdb_views() WHERE database_name = ? "
        "AND schema_name = 'main' AND view_name = ?", [catalog, table]))


def lake_tables(con, catalog: str = LAKE) -> list[str]:
    return [r[0] for r in rows(
        con, "SELECT table_name FROM duckdb_tables() WHERE database_name = ? "
             "AND schema_name = 'main' ORDER BY table_name", [catalog])]


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Merged facilities
# ---------------------------------------------------------------------------

FACILITY_MERGE_LOG = ROOT / "data" / "seed" / "facility_merge_log.csv"
_facility_redirects: dict[Path, dict[str, str]] = {}


def facility_merge_redirects(path: Path = FACILITY_MERGE_LOG) -> dict[str, str]:
    """merged_id -> the facility_id it was merged into (merge_facilities.py's
    log), closed transitively. A seed CSV, override file or research batch
    written before a merge still names the merged id; loaders send it to
    the kept facility instead of failing on it or re-creating it. ingest.py
    is the exception: it drops a raw record whose id was merged away (its
    facets would overwrite the kept facility's)."""
    key = Path(path).resolve()
    if key not in _facility_redirects:
        m: dict[str, str] = {}
        if key.exists():
            with key.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if r.get("merged_id") and r.get("kept_id"):
                        m[r["merged_id"].strip()] = r["kept_id"].strip()
        for k in list(m):
            seen = {k}
            while m[k] in m and m[k] not in seen:
                seen.add(m[k])
                m[k] = m[m[k]]
        _facility_redirects[key] = m
    return _facility_redirects[key]


def canonical_facility_id(fid: str | None) -> str | None:
    """The facility a (possibly merged-away) facility_id now lives under."""
    if not fid:
        return fid
    fid = fid.strip()
    return facility_merge_redirects().get(fid, fid)


# ---------------------------------------------------------------------------
# Merged funders
# ---------------------------------------------------------------------------

FUNDER_MERGE_LOG = ROOT / "data" / "seed" / "funder_merge_log.csv"
_funder_redirects: dict[Path, tuple[dict[str, str], dict[str, str]]] = {}


def funder_name_ids(name: str | None) -> list[str]:
    """Every id a writer mints for a funder name: the sha1 family (ingest.py,
    load_lto_funding.py) and the blake2b family (fetch_funding_nsf /
    _usaspending, load_agency_budgets, fetch_funding_990), both over
    lower(strip(name)), first 16 hex characters."""
    key = (name or "").strip().lower()
    if not key:
        return []
    return [hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
            hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest()]


def funder_merge_redirects(path: Path = FUNDER_MERGE_LOG) -> dict[str, str]:
    """retired funder id -> the funder_id it was merged into
    (merge_funders.py's log), closed transitively. Keys are each merged id
    plus both families' ids for the merged name, the log's aliases and the
    kept name (so 'NSF' minted by ingest, 'Environmental Protection Agency'
    minted by the USAspending fetcher, or the survivor's own name minted by
    the other hash family all land on the survivor)."""
    return _funder_redirect_maps(path)[0]


def _funder_redirect_maps(path: Path = FUNDER_MERGE_LOG
                          ) -> tuple[dict[str, str], dict[str, str]]:
    key = Path(path).resolve()
    if key not in _funder_redirects:
        m: dict[str, str] = {}
        names: dict[str, str] = {}
        if key.exists():
            with key.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    kept, merged = (r.get("kept_id") or "").strip(), (r.get("merged_id") or "").strip()
                    if not (kept and merged):
                        continue
                    names[kept] = (r.get("kept_name") or "").strip()
                    aliases = [a for a in (r.get("aliases") or "").split("|") if a.strip()]
                    for n in [r.get("merged_name"), r.get("kept_name"), *aliases]:
                        for i in funder_name_ids(n):
                            if i != kept:
                                m.setdefault(i, kept)
                    m[merged] = kept
        for k in list(m):
            seen = {k}
            while m[k] in m and m[k] not in seen:
                seen.add(m[k])
                m[k] = m[m[k]]
        _funder_redirects[key] = (m, names)
    return _funder_redirects[key]


def canonical_funder_id(fid: str | None) -> str | None:
    """The funder a (possibly merged-away) funder_id now lives under."""
    if not fid:
        return fid
    fid = fid.strip()
    return funder_merge_redirects().get(fid, fid)


def canonical_funder(fid: str, name: str | None) -> tuple[str, str | None]:
    """(funder_id, name) a writer should use for the funder it minted as
    ``fid`` from ``name``: a merged-away id is sent to its survivor and the
    survivor's name replaces the retired one, so an upsert neither
    re-creates the merged funder nor renames the survivor."""
    m, names = _funder_redirect_maps()
    keep = m.get(fid.strip(), fid.strip()) if fid else fid
    if keep != fid and names.get(keep):
        return keep, names[keep]
    return keep, name


def latest_snapshot(con, catalog: str = LAKE) -> dict:
    """The lake's newest snapshot: id, time (VARCHAR), author, message."""
    r = rows(con, f"""SELECT snapshot_id, CAST(snapshot_time AS VARCHAR),
                             author, commit_message, commit_extra_info
                      FROM {catalog}.snapshots()
                      ORDER BY snapshot_id DESC LIMIT 1""")
    if not r:
        return {}
    sid, t, author, msg, extra = r[0]
    return {"snapshot_id": sid, "snapshot_time": t, "author": author,
            "commit_message": msg, "commit_extra_info": extra}


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def _default_author() -> str:
    return os.environ.get("LTO_AUTHOR") or os.environ.get("USER") or "lto"


def _attached_catalog(con) -> tuple[Path | None, bool]:
    """(catalog path, read_only) of the lake attached to ``con``."""
    r = rows(con, "SELECT path, readonly FROM duckdb_databases() "
                  "WHERE database_name = ?", [LAKE])
    if not r or not r[0][0]:
        return None, True
    path, ro = r[0]
    if path.startswith("sqlite:"):
        path = path[len("sqlite:"):]
    return Path(path), bool(ro)


@contextmanager
def _writer_lock(con) -> Iterator[None]:
    """Hold the catalog's exclusive writer lock (no-op for a read-only lake)."""
    cat, ro = _attached_catalog(con)
    if cat is None or ro:
        yield
        return
    lp = cat.with_name(cat.name + ".lock")
    lp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lp, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[lock] another process is writing to {cat.name}; waiting ...",
                  file=sys.stderr, flush=True)
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextmanager
def transaction(con, message: str, author: str | None = None,
                extra_info: str | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    """One snapshot, with a commit message, for everything in the block.

    Rolls back on any exception (including KeyboardInterrupt) and
    re-raises. A block that changes nothing commits nothing — no empty
    snapshot is written. ``message`` should start with the script name,
    e.g. ``"load_arid: 26 people, 9 projects"``.

    Lake writers are serialised: the block runs under an exclusive
    ``flock`` on ``<catalog>.lock``, taken before ``BEGIN`` (so the
    transaction's snapshot includes every earlier writer's commit) and
    released after ``COMMIT``/``ROLLBACK``. A second writer waits.
    """
    with _writer_lock(con):
        con.execute("BEGIN TRANSACTION")
        try:
            yield con
            con.execute(f"CALL {LAKE}.set_commit_message(?, ?, extra_info => ?)",
                        [author or _default_author(), message, extra_info])
            con.execute("COMMIT")
        except BaseException:
            try:
                con.execute("ROLLBACK")
            except duckdb.Error:
                pass
            raise


# ---------------------------------------------------------------------------
# Upsert (replaces INSERT OR REPLACE / INSERT OR IGNORE / ON CONFLICT)
# ---------------------------------------------------------------------------

_SELECT_RE = re.compile(r"^\s*(\(|select\b|with\b|from\b|values\b|table\b)", re.I)


def _columns_of(con, relation_sql: str, params: Sequence | None = None) -> list[str]:
    cur = con.execute(f"SELECT * FROM {relation_sql} AS __r LIMIT 0", list(params or []))
    names = [d[0] for d in cur.description]
    cur.fetchall()
    return names


def create_temp_like(con, name: str, select_sql: str,
                     params: Sequence | None = None) -> list[str]:
    """Create (or replace) an EMPTY TEMP table shaped like ``select_sql``.

    Use this instead of ``CREATE TEMP TABLE t AS SELECT ... LIMIT 0``. In
    DuckDB 2.0.0 a DuckDB-native (TEMP or in-memory) table created by an
    empty CTAS inside a transaction and then bulk-filled by one
    ``INSERT ... SELECT`` of >= 122,880 rows (one row group) -- from a lake
    table, another TEMP table or a registered Arrow/pandas object -- reads
    back as 0 rows: count(*) and every later scan (merge_upsert's own copy,
    DISTINCT ON) see nothing, so the write silently drops the batch.
    ``executemany`` fills and DuckLake tables are not affected, and nor are
    tables declared with explicit column DDL, which is what this builds
    from ``DESCRIBE``. Returns the column names, in order.
    """
    cur = con.execute(f"DESCRIBE {select_sql}", list(params or []))
    cols = [(r[0], r[1]) for r in cur.fetchall()]
    con.execute(f"CREATE OR REPLACE TEMP TABLE {qident(name)} ("
                + ", ".join(f"{qident(n)} {t}" for n, t in cols) + ")")
    return [n for n, _ in cols]


_merge_seq = 0


def merge_upsert(con, table: str, key_cols: Sequence[str], source: str,
                 update_cols: Sequence[str] | None = None,
                 coalesce: bool | Sequence[str] = False,
                 fill: Sequence[str] = (),
                 insert_only: bool = False,
                 order_by: str | None = None,
                 extra_set: dict[str, str] | None = None,
                 params: Sequence | None = None) -> dict:
    """``MERGE INTO <table>`` from a de-duplicated source. Returns counts.

    table        target table in the lake (unqualified).
    key_cols     the logical primary key (from schema.sql) to match on.
                 NULL keys are rejected: they can never match, so they
                 would be inserted again on every run.
    source       a SELECT/WITH/FROM/VALUES query, or the name of a
                 (TEMP) table holding staged rows. Only columns that also
                 exist in the target are used; extras (e.g. a ``_seq``
                 ordering column) are ignored.
    update_cols  columns to overwrite on a match (default: every shared
                 non-key column).
    coalesce     True, or a list of columns: ``col = COALESCE(s.col,
                 t.col)`` so a NULL in the source never erases a value
                 already in the lake (the old ``ON CONFLICT DO UPDATE SET
                 x = COALESCE(excluded.x, x)`` idiom).
    fill         columns that are only filled in: ``col = COALESCE(t.col,
                 s.col)``, so a value already in the lake (e.g. one a
                 research batch wrote with its source) always wins over
                 the source's. Takes precedence over ``coalesce``.
    insert_only  only insert keys that are absent (the old INSERT OR
                 IGNORE / ON CONFLICT DO NOTHING).
    order_by     which duplicate wins: ``DISTINCT ON (keys)`` keeps the
                 first row under ``ORDER BY keys, <order_by>``. Without
                 it the survivor among duplicate source keys is arbitrary.
                 For the old per-row INSERT OR REPLACE behaviour (last
                 write wins) stage a ``_seq`` column and pass
                 ``order_by="_seq DESC"``.
    extra_set    extra assignments applied on a match, e.g.
                 ``{"updated_at": "now()"}``.
    params       bind parameters for ``?`` placeholders in a query
                 ``source`` (a single-row upsert: ``"SELECT ? AS person_id,
                 ? AS name"`` with ``params=[pid, name]``).

    Returns ``{"source_rows", "unique_keys", "matched", "inserted"}``.
    "matched" counts keys that already existed (updated, unless
    insert_only). Must run inside ``transaction()`` if the caller wants
    the upsert and its staging to be one snapshot.
    """
    global _merge_seq
    key_cols = list(key_cols)
    src_rel = f"({source})" if _SELECT_RE.match(source) else source
    src_cols = _columns_of(con, src_rel, params)
    tgt_cols = _columns_of(con, qident(table))
    shared = [c for c in src_cols if c in tgt_cols]
    missing_keys = [k for k in key_cols if k not in shared]
    if missing_keys:
        raise ValueError(f"merge_upsert({table}): key column(s) {missing_keys} "
                         f"not in both source and target")

    _merge_seq += 1
    stage = f"__merge_src_{_merge_seq}"
    keys = ", ".join(qident(k) for k in key_cols)
    order = f"ORDER BY {keys}" + (f", {order_by}" if order_by else "")
    con.execute(f"CREATE OR REPLACE TEMP TABLE {stage} AS "
                f"SELECT * FROM {src_rel} AS __s", list(params or []))
    try:
        null_keys = scalar(con, f"SELECT count(*) FROM {stage} WHERE "
                                + " OR ".join(f"{qident(k)} IS NULL" for k in key_cols))
        if null_keys:
            raise ValueError(f"merge_upsert({table}): {null_keys} source row(s) "
                             f"have a NULL in key {key_cols}")
        n_src = scalar(con, f"SELECT count(*) FROM {stage}")
        con.execute(f"CREATE OR REPLACE TEMP TABLE {stage}_d AS "
                    f"SELECT DISTINCT ON ({keys}) * FROM {stage} {order}")
        n_keys = scalar(con, f"SELECT count(*) FROM {stage}_d")
        on = " AND ".join(f"t.{qident(k)} = s.{qident(k)}" for k in key_cols)
        n_matched = scalar(con, f"SELECT count(*) FROM {stage}_d s WHERE EXISTS "
                                f"(SELECT 1 FROM {qident(table)} t WHERE {on})")

        ins_cols = ", ".join(qident(c) for c in shared)
        ins_vals = ", ".join(f"s.{qident(c)}" for c in shared)
        clauses = []
        if not insert_only:
            upd = list(update_cols) if update_cols is not None else \
                [c for c in shared if c not in key_cols]
            bad = [c for c in upd if c not in shared]
            if bad:
                raise ValueError(f"merge_upsert({table}): update column(s) {bad} "
                                 f"not in both source and target")
            co = set(upd) if coalesce is True else set(coalesce or [])
            fi = set(fill or [])
            sets = [f"{qident(c)} = COALESCE(t.{qident(c)}, s.{qident(c)})" if c in fi
                    else f"{qident(c)} = COALESCE(s.{qident(c)}, t.{qident(c)})" if c in co
                    else f"{qident(c)} = s.{qident(c)}" for c in upd]
            sets += [f"{qident(c)} = {expr}" for c, expr in (extra_set or {}).items()]
            if sets:
                clauses.append("WHEN MATCHED THEN UPDATE SET " + ", ".join(sets))
        clauses.append(f"WHEN NOT MATCHED THEN INSERT ({ins_cols}) VALUES ({ins_vals})")
        con.execute(f"MERGE INTO {qident(table)} t USING {stage}_d s ON {on} "
                    + " ".join(clauses))
    finally:
        # A failed statement inside transaction() aborts it; a DROP then
        # raises "transaction is aborted" and would mask the real error.
        for t in (stage, f"{stage}_d"):
            try:
                con.execute(f"DROP TABLE IF EXISTS {t}")
            except duckdb.Error:
                pass
    return {"source_rows": n_src, "unique_keys": n_keys,
            "matched": n_matched, "inserted": n_keys - n_matched}


# ---------------------------------------------------------------------------
# Derived tables (compute_* / build_mvg_layout outputs)
# ---------------------------------------------------------------------------

def replace_table(con, table: str, select_sql: str) -> int:
    """``CREATE OR REPLACE TABLE <table> AS <select_sql>`` in the lake.

    For derived tables that a script recomputes wholesale. Drops a VIEW of
    the same name first (DuckDB refuses ``DROP VIEW`` on a table and
    ``CREATE OR REPLACE TABLE`` over a view, so the type is checked).
    The new table has no NOT NULL/DEFAULT clauses — fine for derived
    tables, NOT for schema.sql tables (use DELETE + INSERT, or
    merge_upsert, for those so their column definitions survive).
    Returns the new row count. ``select_sql`` may read a registered
    DataFrame (``con.register("df", polars_or_pandas_df)``).
    """
    if scalar(con, "SELECT count(*) FROM duckdb_views() WHERE database_name = ? "
                   "AND schema_name = 'main' AND view_name = ?", [LAKE, table]):
        con.execute(f"DROP VIEW {qident(table)}")
    con.execute(f"CREATE OR REPLACE TABLE {qident(table)} AS {select_sql}")
    return scalar(con, f"SELECT count(*) FROM {qident(table)}")


def ensure_schema(con, schema_path: Path = SCHEMA_SQL) -> list[str]:
    """Bring the lake's tables/columns/views up to schema.sql, in place.

    When someone adds a column or a table to schema.sql, an existing lake
    does not have it, and rebuilding from parquet would throw away any
    lake changes not yet exported. This adds what is missing instead:

      * a spec table absent from the lake  -> created column-only;
      * a spec column absent from a table  -> ALTER TABLE ADD COLUMN with
        its type and DEFAULT (NOT NULL is not added to a populated table;
        the integrity check reports NULLs in it);
      * every spec view                    -> CREATE OR REPLACE VIEW.

    Never drops or retypes anything. Returns a list of what it changed.
    Run it inside transaction() so the migration is one snapshot.
    """
    sp = spec(schema_path)
    present = set(lake_tables(con))
    changes: list[str] = []
    for t in sp["tables"]:
        if t not in present:
            con.execute(column_only_ddl(t, schema_path))
            changes.append(f"created table {t}")
            continue
        have = set(_columns_of(con, qident(t)))
        for name, typ, _nullable, default in sp["columns"][t]:
            if name not in have:
                d = f" DEFAULT {default}" if default is not None else ""
                con.execute(f"ALTER TABLE {qident(t)} ADD COLUMN {qident(name)} {typ}{d}")
                changes.append(f"added column {t}.{name} {typ}")
    for v, sql in sp["views"]:
        con.execute(re.sub(r"^\s*CREATE\s+(OR\s+REPLACE\s+)?VIEW", "CREATE OR REPLACE VIEW",
                           sql, count=1, flags=re.I))
    return changes


# ---------------------------------------------------------------------------
# The logical schema (schema.sql in an in-memory spec database)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def _spec(schema_text: str) -> dict:
    """Execute schema.sql in a private in-memory DB and read its catalog.

    Cached per schema text, so repeated calls in one process are free and
    an edited schema.sql is picked up on the next process start.
    """
    c = duckdb.connect()
    try:
        c.execute(schema_text)
        tables = [r[0] for r in c.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'memory' "
            "ORDER BY table_oid").fetchall()]
        cols: dict[str, list[tuple]] = {t: [] for t in tables}
        for t, name, typ, nullable, default in c.execute(
                "SELECT table_name, column_name, data_type, is_nullable, column_default "
                "FROM duckdb_columns() WHERE database_name = 'memory' "
                "AND table_name IN (SELECT table_name FROM duckdb_tables() "
                "                   WHERE database_name = 'memory') "
                "ORDER BY table_name, column_index").fetchall():
            cols[t].append((name, typ, nullable, default))
        views = [(v, sql) for v, sql in c.execute(
            "SELECT view_name, sql FROM duckdb_views() WHERE database_name = 'memory' "
            "AND NOT internal ORDER BY view_oid").fetchall()]
        cons = [dict(table=t, kind=k, columns=list(cc), ref_table=rt,
                     ref_columns=list(rc or []), expression=e)
                for t, k, cc, rt, rc, e in c.execute(
                    "SELECT table_name, constraint_type, constraint_column_names, "
                    "referenced_table, referenced_column_names, expression "
                    "FROM duckdb_constraints() WHERE database_name = 'memory' "
                    "AND constraint_type IN ('PRIMARY KEY','UNIQUE','FOREIGN KEY',"
                    "'CHECK','NOT NULL') "
                    "ORDER BY table_name, constraint_type, constraint_index").fetchall()]
    finally:
        c.close()
    pks = {d["table"]: d["columns"] for d in cons if d["kind"] == "PRIMARY KEY"}
    return {"tables": tables, "columns": cols, "views": views,
            "constraints": cons, "primary_keys": pks}


def spec(schema_path: Path = SCHEMA_SQL) -> dict:
    """Logical schema from schema.sql: tables (creation order), columns
    ``(name, type, nullable, default)``, views ``(name, sql)`` in creation
    order, constraints, and primary keys by table."""
    return _spec(Path(schema_path).read_text())


def column_only_ddl(table: str, schema_path: Path = SCHEMA_SQL) -> str:
    """CREATE TABLE for the lake: names, types, NOT NULL, DEFAULT only."""
    cols = spec(schema_path)["columns"][table]
    body = ",\n  ".join(
        f"{qident(n)} {typ}" + ("" if nullable else " NOT NULL")
        + (f" DEFAULT {default}" if default is not None else "")
        for n, typ, nullable, default in cols)
    return f"CREATE TABLE {qident(table)} (\n  {body}\n)"


def primary_key(table: str, schema_path: Path = SCHEMA_SQL) -> list[str] | None:
    return spec(schema_path)["primary_keys"].get(table)


# ---------------------------------------------------------------------------
# Integrity (what the lake cannot enforce)
# ---------------------------------------------------------------------------

def _constraint_sql(d: dict, catalog: str) -> tuple[str, str]:
    """(count_sql, sample_sql) for one constraint."""
    t = f"{catalog}.main.{qident(d['table'])}"
    cols = d["columns"]
    q = ", ".join(qident(c) for c in cols)
    k = d["kind"]
    if k in ("PRIMARY KEY", "UNIQUE"):
        # SQL UNIQUE allows repeated NULLs; a PK column is NOT NULL anyway.
        where = (" WHERE " + " AND ".join(f"{qident(c)} IS NOT NULL" for c in cols)
                 if k == "UNIQUE" else "")
        inner = f"SELECT {q}, count(*) AS n FROM {t}{where} GROUP BY ALL HAVING count(*) > 1"
        return f"SELECT count(*) FROM ({inner})", f"{inner} ORDER BY ALL LIMIT 3"
    if k == "FOREIGN KEY":
        rt = f"{catalog}.main.{qident(d['ref_table'])}"
        on = " AND ".join(f"p.{qident(b)} = c.{qident(a)}"
                          for a, b in zip(cols, d["ref_columns"]))
        notnull = " AND ".join(f"c.{qident(a)} IS NOT NULL" for a in cols)
        body = (f"FROM {t} c WHERE {notnull} AND NOT EXISTS "
                f"(SELECT 1 FROM {rt} p WHERE {on})")
        sel = ", ".join(f"c.{qident(a)}" for a in cols)
        return (f"SELECT count(*) {body}",
                f"SELECT DISTINCT {sel} {body} ORDER BY ALL LIMIT 3")
    if k == "CHECK":
        body = f"FROM {t} WHERE NOT ({d['expression']})"
        return f"SELECT count(*) {body}", f"SELECT DISTINCT {q} {body} ORDER BY ALL LIMIT 3"
    if k == "NOT NULL":
        body = f"FROM {t} WHERE {qident(cols[0])} IS NULL"
        return f"SELECT count(*) {body}", f"SELECT 'NULL' {body} LIMIT 1"
    raise ValueError(k)


def _c(table, kind, columns, ref_table=None, ref_columns=None, origin="derived"):
    return dict(table=table, kind=kind, columns=list(columns), ref_table=ref_table,
                ref_columns=list(ref_columns or []), expression=None, origin=origin)


# Keys of the derived tables (compute_* / build_mvg_layout outputs). They
# are not in schema.sql — each is recreated wholesale with replace_table —
# but the views and caches join on them, so a duplicate key multiplies rows
# in people_cards.json and an orphan points the site at nothing. Checked
# only when the table exists in the lake.
DERIVED_CONSTRAINTS: list[dict] = [
    _c("person_primary_groups", "PRIMARY KEY", ["person_id"]),
    _c("person_primary_groups", "FOREIGN KEY", ["person_id"], "people", ["person_id"]),
    _c("person_primary_groups", "FOREIGN KEY", ["primary_area_id"],
       "research_areas", ["area_id"]),
    _c("facility_primary_groups", "PRIMARY KEY", ["facility_id"]),
    _c("facility_primary_groups", "FOREIGN KEY", ["facility_id"],
       "facilities", ["facility_id"]),
    _c("facility_primary_groups", "FOREIGN KEY", ["primary_area_id"],
       "research_areas", ["area_id"]),
    _c("research_areas_active", "PRIMARY KEY", ["area_id"]),
    _c("person_area_metrics", "PRIMARY KEY", ["person_id", "area_id"]),
    _c("person_area_metrics", "FOREIGN KEY", ["area_id"], "research_areas", ["area_id"]),
    _c("facility_area_funding", "PRIMARY KEY", ["area_id", "facility_id"]),
    _c("facility_area_funding", "FOREIGN KEY", ["facility_id"],
       "facilities", ["facility_id"]),
    _c("funder_area_funding", "PRIMARY KEY", ["area_id", "funder_id"]),
    _c("funder_area_funding", "FOREIGN KEY", ["funder_id"], "funders", ["funder_id"]),
    _c("area_coverage_matrix", "PRIMARY KEY", ["area_id", "dim", "bucket"]),
    _c("mvg_node_layout", "PRIMARY KEY", ["node_uid"]),
    _c("mvg_node_layout", "FOREIGN KEY", ["source_id"], "people", ["person_id"]),
    # No FK: rows point at archive-tier registry ids, which are not shipped.
    _c("scholar_area_assignments", "PRIMARY KEY", ["canonical_id"]),
]

# References schema.sql leaves undeclared on purpose (the project and
# registry tables are bulk-loaded in any order, and the old DuckDB file
# blocked updating a referenced parent). Not declared is not unchecked:
# they are verified here like any foreign key. person_identity_source's
# canonical_id is left out — most of its rows point at archive-tier ids
# by design.
SOFT_REFERENCES: list[dict] = [
    _c(t, "FOREIGN KEY", [c], rt, [rc], origin="soft")
    for t, c, rt, rc in (
        ("projects", "parent_project_id", "projects", "project_id"),
        ("projects", "lead_facility_id", "facilities", "facility_id"),
        ("project_personnel", "project_id", "projects", "project_id"),
        ("project_personnel", "person_id", "people", "person_id"),
        ("project_facilities", "project_id", "projects", "project_id"),
        ("project_facilities", "facility_id", "facilities", "facility_id"),
        ("registry_facilities", "facility_id", "facilities", "facility_id"),
        ("registry_facilities", "canonical_id", "person_registry", "canonical_id"),
        ("person_registry", "person_id", "people", "person_id"),
    )
]


def known_tables(schema_path: Path = SCHEMA_SQL) -> set[str]:
    """Every table name integrity_violations() knows how to check."""
    return set(spec(schema_path)["tables"]) | {d["table"] for d in DERIVED_CONSTRAINTS}


def _lake_columns(con, catalog: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for t, c, typ in rows(con, "SELECT table_name, column_name, data_type "
                               "FROM duckdb_columns() WHERE database_name = ? "
                               "AND schema_name = 'main' "
                               "AND table_name IN (SELECT table_name FROM duckdb_tables() "
                               "  WHERE database_name = ? AND schema_name = 'main')",
                          [catalog, catalog]):
        out.setdefault(t, {})[c] = typ
    return out


def integrity_violations(con, tables: Iterable[str] | None = None,
                         catalog: str = LAKE,
                         include_not_null: bool = True,
                         schema_path: Path = SCHEMA_SQL) -> list[dict]:
    """Check every constraint the lake cannot enforce; return violations.

    Covers PRIMARY KEY and UNIQUE (duplicate keys), FOREIGN KEY (child
    rows whose non-NULL key has no parent — NULL references are allowed,
    as in SQL), CHECK (rows where the expression is false; NULL passes, as
    in SQL) and NOT NULL (a table recreated with CREATE OR REPLACE loses
    the lake's own NOT NULL enforcement) from schema.sql; plus the derived
    tables' keys (``DERIVED_CONSTRAINTS``, when the table exists) and the
    undeclared soft references (``SOFT_REFERENCES``).

    It also compares each schema table's columns with schema.sql and
    reports ``MISSING COLUMN``, ``EXTRA COLUMN`` and ``COLUMN TYPE``; a
    constraint whose columns are missing is reported that way instead of
    being run. A spec table missing from the lake is ``MISSING TABLE``.

    tables   limit to constraints on these tables, plus schema and soft
             foreign keys that *reference* them (a parent change can orphan
             a child; derived tables excepted, see below). A name
             that is neither a schema.sql table nor a derived table raises
             ValueError (a typo would otherwise check nothing).
    Returns one dict per violated constraint: table, kind, columns,
    ref_table, count, sample (up to 3 offending values), origin
    ("schema" | "derived" | "soft").
    """
    sp = spec(schema_path)
    if tables is not None:
        tables = list(tables)
        unknown = set(tables) - known_tables(schema_path)
        if unknown:
            raise ValueError(f"integrity_violations: unknown table(s) {sorted(unknown)}")
    lake_cols = _lake_columns(con, catalog)
    present = set(lake_cols)
    want = set(tables) if tables is not None else None
    out: list[dict] = []

    def add(table, kind, columns=(), ref_table=None, count=1, sample=(), origin="schema"):
        out.append(dict(table=table, kind=kind, columns=list(columns), ref_table=ref_table,
                        count=count, sample=list(sample), origin=origin))

    for t in sp["tables"]:
        if want is not None and t not in want:
            continue
        if t not in present:
            add(t, "MISSING TABLE")
            continue
        have, spec_cols = lake_cols[t], {n: typ for n, typ, _, _ in sp["columns"][t]}
        for n, typ in spec_cols.items():
            if n not in have:
                add(t, "MISSING COLUMN", [n])
            elif have[n] != typ:
                add(t, "COLUMN TYPE", [n], sample=[(have[n], f"schema.sql: {typ}")])
        for n in have:
            if n not in spec_cols:
                add(t, "EXTRA COLUMN", [n], sample=[(have[n],)])

    cons = [dict(d, origin="schema") for d in sp["constraints"]]
    cons += [d for d in DERIVED_CONSTRAINTS if d["table"] in present]
    cons += SOFT_REFERENCES
    for d in cons:
        if d["kind"] == "NOT NULL" and not include_not_null:
            continue
        if want is not None and d["table"] not in want and (
                d["ref_table"] not in want or d["origin"] == "derived"):
            # A derived table's references are checked when the table
            # itself is named (its producer) or by a full check (qa.py),
            # not when a parent changes: a loader that drops a person
            # cannot also recompute every derived table, and qa.py makes
            # the stale derived table fail before anything is exported.
            continue
        if d["table"] not in present or (d["ref_table"] and d["ref_table"] not in present):
            continue                      # reported above as MISSING TABLE
        if not (set(d["columns"]) <= set(lake_cols[d["table"]])
                and (not d["ref_table"]
                     or set(d["ref_columns"]) <= set(lake_cols[d["ref_table"]]))):
            if d["origin"] != "schema":
                add(d["table"], "MISSING COLUMN", d["columns"], d["ref_table"],
                    origin=d["origin"])
            continue                      # schema columns: reported above
        count_sql, sample_sql = _constraint_sql(d, catalog)
        n = scalar(con, count_sql)
        if n:
            add(d["table"], d["kind"], d["columns"], d["ref_table"], n,
                rows(con, sample_sql), d["origin"])
    return out


def constraint_count(include_not_null: bool = True,
                     schema_path: Path = SCHEMA_SQL) -> int:
    """schema.sql constraints + derived-table keys + soft references."""
    return (sum(1 for d in spec(schema_path)["constraints"]
                if include_not_null or d["kind"] != "NOT NULL")
            + len(DERIVED_CONSTRAINTS) + len(SOFT_REFERENCES))


def format_violations(violations: list[dict]) -> str:
    lines = []
    for v in violations:
        ref = f" -> {v['ref_table']}" if v.get("ref_table") else ""
        tag = {"derived": " (derived)", "soft": " (soft ref)"}.get(v.get("origin"), "")
        lines.append(f"{v['table']} {v['kind']}{tag} {v['columns']}{ref}: "
                     f"{v['count']} violating row(s/keys); e.g. {v['sample'][:3]}")
    return "\n".join(lines)


def assert_integrity(con, tables: Iterable[str] | None = None,
                     catalog: str = LAKE) -> None:
    """Raise IntegrityError if any constraint is violated.

    Call it as the last statement inside ``transaction()``: the exception
    rolls the whole loader run back, so a bad batch never lands.
    """
    v = integrity_violations(con, tables, catalog=catalog)
    if v:
        raise IntegrityError(v)
