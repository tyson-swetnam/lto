#!/usr/bin/env python3
"""Harvest LTO-topic works for the registry's core tier — the H8 step.

`harvest_runner.harvest()` is the engine (batched 50 authors per cursor,
resumable, request-budgeted); it has no CLI, and until now was driven by
hand from a throwaway shell. This is that driver, so the step is
reproducible and its scope is stated rather than remembered.

Scope is the CORE tier by default, and that is a cost decision, not a
preference. compute_registry_collaborations.py spends one request per
registry member; at 31k members that is three days of a 10k/day quota.
This path spends one request per PAGE of a 50-author batch, so the same
authors cost ~50x less — which is why the plan puts H8 before H9 and why
the collaboration graph should be built from what this harvests.

Output goes to the gitignored checkpoint dir
data/raw/oa_harvest/_state/harvest_{works,pairs}.parquet.d/, which
`validate_registry.py --stage match` reads to build coauthor_edges and
coauthor_candidates. Nothing here touches the DB.

Quota: the run stops at --request-budget (default 6,500, leaving room
under the 10k/day cap for the validate stages), and a batch cut short by
the budget is left unmarked so the next run re-attempts it. Re-run with
the same command after the daily reset to continue.

Usage::

    python scripts/harvest_core_works.py --dry-run
    python scripts/harvest_core_works.py --request-budget 6500
    python scripts/harvest_core_works.py --tier all --request-budget 2000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harvest_runner  # noqa: E402
import openalex_auth  # noqa: E402
from validate_registry import quota_remaining  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--tier", default="core", choices=["core", "all"],
                    help="'core' is the 2,000 shipped identities; 'all' is "
                         "every registry row with an OpenAlex id and will "
                         "span several quota days")
    ap.add_argument("--request-budget", type=int, default=6500)
    ap.add_argument("--per-author-cap", type=int, default=200,
                    help="works per author, most-cited first, so a truncated "
                         "author keeps their highest-signal collaborations")
    ap.add_argument("--quota-floor", type=int, default=800,
                    help="refuse to start if the key has less than this left")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the shard set and cost estimate, fetch nothing")
    args = ap.parse_args()

    openalex_auth.require_api_key()
    conn = duckdb.connect(str(args.db), read_only=True)
    where = "openalex_id IS NOT NULL AND openalex_id <> ''"
    if args.tier == "core":
        where += " AND tier = 'core'"
    shards = conn.execute(
        f"SELECT canonical_id, openalex_id, display_name FROM person_registry "
        f"WHERE {where} ORDER BY canonical_id").fetchdf()
    conn.close()

    total = len(shards)
    batches = -(-total // 50)
    print(f"[h8] {total:,} {args.tier}-tier author(s) with an OpenAlex id "
          f"→ {batches:,} batch(es) of 50")
    state = harvest_runner.load_state()
    done = len(state.get("done_batches") or [])
    if done:
        print(f"[h8] resuming: {done:,} batch(es) already complete, "
              f"{state.get('requests_used', 0):,} request(s) spent, "
              f"{state.get('works', 0):,} works / {state.get('pairs', 0):,} "
              f"pairs so far")

    if args.dry_run:
        print(f"[h8] dry run — would spend at most {args.request_budget:,} "
              f"request(s) this pass")
        return 0

    q = quota_remaining()
    if q is not None:
        print(f"[quota] {q:,} request(s) remaining today")
        if q < args.quota_floor:
            print(f"[h8] quota {q} is below the floor {args.quota_floor}; "
                  "wait for the daily reset", file=sys.stderr)
            return 3
    st = harvest_runner.harvest(
        pd.DataFrame({"openalex_id": shards.openalex_id}),
        per_author_cap=args.per_author_cap,
        request_budget=args.request_budget)
    cut = len(st.get("budget_cut_batches") or [])
    print(f"[h8] {st['works']:,} work(s), {st['pairs']:,} co-author pair(s), "
          f"{st['requests_used']:,} request(s) used; "
          f"{len(st['done_batches']):,}/{batches:,} batch(es) complete"
          + (f"; {cut} cut by budget — re-run to finish them" if cut else ""))
    if len(st["done_batches"]) < batches:
        print("[h8] NOT finished — re-run this command after the daily quota "
              "reset; the manifest resumes from the saved cursors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
