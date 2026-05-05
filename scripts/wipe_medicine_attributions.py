#!/usr/bin/env python3
"""Aggressive cleanup of medicine-flavored OpenAlex misattributions.

This is a tougher sibling of ``scripts/wipe_bad_openalex_attributions.py``.
That script flagged a person as bad only when their ``research_interests``
contained NO marine/coastal keyword. That heuristic missed every wrong-
person OpenAlex match where the matched author's profile happened to
include one tangentially marine concept (e.g. "Biology" or "Ecology")
alongside heavy medical content.

Re-audit on 2026-04-26 found 167 cod-kmap people with at least one
medicine-tagged publication and 35+ where >25% of all publications
are medicine-tagged. Several have a real ORCID — wrong ORCIDs were
also flowing in via name-only resolution.

This script wipes a person's OpenAlex linkage when ANY of these are true:

  (1) research_interests starts with a strong medical term, or contains
      ≥2 strong medical terms in its first 5 comma-separated tokens;
  (2) >= ``--med-pct-threshold`` (default 25) percent of the person's
      publications are tagged with a medicine/clinical/oncology/etc.
      OpenAlex concept;
  (3) the person has ≥1 medicine-tagged publication AND zero rows in
      person_area_metrics (i.e. the OpenAlex topic crosswalk found no
      coastal-relevant publications for them at all).

For each flagged person:
  * NULL out openalex_id, research_interests, bio (the latter is also
    OpenAlex-sourced).
  * DELETE the person's authorship rows so the bogus pub→person links
    disappear.
  * DELETE their person_areas rows.
  * Leave publications themselves untouched (they may have legitimate
    co-authors among other people in the dataset).

Then re-export the affected parquets.

Idempotent — re-running finds nothing left to wipe.

Usage:
    python scripts/wipe_medicine_attributions.py --dry-run
    python scripts/wipe_medicine_attributions.py             # apply
    python scripts/wipe_medicine_attributions.py --med-pct-threshold 15
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "cod_kmap.duckdb"
PARQUET_DIRS = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]

# Strong medical terms: presence in research_interests is a strong negative
# signal regardless of marine-keyword overlap (because authors with one
# token "Biology" but five "Internal medicine, Cardiology" tokens are
# clearly the wrong person for a coastal observatory).
MED_TOKENS = {
    "medicine", "internal medicine", "clinical medicine", "family medicine",
    "intensive care medicine", "emergency medicine", "physical medicine",
    "nuclear medicine", "alternative medicine",
    "cardiology", "oncology", "psychiatry", "pediatrics", "obstetrics",
    "gynecology", "neurology", "anesthesiology", "dentistry", "dermatology",
    "radiology", "pathology", "endocrinology", "urology", "rheumatology",
    "gastroenterology", "ophthalmology", "hepatology", "hematology",
    "cancer research", "cancer", "tumor", "tumour", "myocardial infarction",
    "heart failure", "ejection fraction", "pancreatic cancer", "pancreatitis",
    "asthma", "diabetes", "hypertension", "stroke", "covid-19",
    "etanercept", "interleukin", "interferon", "vaccine",
    "periodontitis", "transplantation", "nursing", "surgery", "general surgery",
    "head and neck cancer", "breast cancer", "prostate cancer",
    "colorectal cancer", "clinical trial", "chemotherapy",
    "psychotherapy", "neuroscience",
}

# Concept-name LIKE patterns we treat as a "medicine pub" for the
# coverage-based check.
MED_PUB_LIKE = (
    "medicine", "internal medicine", "clinical", "pharm", "cancer",
    "surger", "nursing", "psychiatr", "pediatr", "oncology", "cardio",
    "dent", "anesthes", "obstetr", "gynec", "intensive care",
    "emergency medicine",
)


def has_strong_med_signal(ri: str | None) -> bool:
    if not ri:
        return False
    tokens = [t.strip().lower() for t in ri.split(",")]
    head = tokens[:5]
    n_med = sum(1 for t in head if t in MED_TOKENS)
    if tokens and tokens[0] in MED_TOKENS:
        return True
    if n_med >= 2:
        return True
    # Also catch any token that exactly contains 'medicine' as a prefix
    if any("medicine" in t for t in head):
        return True
    return False


def find_suspects(conn, med_pct_threshold: float):
    """Return list of (person_id, name, ri, openalex_id, reason)."""
    # Build the medicine-pub set once
    med_clause = " OR ".join(
        f"concept_name ILIKE '%{kw}%'" for kw in MED_PUB_LIKE
    )
    conn.execute(f"""
        CREATE OR REPLACE TEMPORARY VIEW _med_pubs AS
        SELECT DISTINCT publication_id FROM publication_topics
        WHERE {med_clause}
    """)

    rows = conn.execute("""
        WITH per_pub AS (
            SELECT p.person_id, p.name, p.research_interests, p.openalex_id, p.orcid,
                   COUNT(DISTINCT a.publication_id) AS n_total,
                   COUNT(DISTINCT CASE WHEN mp.publication_id IS NOT NULL
                                       THEN a.publication_id END) AS n_med
            FROM   people p
            LEFT JOIN authorship a   ON a.person_id = p.person_id
            LEFT JOIN _med_pubs   mp ON mp.publication_id = a.publication_id
            WHERE  p.openalex_id IS NOT NULL AND length(p.openalex_id) > 0
            GROUP  BY p.person_id, p.name, p.research_interests,
                      p.openalex_id, p.orcid
        ),
        pa_counts AS (
            SELECT person_id, COUNT(*) AS n_pa
            FROM   person_areas
            GROUP  BY person_id
        )
        SELECT pp.person_id, pp.name, pp.research_interests, pp.openalex_id,
               pp.orcid, pp.n_total, pp.n_med,
               COALESCE(pa.n_pa, 0) AS n_pa
        FROM   per_pub pp
        LEFT JOIN pa_counts pa USING (person_id)
    """).fetchall()

    suspects = []
    for pid, name, ri, oaid, orcid, n_total, n_med, n_pa in rows:
        reasons: list[str] = []
        if has_strong_med_signal(ri):
            reasons.append("ri-medicine")
        pct = (100.0 * n_med / n_total) if n_total else 0.0
        if pct >= med_pct_threshold:
            reasons.append(f"pubs-{pct:.0f}%-medicine")
        if n_med >= 1 and n_pa == 0:
            reasons.append("no-coastal-areas")
        if reasons:
            suspects.append((pid, name, ri, oaid, orcid, ",".join(reasons),
                             n_total, n_med, pct))
    return suspects


def wipe(conn, suspects, *, keep_orcid: bool = False) -> dict:
    if not suspects:
        return {"people": 0, "authorship": 0, "person_areas": 0}
    pids = [s[0] for s in suspects
            if (not keep_orcid) or not (s[4] and s[4].startswith("0000-"))]
    if not pids:
        return {"people": 0, "authorship": 0, "person_areas": 0}
    placeholder = ",".join(["?"] * len(pids))

    n_aut_before = conn.execute(
        f"SELECT COUNT(*) FROM authorship WHERE person_id IN ({placeholder})",
        pids,
    ).fetchone()[0]
    conn.execute(
        f"DELETE FROM authorship WHERE person_id IN ({placeholder})", pids,
    )
    n_pa_before = conn.execute(
        f"SELECT COUNT(*) FROM person_areas WHERE person_id IN ({placeholder})",
        pids,
    ).fetchone()[0]
    conn.execute(
        f"DELETE FROM person_areas WHERE person_id IN ({placeholder})", pids,
    )
    conn.execute(
        f"""UPDATE people SET
                openalex_id        = NULL,
                research_interests = NULL,
                bio                = NULL,
                updated_at         = now()
            WHERE person_id IN ({placeholder})""",
        pids,
    )
    return {
        "people": len(pids),
        "authorship_deleted": n_aut_before,
        "person_areas_deleted": n_pa_before,
    }


def export_parquet(conn) -> None:
    for base in PARQUET_DIRS:
        base.mkdir(parents=True, exist_ok=True)
        for t in ("people", "authorship", "person_areas"):
            out = base / f"{t}.parquet"
            conn.execute(f"COPY {t} TO '{out}' (FORMAT PARQUET)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path,
                    default=Path(os.environ.get("COD_KMAP_DB",
                                                 str(DEFAULT_DB))))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--med-pct-threshold", type=float, default=25.0,
                    help="Wipe a person whose >= this %% of pubs are "
                         "medicine-tagged. Default 25.")
    ap.add_argument("--keep-orcid", action="store_true",
                    help="Spare people who have a real ORCID even if they "
                         "trip the medicine heuristics. Off by default.")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[err] DB not found: {args.db}", file=sys.stderr)
        return 2
    print(f"[wipe] DB: {args.db}", file=sys.stderr)

    conn = duckdb.connect(str(args.db))
    suspects = find_suspects(conn, args.med_pct_threshold)
    print(f"[wipe] {len(suspects)} suspects identified", file=sys.stderr)
    print()
    for pid, name, ri, oaid, orcid, why, n_total, n_med, pct in suspects:
        flag = "ORCID" if (orcid and orcid.startswith("0000-")) else " ----"
        print(f"  {flag} {name[:30]:30s} OA={oaid:13s} {pct:5.1f}% "
              f"{n_med:>4d}/{n_total:>4d}  why={why:35s}  RI={(ri or '')[:60]}")

    if args.dry_run:
        print("\n[dry-run] no writes. Re-run without --dry-run to apply.")
        conn.close()
        return 0

    res = wipe(conn, suspects, keep_orcid=args.keep_orcid)
    print()
    print(f"[wiped] people: {res['people']}  "
          f"authorship_deleted: {res['authorship_deleted']}  "
          f"person_areas_deleted: {res['person_areas_deleted']}",
          file=sys.stderr)

    export_parquet(conn)
    print("[wipe] re-exported people, authorship, person_areas parquets",
          file=sys.stderr)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
