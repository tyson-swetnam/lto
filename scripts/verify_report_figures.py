#!/usr/bin/env python3
"""Re-execute every derivable figure in docs/VALIDATION_REPORT.md.

The report states counts that a reader should not have to take on trust.
db/derived/report_audit_full.json pairs each such figure with the exact SQL that
produces it from files tracked in this repository; this script runs all of them
and reports any that no longer agree.

Run from the repository root:

    python scripts/verify_report_figures.py

Exit status is 0 when every figure agrees, 1 otherwise, so it can gate CI.
The report and its audit map land with the M9 docs; until then the figure set
is empty, the audit file is absent, and this gate passes vacuously — absence
is "nothing to verify yet", not a failure.

Why this exists: successive drafts of the upstream report claimed a broader
verification than had been performed -- a figure assigned from remembered stdout
while being counted as re-derived, a split computed against a gitignored local
database while reported as parquet-derived, and counts declared un-derivable
that were plain row counts of a shipped table. A claim that a reader can
re-execute cannot drift from the work that produced it.

Figures whose only source is a run log or an API response header are listed
separately in the JSON under `not_derivable_from_artifacts` and are deliberately
NOT checked here -- there is nothing in the repository to check them against.
"""
from __future__ import annotations

import json
import os
import sys

AUDIT = "db/derived/report_audit_full.json"


def main() -> int:
    if not os.path.exists(AUDIT):
        print(f"{AUDIT} not present — no report figures to verify yet "
              "(the audit map ships with docs/VALIDATION_REPORT.md in M9). "
              "Nothing to check; passing.")
        return 0
    try:
        import duckdb
    except ImportError:
        print("needs duckdb: pip install duckdb", file=sys.stderr)
        return 1

    audit = json.load(open(AUDIT))
    figures = audit["figures"]
    con = duckdb.connect()

    failures = []
    for token, spec in sorted(figures.items(),
                              key=lambda kv: -int(kv[0].replace(",", ""))):
        want = spec["reported"]
        try:
            got = con.execute(spec["sql"]).fetchone()[0]
        except Exception as exc:                     # noqa: BLE001
            failures.append((token, want, f"{type(exc).__name__}: {exc}"))
            continue
        if got != want:
            failures.append((token, want, got))

    n = len(figures)
    print(f"checked {n} figure(s) from {AUDIT}")
    if failures:
        print(f"{len(failures)} DISAGREE with the report:")
        for token, want, got in failures:
            print(f"  {token:>11}  report={want:<12} derived={got}")
        return 1
    print(f"all {n} agree with docs/VALIDATION_REPORT.md")
    skipped = audit.get("not_derivable_from_artifacts", {})
    if skipped:
        print(f"({len(skipped)} run-log / API-header figures not checkable here; "
              f"see not_derivable_from_artifacts in the JSON)")
    withdrawn = audit.get("withdrawn", {})
    for token, why in withdrawn.items():
        print(f"withdrawn: {token} — {why.split(';')[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
