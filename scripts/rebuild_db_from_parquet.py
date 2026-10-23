#!/usr/bin/env python3
"""DEPRECATED — use scripts/rebuild_lake_from_parquet.py.

``db/lto.duckdb`` is retired. The store of record is now a DuckLake
(``db/lto_catalog.sqlite`` + ``db/lake/``, see ``scripts/lto_db.py``),
rebuilt from the committed ``public/parquet/`` by
``rebuild_lake_from_parquet.py``. This shim keeps old muscle memory, CI
steps and docs working: it forwards ``--parquet`` and runs the new
rebuild. The old ``--db`` option is accepted and ignored with a warning
(use ``--catalog`` or ``$LTO_LAKE_CATALOG`` instead).
"""
from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=None, help="ignored (db/lto.duckdb is retired)")
    args, rest = ap.parse_known_args()
    print("[deprecated] rebuild_db_from_parquet.py -> rebuild_lake_from_parquet.py "
          "(db/lto.duckdb is retired; the store is the DuckLake in db/)", file=sys.stderr)
    if args.db is not None:
        print(f"[deprecated] --db {args.db} ignored; use --catalog or $LTO_LAKE_CATALOG",
              file=sys.stderr)
    sys.argv = [str(HERE / "rebuild_lake_from_parquet.py"), *rest]
    try:
        runpy.run_path(str(HERE / "rebuild_lake_from_parquet.py"), run_name="__main__")
    except SystemExit as e:
        if isinstance(e.code, int) or e.code is None:
            return e.code or 0
        print(e.code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
