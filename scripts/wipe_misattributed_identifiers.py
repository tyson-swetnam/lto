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

Re-runs are idempotent. A run is one lake snapshot; run
scripts/export_parquet.py afterwards to publish it.

Usage::
    python scripts/wipe_misattributed_identifiers.py --dry-run
    python scripts/wipe_misattributed_identifiers.py
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lto_db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

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
        False, False,
        "openalex_id resolved to 'J. A. Clark' — the given name was matched "
        "as a surname. 171 works attributed. Disarmed 2026-10-23: this entry "
        "is keyed on the name, not the bad id, so it would wipe the correct "
        "A5052291224 ('Clark Alexander', Skidaway Institute of Oceanography; "
        "matched by his ORCID 0000-0002-3904-1091 and confirmed in the "
        "2026-10-23 attribution review)."),
    "Ed Sherwood": (
        False, False,
        "openalex_id was 'Morgan Sherwood'. The stored ORCID is correct — "
        "its works are seagrass remote sensing and harmful algal blooms at "
        "the Tampa Bay Estuary Program. Disarmed 2026-10-22: OpenAlex now "
        "resolves A5065465046 to Edward T. Sherwood, Tampa Bay Estuary "
        "Program (ORCID 0000-0001-5330-302X), so the id is right and kept."),
    "Erik Smith": (
        True, False,
        "Stored ORCID's employer is the Electric Power Research Institute "
        "and its works are climate/weather datasets. The openalex_id is "
        "correct — 'Erik M. Smith' at the University of South Carolina, "
        "which runs North Inlet-Winyah Bay NERR — so only the ORCID goes."),
    "James McClelland": (
        False, False,
        "openalex_id was 'James L. McClelland', the Stanford cognitive "
        "scientist; the attributed works were on bilingualism and reading "
        "development. The stored ORCID is correct — 'J. W. McClelland', "
        "Arctic river biogeochemistry, Beaufort Lagoon LTER. Disarmed "
        "2026-10-24: this entry is keyed on the name, not the bad id, so it "
        "would wipe the correct A5019713703 (matched by his ORCID "
        "0000-0001-9619-8194 and confirmed in the 2026-10-24 attribution "
        "review). The cognitive scientist's id was never committed, so it "
        "cannot be listed in BAD_BY_ID; the ORCID match is the guard."),
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

# 2026-10-22 sweep of every stored ORCID against pub.orcid.org: these ids
# resolve to a different human, and four of them had carried the wrong
# OpenAlex author (and its works) in with them. Keyed on person_id and on
# the bad value itself, so a re-run never clears an id corrected later
# (people can share a name: there were two "Kathleen C. Weathers" rows).
# person_id -> (bad orcid or None, bad openalex_id or None, evidence)
BAD_BY_ID = {
    "b45b83f6ff14d22b": (
        "0000-0002-9622-3318", "A5048108051",
        "Jan A. Newton (UW APL / NANOOS): the ORCID record and OpenAlex author "
        "A5048108051 are Mark Dopson, microbiologist at Linnaeus University "
        "(245 works)."),
    "4be69b66a360b7a8": (
        "0000-0002-3550-5485", "A5003462162",
        "Kathleen C. Weathers (Cary Institute): the ORCID record and OpenAlex "
        "author A5003462162 are Heather A. Lawson, Washington University in "
        "St. Louis. Her own iD 0000-0002-3575-6508 (employer Cary Institute) "
        "was verified by R-PEOPLE2."),
    "55b9d2c7b71296db": (
        "0000-0002-6435-3863", "A5023463877",
        "Douglas A. Burns (USGS): the ORCID record and OpenAlex author "
        "A5023463877 are Piotr Konopelski, Medical University of Warsaw."),
    "b6da7a008f6b2319": (
        "0000-0003-2728-6996", "A5013456283",
        "Kathryn L. Cottingham (Dartmouth): the ORCID record and OpenAlex "
        "author A5013456283 are Chih-Kai Peng, Chung Shan Medical University."),
    "03d2c5d35441a78b": (
        "0000-0001-6339-5546", None,
        "Robert J. Toonen (HIMB): the ORCID record is 'Felipe Freire'."),
    "1f588d98bcf365e5": (
        "0000-0002-1042-7484", None,
        "J. William Munger (Harvard): the ORCID record is 'Janeth Montero Mendoza'."),
    "cbe750e7bf43e318": (
        "0000-0003-2972-1525", None,
        "Russell L. Scott (USDA-ARS): the ORCID record is 'Miseon Park'."),
    # 2026-10-23 OpenAlex attribution review (data/seed/
    # openalex_attribution_review_2026-10-23.csv). For the first three the
    # stored ORCID is right but the OpenAlex author carrying it has another
    # person's works merged in; only the openalex_id is listed.
    "7e9779770e0b4608": (
        None, "A5090729096",
        "Arthur J. Miller (Scripps, CCE LTER): OpenAlex A5090729096 carries "
        "his ORCID but merges a UCSF orthodontics researcher, the playwright "
        "and an SMPTE film engineer (~25% of 200 attached works)."),
    "7236f1da13813199": (
        None, "A5006179506",
        "Benjamin P. Warner (UNM): OpenAlex A5006179506 carries his ORCID but "
        "45 of its 46 works are a LANL organometallic/actinide chemist's "
        "(1990-2023); he took his BS in 2001."),
    "97afc747bd02c879": (
        None, "A5003055123",
        "David Parrish (CBNERR-VA / VIMS): OpenAlex A5003055123 carries his "
        "ORCID but merges a USAMRIID / Immune Tolerance Network informatics "
        "author (11 of 22 works, 1991-2008)."),
    "6b5037ecc7044cab": (
        "0000-0001-7164-731X", "A5076903000",
        "Daniel Fisher (NRCS Alaska Snow Survey): the ORCID record and "
        "OpenAlex author A5076903000 are Daniel K. Fisher, USDA-ARS "
        "Stoneville MS, irrigation agronomy. The ORCID was accepted at 0.537 "
        "by fuzzy-matching USDA ARS to USDA NRCS."),
    # Found by the wipe_medicine_attributions.py dry run of 2026-10-23
    # (72% of attached works medicine-tagged); predates that run.
    "d1c39e3d5ff9d8e3": (
        "0000-0003-4381-5245", "A5050942040",
        "William P. Bowman (CU Boulder alpine ecologist, Niwot Ridge / Rocky "
        "Mountain NP): the ORCID record is a Yale astronomer (Dragonfly "
        "Telephoto Array, Helix Nebula) and OpenAlex author A5050942040 is "
        "W. Paul Bowman, pediatric leukemia oncologist (St. Jude, Children's "
        "Medical Center Dallas); 198 attributed works on childhood ALL."),
    # 2026-10-23 ORCID review of the three people held out of the
    # OpenAlex run. Neither author was ever attached; listed so a re-run
    # cannot attach it.
    "8b46cf9bb8d3d818": (
        "0009-0000-0174-1247", "A5112191115",
        "Michael R. Landry (Scripps, CCE LTER): the ORCID record is the LIGO "
        "Hanford Observatory head (Caltech) and OpenAlex A5112191115 'M. "
        "Landry' is his gravitational-wave author. Replaced by verified "
        "0000-0001-8787-2802 (Scripps profile; OpenAlex A5061728587)."),
    "a9637d30d5ba1d55": (
        None, "A5074241907",
        "Mary Martin (UNH ESRC, Hubbard Brook): OpenAlex A5074241907 'Mary "
        "Catharine Martin' (libguides, Ontario primary care) carries ORCID "
        "0000-0002-3619-4463, not her verified 0000-0003-1791-5584."),
    # 2026-10-24 OpenAlex attribution review, pass 2 (data/seed/
    # openalex_attribution_review_2026-10-24.csv). Wang and both Millers
    # keep their (correct) ORCID; the OpenAlex author carrying it is a
    # multi-person merge. Burke's stored ORCID is itself another person's.
    "555356e0213a2c78": (
        None, "A5100426850",
        "Jingjing Wang (UNM Economics, ARID): OpenAlex A5100426850 carries "
        "her ORCID but merges many Jingjing Wangs (Hunan, Central South, "
        "Beijing Normal, Northwest A&F; adsorption, oxidation chemistry); "
        "2 of a 10-work sample were hers."),
    "fdd01ff8110578aa": (
        None, "A5012500008",
        "Mark E. Miller (USGS Canyonlands / NPS dryland ecologist): OpenAlex "
        "A5012500008 carries his ORCID but merges an Urban Institute health-"
        "policy author (NEJM), a Southern Utah University historian and "
        "others; only ~34 of 182 works match his ORCID DOIs."),
    "ebb4846a95cda597": (
        "0000-0001-6265-5385", "A5091839520",
        "Pat Burke (NOAA CO-OPS Oceanographic Division): the ORCID record and "
        "OpenAlex author A5091839520 are Patrick C. Burke, NSSL Warn-on-"
        "Forecast / WPC meteorologist (OU meteorology); ~18 of 24 works are "
        "his, the rest a CO-OPS Burke merged in."),
    "d574f93e9f92a588": (
        None, "A5085326552",
        "Robert J. Miller (UCSB MSI, SBC LTER): OpenAlex A5085326552 carries "
        "his ORCID but merges several Robert J. Millers (492 works 1952-2026: "
        "GE reliability testing, DFO Canada fisheries, education, medicine)."),
}


def bad_openalex_pairs() -> set[tuple[str, str]]:
    """(person_id, openalex_id) pairs that must never be re-attached.

    enrich_people_openalex.py reads this so a re-run cannot bring back an
    author this roster removed. Only BAD_BY_ID counts: BAD is keyed on
    name and does not record the bad id value.
    """
    return {(pid, oa.upper()) for pid, (_, oa, _) in BAD_BY_ID.items() if oa}

# Rows whose `orcid` column holds biography prose rather than an
# identifier. The text is preserved by moving it into `notes` rather than
# being discarded, since it is hand-curated and true — it is simply in
# the wrong column, where it would fail every downstream ORCID lookup.
PROSE_IN_ORCID = ["Marty Downs", "Víctor Manuel Vidal Martínez"]


def main() -> int:
    ap = argparse.ArgumentParser()
    lto_db.add_argparse_catalog(ap)
    ap.add_argument("--db", dest="catalog", type=Path,
                    help="deprecated alias of --catalog")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        conn = lto_db.connect(read_only=args.dry_run, catalog=args.catalog,
                              data=args.lake_data)
    except lto_db.LakeNotFound as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    # A dry run opens the lake read-only and writes nothing; a real run
    # is one snapshot (rolled back whole if the integrity check fails).
    tx = (contextlib.nullcontext() if args.dry_run else lto_db.transaction(
        conn, f"wipe_misattributed_identifiers: {len(BAD) + len(BAD_BY_ID)} roster + "
              f"{len(PROSE_IN_ORCID)} prose-in-orcid rows"))
    with tx:
        totals = _wipe(conn, args.dry_run)
        if not args.dry_run:
            lto_db.assert_integrity(
                conn, ["people", "authorship", "person_areas", "provenance"])
    n_orcid, n_oa, n_auth, n_areas, n_prose = totals

    print(f"[totals] orcid_wiped={n_orcid} openalex_wiped={n_oa} "
          f"authorship_deleted={n_auth} person_areas_deleted={n_areas} "
          f"prose_moved={n_prose}")

    if not args.dry_run:
        # parquet is export_parquet.py's to write.
        print("[next] run scripts/export_parquet.py and export_view_caches.py "
              "to publish")
    conn.close()
    return 0


def _wipe(conn, dry_run: bool) -> tuple[int, int, int, int, int]:
    """Apply BAD and PROSE_IN_ORCID; with dry_run, only print."""
    now = datetime.now(timezone.utc).isoformat()
    n_orcid = n_oa = n_auth = n_areas = n_prose = 0

    todo = []
    for name, (wipe_orcid, wipe_oa, why) in BAD.items():
        row = conn.execute(
            "SELECT person_id, orcid, openalex_id FROM people WHERE name = ?",
            [name]).fetchone()
        if not row:
            print(f"  [skip] {name}: not in people")
            continue
        todo.append((name, wipe_orcid, wipe_oa, why, row))
    for pid, (bad_orcid, bad_oa, why) in BAD_BY_ID.items():
        row = conn.execute(
            "SELECT person_id, orcid, openalex_id, name FROM people WHERE person_id = ?",
            [pid]).fetchone()
        if not row:
            print(f"  [skip] {pid}: not in people")
            continue
        todo.append((row[3], bool(bad_orcid) and (row[1] or "").upper() == bad_orcid,
                     bool(bad_oa) and (row[2] or "").upper() == bad_oa, why, row[:3]))
    for name, wipe_orcid, wipe_oa, why, row in todo:
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
        if dry_run:
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
        if dry_run:
            continue
        merged = "; ".join(t for t in [notes, orcid] if t)
        conn.execute("UPDATE people SET orcid = NULL, notes = ?, "
                     "updated_at = now() WHERE person_id = ?", [merged, pid])
        n_prose += 1

    return n_orcid, n_oa, n_auth, n_areas, n_prose


if __name__ == "__main__":
    sys.exit(main())
