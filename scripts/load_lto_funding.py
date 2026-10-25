#!/usr/bin/env python3
"""Load Wave-H H-FUND-* JSON outputs into funders + funding_events.

Reads every `data/raw/H-FUND-*/funding_events.json` file and upserts into
the funders dimension and funding_events fact table. Idempotent on
event_id = sha1(funder||facility||award_id||fiscal_year).

Mirror of `load_lto_people.py` for the funding side. Companion to the
existing `fetch_funding_*.py` API-driven enrichers — those will run in
CI where api.nsf.gov / usaspending.gov are reachable.

One run is one DuckLake snapshot (scripts/lto_db.py): the funders and
the events are each written with one MERGE (a repeated key keeps its last
row, as INSERT OR REPLACE did). An event DuckDB used to reject (a date
that does not parse, an unknown facility) is checked first and skipped.

Usage::

    python scripts/load_lto_funding.py
    python scripts/load_lto_funding.py --catalog db/lto_catalog.sqlite --verbose
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402
from load_lto_archives import row_error  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"


def funder_id(name: str) -> str:
    return hashlib.sha1(name.strip().lower().encode("utf-8")).hexdigest()[:16]


def event_id(funder: str, facility: str, award: str | None, fy: int | None) -> str:
    key = f"{funder}|{facility}|{award or ''}|{fy or ''}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def resolve_facility(conn, name: str, acronym: str | None) -> str | None:
    if acronym:
        row = conn.execute(
            "SELECT facility_id FROM facilities WHERE upper(acronym) = upper(?) LIMIT 1",
            [acronym],
        ).fetchone()
        if row:
            return row[0]
    if not name:
        return None
    row = conn.execute(
        "SELECT facility_id FROM facilities WHERE lower(canonical_name) = lower(?) LIMIT 1",
        [name],
    ).fetchone()
    if row:
        return row[0]
    rows = conn.execute(
        "SELECT facility_id FROM facilities WHERE canonical_name ILIKE ? LIMIT 2",
        [f"%{name}%"],
    ).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return None
    candidates = conn.execute("SELECT facility_id, canonical_name FROM facilities").fetchall()
    name_to_row = {c[1]: c for c in candidates}
    best = process.extractOne(
        name, list(name_to_row.keys()),
        scorer=fuzz.token_set_ratio, score_cutoff=85,
    )
    if best:
        return name_to_row[best[0]][0]
    return None


FUNDER_COLS = ["funder_id", "name", "type", "country", "url", "notes"]
EVENT_COLS = ["event_id", "funder_id", "facility_id", "amount_usd", "amount_currency",
              "fiscal_year", "period_start", "period_end", "award_id", "award_title",
              "program", "relation", "source", "source_url", "retrieved_at",
              "confidence", "notes"]


def stage(conn, name: str, table: str, cols: list[str], rows: list[list]) -> None:
    """TEMP table typed like `table`'s `cols`, plus `_seq` in input order."""
    lto_db.create_temp_like(conn, name, f"SELECT {', '.join(cols)}, 0 AS _seq FROM {table}")
    if rows:
        conn.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * (len(cols) + 1))})",
                         [[*r, i] for i, r in enumerate(rows)])


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path, help="deprecated alias of --catalog")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # Pick up Wave-H first-pass + Loop-M (and any future *-FUND-*) extensions.
    files = sorted(set(
        list(RAW_DIR.glob("H-FUND-*/funding_events.json")) +
        list(RAW_DIR.glob("M-FUND-*/funding_events.json")) +
        list(RAW_DIR.glob("*/funding_events.json"))
    ))
    print(f"[load_lto_funding] reading {len(files)} agent files")

    inserted_events = 0
    inserted_funders = 0
    skipped = 0
    warnings: list[str] = []

    funder_rows: list[list] = []
    pending: list[tuple[str, list]] = []      # (funder name, event row)
    conn = lto_db.connect(catalog=args.catalog, data=args.lake_data)
    with lto_db.transaction(conn, f"load_lto_funding: funders + funding_events from "
                                  f"{len(files)} agent files"):
        for path in files:
            try:
                events = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                print(f"[skip] {path}: {e}", file=sys.stderr)
                continue
            agent = path.parent.name

            for ev in events:
                fname = (ev.get("funder_name") or "").strip()
                if not fname:
                    skipped += 1
                    continue
                fuid = funder_id(fname)
                # Upsert funder dimension (written below, before the events).
                funder_rows.append([
                    fuid, fname,
                    ev.get("funder_type"),
                    ev.get("funder_country") or "US",
                    ev.get("funder_url"),
                    ev.get("funder_notes"),
                ])
                inserted_funders += 1

                fac_id = resolve_facility(conn, ev.get("facility_canonical_name"), ev.get("facility_acronym"))
                if not fac_id:
                    skipped += 1
                    warnings.append(f"  no facility for {fname} → '{ev.get('facility_canonical_name')}'")
                    continue

                eid = event_id(fuid, fac_id, ev.get("award_id"), ev.get("fiscal_year"))
                pending.append((f"{fname}/{ev.get('facility_canonical_name')}", [
                    eid, fuid, fac_id,
                    ev.get("amount_usd"),
                    ev.get("amount_currency") or "USD",
                    ev.get("fiscal_year"),
                    ev.get("period_start"), ev.get("period_end"),
                    ev.get("award_id"), ev.get("award_title"), ev.get("program"),
                    ev.get("relation"), ev.get("source") or agent, ev.get("source_url"),
                    ev.get("retrieved_at") or "2026-05-05",
                    ev.get("confidence") or "medium",
                    ev.get("notes"),
                ]))

        # Funders first, so the events' funder_id check finds them.
        stage(conn, "_funders", "funders", FUNDER_COLS, funder_rows)
        f_stats = lto_db.merge_upsert(conn, "funders", ["funder_id"], "_funders",
                                      order_by="_seq DESC")
        event_rows: list[list] = []
        for label, row in pending:
            err = row_error(conn, "funding_events", dict(zip(EVENT_COLS, row)))
            if err:
                skipped += 1
                warnings.append(f"  insert failed for {label}: {err}")
            else:
                event_rows.append(row)
                inserted_events += 1
        stage(conn, "_events", "funding_events", EVENT_COLS, event_rows)
        e_stats = lto_db.merge_upsert(conn, "funding_events", ["event_id"], "_events",
                                      order_by="_seq DESC")
        lto_db.assert_integrity(conn, ["funders", "funding_events"])

    print(f"[load_lto_funding] funders {f_stats}; funding_events {e_stats}")
    print(f"[load_lto_funding] inserted {inserted_events} events, {inserted_funders} funder upserts, skipped {skipped}")
    if args.verbose and warnings:
        print("\n".join(warnings[:25]))
        if len(warnings) > 25:
            print(f"  … {len(warnings) - 25} more suppressed")

    # Coverage stats
    n_total = conn.execute("SELECT count(*) FROM funding_events").fetchone()[0]
    n_amt = conn.execute("SELECT count(*) FROM funding_events WHERE amount_usd IS NOT NULL").fetchone()[0]
    sum_amt = conn.execute("SELECT sum(amount_usd) FROM funding_events").fetchone()[0]
    n_fac = conn.execute("SELECT count(DISTINCT facility_id) FROM funding_events WHERE amount_usd IS NOT NULL").fetchone()[0]
    print(
        f"[load_lto_funding] coverage — {n_amt}/{n_total} events with amount_usd "
        f"(${(sum_amt or 0)/1e6:.1f}M total) across {n_fac} unique facilities"
    )
    conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
