#!/usr/bin/env python3
"""Remove identifiers that point at the wrong human being.

Third instance of the failure upstream cod-kmap kept having, after
wipe_bad_openalex_attributions.py and wipe_medicine_attributions.py
(both also ported into this repo). This time the bad ids came in
through the ORCID resolver rather than a name-only OpenAlex search:
upstream's scripts/enrich_people_orcid.py scored a candidate's employer
against the person's facility with max(SequenceMatcher, token_overlap)
and no requirement that the two names share a distinctive word, so at
the 0.45 default it accepted

    Electric Power Research Institute    -> NERR                (0.560)
    Oklahoma Medical Research Foundation -> LTER                (0.593)
    European Medicines Agency  -> Institute of Ocean Sciences   (0.513)
    Appalachian State University         -> Apalachicola NERR   (0.529)

and its name-only fallback picked arbitrarily among namesakes despite a
comment promising it fired only for a single candidate. Both defects are
fixed in the enrich script this repo ships; this one cleans up the rows
they produced, plus several wrong `openalex_id` values that predate them.
Most of the bad rows were scrubbed upstream before the data crossed into
lto, so a run here typically prints skips — that is the point: the roster
below is the incident record, and re-running it is the guard against the
same ids creeping back in.

Every entry below was decided on evidence, not on a score:
  * the OpenAlex author record's display_name and last_known_institutions
  * the ORCID profile's own employment list and work titles
  * what the attributed publications are actually about, read from
    publication_topics

Diacritic and hyphenation differences ("Crespi Abril" vs "Crespi-Abril",
"Möller Jr." vs "Möller") were checked and are NOT treated as mismatches.

Effects, mirroring wipe_bad_openalex_attributions.py:
  * NULLs the offending column(s) on the person
  * DELETEs that person's authorship rows when openalex_id was wrong
    (those links are the misattribution)
  * DELETEs their person_areas rows, which were derived from them
  * leaves `publications` alone — a work wrongly linked to one person may
    be legitimately linked to another
  * records a provenance row per change

Re-runs are idempotent.

Usage::
    python scripts/wipe_misattributed_identifiers.py --dry-run
    python scripts/wipe_misattributed_identifiers.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "lto.duckdb"
PARQUET_OUT = [ROOT / "db" / "parquet", ROOT / "public" / "parquet"]

# name -> (wipe_orcid, wipe_openalex, evidence)
BAD = {
    "Alex Parker": (
        True, True,
        "Both ids are the planetary astronomer A. H. Parker (Southwest "
        "Research Institute / SETI); 99 attributed works are on Pluto and "
        "Kuiper-belt objects. The San Francisco Bay NERR person is a "
        "different Alex Parker."),
    "Andrew Thomson": (
        True, True,
        "openalex_id is particle physicist 'M. Thomson' (Oxford/Regina); "
        "188 works on LHC collisions. Stored ORCID's employer is the "
        "European Medicines Agency. Neither is the Institute of Ocean "
        "Sciences person."),
    "Anne M. Vogel": (
        True, True,
        "openalex_id resolves to 'D. J. Ampleford' at Sandia National "
        "Laboratories — a different name entirely — with 104 works on "
        "laser-plasma physics. ORCID profile has no employment record."),
    "Bob Miller": (
        True, True,
        "openalex_id is 'John A. Miller' (University of Georgia), 131 "
        "works on service-oriented architecture and web services. Stored "
        "ORCID is 'Bobbette Miller', a rehabilitation researcher at the "
        "University of Oklahoma Health Sciences Center. The Santa Barbara "
        "Coastal LTER person is Robert J. Miller."),
    "Clark Alexander": (
        False, True,
        "openalex_id resolves to 'J. A. Clark' — the given name was matched "
        "as a surname. 171 works attributed."),
    "Ed Sherwood": (
        False, True,
        "openalex_id is 'Morgan Sherwood'. The stored ORCID is correct — "
        "its works are seagrass remote sensing and harmful algal blooms at "
        "the Tampa Bay Estuary Program — so only the OpenAlex id is wiped."),
    "Erik Smith": (
        True, False,
        "Stored ORCID's employer is the Electric Power Research Institute "
        "and its works are climate/weather datasets. The openalex_id is "
        "correct — 'Erik M. Smith' at the University of South Carolina, "
        "which runs North Inlet-Winyah Bay NERR — so only the ORCID goes."),
    "James McClelland": (
        False, True,
        "openalex_id is 'James L. McClelland', the Stanford cognitive "
        "scientist; the attributed works are on bilingualism and reading "
        "development. The stored ORCID is correct — 'J. W. McClelland', "
        "Arctic river biogeochemistry, Beaufort Lagoon LTER."),
    "Jean Wiener": (
        False, True,
        "openalex_id resolves to 'O. Schneider'. 182 works attributed."),
    "Kim Miller": (
        True, False,
        "Stored ORCID is 'Kimberly Miller', a community-college educator "
        "(Gaston College / Stanly Community College) whose only work is on "
        "hybrid course design. Not the Apalachicola NERR person."),
    "Mark Sanborn": (
        True, True,
        "Stored ORCID's works are cancer cell mechanics, hippocampal "
        "neurogenesis and mesenchymal stromal cells. openalex_id is 'Mark "
        "A. Sanborn' at Illinois College, publishing on mosquito-borne "
        "disease. Neither is the EPA Region 1 person."),
    "Mike De Luca": (
        False, True,
        "openalex_id resolves to 'Raktim Sarma'. 99 works attributed."),
    "Paul Dest": (
        False, True,
        "openalex_id resolves to 'Julien Perret'. 100 works attributed. "
        "This person was already cleaned once by "
        "wipe_bad_openalex_attributions.py and was re-broken."),
    "Paul Orlando": (
        False, True,
        "openalex_id resolves to 'C. Padilla Aranda'. 166 works attributed."),
    "Tyler Smith": (
        True, False,
        "Stored ORCID's sole employer is Adventium Labs, a software "
        "research company. Not the University of the Virgin Islands "
        "Center for Marine and Environmental Studies person."),
}

# Rows whose `orcid` column holds biography prose rather than an
# identifier. The text is preserved by moving it into `notes` rather than
# being discarded, since it is hand-curated and true — it is simply in
# the wrong column, where it would fail every downstream ORCID lookup.
PROSE_IN_ORCID = ["Marty Downs", "Víctor Manuel Vidal Martínez"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"[error] db not found: {args.db}", file=sys.stderr)
        return 2

    conn = duckdb.connect(str(args.db))
    now = datetime.now(timezone.utc).isoformat()
    n_orcid = n_oa = n_auth = n_areas = n_prose = 0

    for name, (wipe_orcid, wipe_oa, why) in BAD.items():
        row = conn.execute(
            "SELECT person_id, orcid, openalex_id FROM people WHERE name = ?",
            [name]).fetchone()
        if not row:
            print(f"  [skip] {name}: not in people")
            continue
        pid, orcid, oaid = row
        acts = []
        if wipe_orcid and orcid:
            acts.append(f"orcid={orcid}")
        if wipe_oa and oaid:
            acts.append(f"openalex_id={oaid}")
        if not acts:
            continue
        npub = conn.execute(
            "SELECT count(*) FROM authorship WHERE person_id = ?",
            [pid]).fetchone()[0]
        print(f"  {name}: wiping {', '.join(acts)}"
              + (f" and {npub} authorship rows" if wipe_oa and npub else ""))
        if args.dry_run:
            continue

        if wipe_orcid and orcid:
            conn.execute("UPDATE people SET orcid = NULL, updated_at = now() "
                         "WHERE person_id = ?", [pid])
            n_orcid += 1
        if wipe_oa and oaid:
            conn.execute("UPDATE people SET openalex_id = NULL, "
                         "research_interests = NULL, updated_at = now() "
                         "WHERE person_id = ?", [pid])
            n_oa += 1
            n_auth += conn.execute(
                "SELECT count(*) FROM authorship WHERE person_id = ?",
                [pid]).fetchone()[0]
            conn.execute("DELETE FROM authorship WHERE person_id = ?", [pid])
            n_areas += conn.execute(
                "SELECT count(*) FROM person_areas WHERE person_id = ?",
                [pid]).fetchone()[0]
            conn.execute("DELETE FROM person_areas WHERE person_id = ?", [pid])

        conn.execute(
            "INSERT INTO provenance (record_type, record_id, source_url, "
            "retrieved_at, confidence, agent) VALUES (?,?,?,?,?,?)",
            ["person", pid,
             "https://api.openalex.org/authors + https://pub.orcid.org",
             now, "high",
             f"wipe_misattributed_identifiers.py: cleared "
             f"{', '.join(a.split('=')[0] for a in acts)}. {why}"])

    for name in PROSE_IN_ORCID:
        row = conn.execute(
            "SELECT person_id, orcid, notes FROM people WHERE name = ?",
            [name]).fetchone()
        if not row:
            continue
        pid, orcid, notes = row
        if not orcid or len(orcid) == 19:
            continue
        print(f"  {name}: moving prose out of orcid into notes")
        if args.dry_run:
            continue
        merged = "; ".join(t for t in [notes, orcid] if t)
        conn.execute("UPDATE people SET orcid = NULL, notes = ?, "
                     "updated_at = now() WHERE person_id = ?", [merged, pid])
        n_prose += 1

    print(f"[totals] orcid_wiped={n_orcid} openalex_wiped={n_oa} "
          f"authorship_deleted={n_auth} person_areas_deleted={n_areas} "
          f"prose_moved={n_prose}")

    if not args.dry_run:
        for base in PARQUET_OUT:
            base.mkdir(parents=True, exist_ok=True)
            for tbl in ("people", "authorship", "person_areas", "provenance"):
                out = base / f"{tbl}.parquet"
                conn.execute(f"COPY {tbl} TO '{out}' (FORMAT PARQUET)")
            print(f"[parquet] refreshed {base}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
