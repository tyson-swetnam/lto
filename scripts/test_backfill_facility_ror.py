#!/usr/bin/env python3
"""Pin the ROR matcher's rules against the false positives that bought them.

    python scripts/test_backfill_facility_ror.py       # exit 0 = green

Every rule in backfill_facility_ror.judge() exists because an earlier
version of the matcher wrote a wrong ROR into `facilities` — and a wrong
ROR silently mis-joins every researcher at that site. Each case below is
one of those, reconstructed as the minimal ROR v2 record that produced
it, plus the true matches that must survive all the rules. Nothing here
touches the network or the DB; judge() takes the candidate list directly.

No test framework by design (the repo has none): plain asserts and a
count, same shape as scripts/test_overlay_facets.mjs.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backfill_facility_ror import judge  # noqa: E402


def rec(ror: str, display: str, aliases=(), acronyms=(), country="US",
        status="active") -> dict:
    """A ROR v2 record, trimmed to the fields judge() reads."""
    names = [{"value": display, "types": ["ror_display", "label"]}]
    names += [{"value": a, "types": ["alias"]} for a in aliases]
    names += [{"value": a, "types": ["acronym"]} for a in acronyms]
    return {
        "id": f"https://ror.org/{ror}",
        "names": names,
        "status": status,
        "locations": [{"geonames_details": {"country_code": country}}],
    }


PASS, FAIL = [], []


def case(label, facility, acronym, country, items, expect_ror, expect_prefix=None):
    got, matched, why = judge(facility, acronym, country, items)
    ok = got == expect_ror and (expect_prefix is None or why.startswith(expect_prefix))
    (PASS if ok else FAIL).append(
        f"{label}: {facility!r} → {got!r} ({why}), wanted {expect_ror!r}"
        + (f" / {expect_prefix}*" if expect_prefix else ""))


# ── true matches: these must survive every gate ──────────────────────
case("true/exact", "Archbold Biological Station", "ABS", "US",
     [rec("00m2ag473", "Archbold Biological Station", acronyms=["ABS"])],
     "00m2ag473")
case("true/alias-expansion", "Bonanza Creek LTER Caribou-Poker Creeks", None, "US",
     [rec("01nysf027", "Bonanza Creek Long Term Ecological Research",
          aliases=["Bonanza Creek LTER"])],
     "01nysf027")
case("true/two-tokens", "Plum Island Ecosystems LTER", None, "US",
     [rec("052tfzs89", "Plum Island Ecosystems Long Term Ecological Research")],
     "052tfzs89")

# ── rule 1+2: one shared token, or an acronym, is not a match ────────
case("acronym-as-alias", "ACE Basin NERR", None, "US",
     [rec("02pr6am85", "Arkansas Department of Career Education",
          aliases=["ACE"])],
     None)
case("one-token", "Albemarle-Pamlico National Estuary Partnership", None, "US",
     [rec("05vkm7r79", "Lower Columbia Estuary Partnership")],
     None)
case("acronym-only", "Beaufort Lagoon LTER", "LTER", "US",
     [rec("039kwqk96", "Long Term Ecological Research Network",
          acronyms=["LTER"])],
     None)

# ── rule 3: the head token must be shared ────────────────────────────
case("head-token", "Cape Lisburne Coast Guard / NSIDC Sea-Ice Site", None, "US",
     [rec("00zyc7969", "United States Coast Guard")],
     None, "review-head-token")

# ── rule 4: no extra distinctive token on the ROR display name ───────
case("extra/wells-fargo", "Wells NERR", None, "US",
     [rec("00000wf00", "Wells Fargo (United States)")],
     None)
case("extra/point-blue", "Point Reyes National Seashore", None, "US",
     [rec("03sn6yr77", "Point Blue Conservation Science")],
     None)
case("extra/usda-hub", "USDA Midwest Climate Hub", None, "US",
     [rec("024q3f615", "USDA California Climate Hub")],
     None, "review-extra-token")

# ── rule 5: a site's ROR is not its parent university's ──────────────
case("parent-org", "University of Kansas Field Station", None, "US",
     [rec("001tmjg57", "University of Kansas")],
     None, "review-parent-org")

# ── rule 6: the friends-of nonprofit is a different organisation ─────
case("org-form/foundation", "Elkhorn Slough NERR", None, "US",
     [rec("01jseqj92", "Elkhorn Slough Foundation")],
     None, "review-org-form")
# The NERR System is the case where every word of the facility name is
# generic vocabulary, so it never reaches the org-form gate — it fails
# scoring for want of a single distinctive token. Either way the ROR of
# the NERR *Association* must not land on it; only the outcome is pinned.
case("org-form/association", "National Estuarine Research Reserve System",
     None, "US",
     [rec("04km2jv85", "National Estuarine Research Reserve Association")],
     None)
case("org-form/institute", "San Francisco Estuary Partnership NEP", None, "US",
     [rec("025et0929", "San Francisco Estuary Institute")],
     None, "review-org-form")

# ── gates that run before scoring ────────────────────────────────────
case("country-mismatch", "Archbold Biological Station", "ABS", "US",
     [rec("09xxxxx11", "Archbold Biological Station", country="AU")],
     None, "no-match")
case("withdrawn-record", "Archbold Biological Station", "ABS", "US",
     [rec("00m2ag473", "Archbold Biological Station", status="withdrawn")],
     None, "no-match")
case("ambiguity", "Sevilleta LTER", None, "US",
     [rec("01qcacz92", "Sevilleta Long Term Ecological Research"),
      rec("02qcacz93", "Sevilleta Long Term Ecological Research")],
     None, "ambiguous")

for line in PASS:
    print(f"ok   {line}")
for line in FAIL:
    print(f"FAIL {line}")
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
raise SystemExit(1 if FAIL else 0)
