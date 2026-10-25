#!/usr/bin/env python3
"""Derive `person_areas` from each person's publication topics.

Pipeline:

    publication_topics  +  data/vocab_crosswalk/openalex_to_area.csv
                          ↓
                       (per-pub area scores via crosswalk × topic score × confidence)
                          ↓
    authorship  →  per-person aggregate  →  person_areas

Algorithm:

  1. Load the crosswalk CSV (openalex_id → area_id, confidence).
  2. For each (publication_id, area_id), compute:
        pub_area_score = MAX(topic.score × confidence_multiplier)
     where confidence_multiplier = {high: 1.0, medium: 0.7, low: 0.4}.
     We take MAX rather than SUM because if a publication is tagged
     with two different OpenAlex topics that both map to the same
     research_area, we don't want to double-count the same paper.
  3. For each (person_id, area_id), aggregate:
        weight         = SUM(pub_area_score) / n_publications  -- 0..1
        evidence_count = COUNT(DISTINCT publication_id)
  4. Filter out (person, area) pairs with evidence_count < min_evidence
     (default 2) so a single ambiguous topic doesn't spuriously assign
     someone to a research area.
  5. Replace existing rows where source = 'openalex_topics' (DELETE
     + INSERT). Manual entries (source = 'manual') are preserved.

Usage::

    python scripts/compute_person_areas.py
    python scripts/compute_person_areas.py --min-evidence 3
    python scripts/compute_person_areas.py --min-weight 0.05
    python scripts/compute_person_areas.py --top-areas 5  # cap per person
    python scripts/compute_person_areas.py --dry-run

A real run is one lake snapshot (DELETE + INSERT in one transaction); a
--dry-run opens the lake read-only and writes nothing.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CROSSWALK = ROOT / "data" / "vocab_crosswalk" / "openalex_to_area.csv"

CONFIDENCE_MULT = {"high": 1.0, "medium": 0.7, "low": 0.4}


def load_crosswalk(path: Path) -> dict[str, list[tuple[str, float]]]:
    """Returns oa_id -> [(area_id, multiplier), …]. Skips comment rows
    (starting with '#') and rows without an area_id (intentional
    off-domain markers)."""
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(
            (line for line in fh if not line.lstrip().startswith("#")),
        )
        for row in reader:
            oa = (row.get("openalex_id") or "").strip()
            area = (row.get("area_id") or "").strip()
            conf = (row.get("confidence") or "low").strip().lower()
            if not (oa and area):
                continue
            out[oa].append((area, CONFIDENCE_MULT.get(conf, 0.4)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    ap.add_argument("--min-evidence", type=int, default=2,
                    help="Drop (person, area) pairs with fewer than N "
                         "supporting publications. Default: 2.")
    ap.add_argument("--min-weight", type=float, default=0.02,
                    help="Drop pairs with weight below this threshold. "
                         "Default: 0.02.")
    ap.add_argument("--top-areas", type=int, default=8,
                    help="Keep at most N areas per person (highest "
                         "weight). Default: 8.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute and print summary, but do not write.")
    args = ap.parse_args()

    if not args.crosswalk.exists():
        print(f"[error] crosswalk not found: {args.crosswalk}", file=sys.stderr)
        return 2

    crosswalk = load_crosswalk(args.crosswalk)
    print(f"[crosswalk] {len(crosswalk)} OpenAlex ids → "
          f"{sum(len(v) for v in crosswalk.values())} (id, area) pairs")

    conn = lto_db.connect(read_only=args.dry_run,
                          catalog=args.catalog, data=args.lake_data)

    # Load the (publication_id, concept_id, score) join we need into
    # a Python list — for ~250k rows this is trivial RAM-wise and lets
    # us keep the per-row arithmetic in Python (CONFIDENCE_MULT lookup
    # is awkward in pure SQL without registering a UDF).
    rows = conn.execute("""
        SELECT pt.publication_id, pt.concept_id, COALESCE(pt.score, 0.5)
        FROM publication_topics pt
        WHERE pt.concept_id IN ?
    """, [list(crosswalk.keys())]).fetchall()
    print(f"[topics] {len(rows)} (pub, topic) rows match the crosswalk")

    # pub_area_score[pub_id][area_id] = max over topics of (score × mult)
    pub_area_score: dict[str, dict[str, float]] = defaultdict(dict)
    for pub_id, concept_id, score in rows:
        for area_id, mult in crosswalk.get(concept_id, []):
            s = float(score) * mult
            cur = pub_area_score[pub_id].get(area_id, 0.0)
            if s > cur:
                pub_area_score[pub_id][area_id] = s
    print(f"[topics] resolved {len(pub_area_score)} publications "
          f"to one or more research_areas")

    # Now join authorship: for each person, aggregate their pub_area_scores.
    auth_rows = conn.execute(
        "SELECT person_id, publication_id FROM authorship"
    ).fetchall()
    person_pubs: dict[str, list[str]] = defaultdict(list)
    for pid, pub in auth_rows:
        person_pubs[pid].append(pub)

    # Aggregate per (person, area): SUM(pub_area_score) / n_pubs_with_topics.
    # We divide by the count of the person's publications that *had any
    # topic at all* (rather than total publications), so a person with
    # only a few topiced papers isn't penalised for a sparse OpenAlex
    # corpus. Floor of 1 to avoid div-by-zero.
    person_area_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    person_area_n:   dict[str, dict[str, int]]   = defaultdict(lambda: defaultdict(int))
    person_topiced_pubs: dict[str, int] = defaultdict(int)

    for person_id, pubs in person_pubs.items():
        topiced = 0
        for pub in pubs:
            if pub not in pub_area_score:
                continue
            topiced += 1
            for area_id, s in pub_area_score[pub].items():
                person_area_sum[person_id][area_id] += s
                person_area_n[person_id][area_id]   += 1
        person_topiced_pubs[person_id] = topiced

    # Build output rows: (person_id, area_id, weight, evidence_count, source).
    out_rows: list[tuple[str, str, float, int, str]] = []
    for person_id, area_sums in person_area_sum.items():
        denom = max(person_topiced_pubs[person_id], 1)
        # Per-area normalised weight (0..1ish).
        ranked = sorted(
            ((a, s / denom, person_area_n[person_id][a]) for a, s in area_sums.items()),
            key=lambda x: x[1], reverse=True,
        )
        # Apply --min-evidence and --min-weight filters.
        ranked = [(a, w, n) for (a, w, n) in ranked
                  if n >= args.min_evidence and w >= args.min_weight]
        # Cap to --top-areas.
        ranked = ranked[: args.top_areas]
        for area_id, weight, ev in ranked:
            out_rows.append((person_id, area_id, round(weight, 4), ev,
                             "openalex_topics"))

    print(f"[aggregate] {len(out_rows)} (person, area) rows ready  "
          f"({len(set(r[0] for r in out_rows))} people, "
          f"{len(set(r[1] for r in out_rows))} areas)")

    if args.dry_run:
        print("[dry-run] sample first 20:")
        for r in out_rows[:20]:
            print(f"  person={r[0]}  area={r[1]}  weight={r[2]}  "
                  f"evidence={r[3]}")
        return 0

    # Replace only rows we own. Manual entries (source='manual') survive.
    # The delete and the insert are one transaction, so one lake snapshot,
    # and assert_integrity rolls both back if a person/area FK is broken.
    with lto_db.transaction(conn, f"compute_person_areas: {len(out_rows)} "
                                  f"openalex_topics rows (min_evidence="
                                  f"{args.min_evidence}, top_areas={args.top_areas})"):
        # A facility-inherited area (compute_lto_person_metrics.py) needs the
        # facility link it came from: once a merge or fix drops the person's
        # role, or the facility's area, the row is unsupported. Pruned first,
        # so a topic row for the same pair can take its place in this run.
        pruned = conn.execute("""
            DELETE FROM person_areas pa
            WHERE source = 'facility-area-inheritance'
              AND NOT EXISTS (SELECT 1 FROM facility_personnel fp
                              JOIN area_links al ON al.facility_id = fp.facility_id
                              WHERE fp.person_id = pa.person_id
                                AND al.area_id = pa.area_id)""").fetchone()[0]
        if pruned:
            print(f"[prune] {pruned} facility-area-inheritance rows with no facility "
                  f"link carrying that area")
        conn.execute("DELETE FROM person_areas WHERE source = 'openalex_topics'")
        if out_rows:
            # Bulk insert via a temp table, dedupe to be safe (in case the
            # same person shows up twice for an area, which shouldn't happen
            # but the lake enforces no PK, so a duplicate would land).
            conn.execute("""
                CREATE TEMP TABLE _pa_stage (
                    person_id      VARCHAR,
                    area_id        VARCHAR,
                    weight         DOUBLE,
                    evidence_count INTEGER,
                    source         VARCHAR
                )
            """)
            conn.executemany(
                "INSERT INTO _pa_stage VALUES (?, ?, ?, ?, ?)", out_rows,
            )
            conn.execute("""
                INSERT INTO person_areas (person_id, area_id, weight,
                                          evidence_count, source)
                SELECT person_id, area_id, MAX(weight), MAX(evidence_count),
                       ANY_VALUE(source)
                FROM _pa_stage
                WHERE EXISTS (
                    SELECT 1 FROM people p WHERE p.person_id = _pa_stage.person_id
                )
                AND EXISTS (
                    SELECT 1 FROM research_areas ra WHERE ra.area_id = _pa_stage.area_id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM person_areas pa
                    WHERE pa.person_id = _pa_stage.person_id
                      AND pa.area_id   = _pa_stage.area_id
                )
                GROUP BY person_id, area_id
            """)
            conn.execute("DROP TABLE _pa_stage")
        lto_db.assert_integrity(conn, ["person_areas"])
    n_total = conn.execute("SELECT COUNT(*) FROM person_areas").fetchone()[0]
    n_topic = conn.execute(
        "SELECT COUNT(*) FROM person_areas WHERE source = 'openalex_topics'"
    ).fetchone()[0]
    print(f"[done] person_areas total={n_total}  from_topics={n_topic}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
