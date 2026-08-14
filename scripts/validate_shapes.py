#!/usr/bin/env python3
"""Regression test for schema/shapes/lto-shapes.ttl.

Runs the shapes standalone (pyshacl, no reasoner, no network) against the
worked example graph and asserts the EXACT set of violations. A shape that
silently stops firing is a shape that stops gating an ingest, and a shape that
starts firing on a conforming node blocks legitimate data — this catches both.

    python scripts/validate_shapes.py

Exits non-zero on any difference, so it can be wired into scripts/qa.py or a
pre-commit hook. Requires: pip install rdflib pyshacl owlrl
"""
from __future__ import annotations

import sys
from pathlib import Path

import pyshacl
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, SH

LTO = Namespace("https://tyson-swetnam.github.io/lto/ns/lto#")
EX = "https://tyson-swetnam.github.io/lto/id/"

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ONTOLOGY = ROOT / "schema" / "ontology" / "lto.owl"
SHAPES = ROOT / "schema" / "shapes" / "lto-shapes.ttl"
EXAMPLE = ROOT / "schema" / "shapes" / "lto-example.ttl"

# (focus node local name, SHACL constraint component) -> why it must fire.
# PART B of lto-example.ttl; keep the two in step. Same deliberate violation
# set as upstream cod-kmap's cod-example.ttl, minus B4 (public id + codp:
# local identity): lto has no local-identifier form — every registry row
# carries a public ORCID or OpenAlex author id by construction — so neither
# the defect nor cod:LocalIdentityExclusivityShape exists in this port. The
# B numbering stays aligned with upstream so the two files diff side by side.
EXPECTED: dict[tuple[str, str], str] = {
    ("person/bad-no-identifier", "OrConstraintComponent"):
        "B1 no persistent identifier",
    ("person/bad-no-source-url", "MinCountConstraintComponent"):
        "B2a no citable source_url",
    ("person/bad-no-source-url", "InConstraintComponent"):
        "B2b confidence outside {high,medium,low}",
    ("person/bad-orcid-syntax", "PatternConstraintComponent"):
        "B3 ORCID is a URL, not a bare id",
    ("edge/bad-no-evidence", "OrConstraintComponent"):
        "B5 edge with no provenance path back to a work",
    ("work/bad-untitled-preprint", "OrConstraintComponent"):
        "B6 evidence work carries no OpenAlex id and no DOI",
    ("candidate/bad-bare-name", "OrConstraintComponent"):
        "B7 candidate proposed on a bare name",
    ("candidate/bad-silent-rejection", "SPARQLConstraintComponent"):
        "B8 rejection with no disambiguation evidence",
    ("person/bad-shortcut-only", "SPARQLConstraintComponent"):
        "B9 lto:coauthorOf with no backing lto:CoauthorEdge",
    ("validation/bad-fail-no-detail", "SPARQLConstraintComponent"):
        "B10 Fail verdict with no mismatch detail",
}

# PART A of lto-example.ttl. Any violation on one of these is a false positive:
# the OpenAlex-only node in particular MUST pass — it is lto's minimal-identity
# case (upstream's codp:% local-identity node has no counterpart here), and a
# row known only by one identifier is legitimate, not a defect.
MUST_CONFORM = {
    "person/orcid-0000-0002-1825-0097",
    "person/orcid-0000-0003-1613-5981",
    "person/openalex-A5011122233",
    "person/orcid-0000-0002-3333-4444",   # internal seed provenance: warns, never violates
    "edge/A1-A2",
    "work/W2741809807",
    "work/W3011223344",
    "candidate/openalex-A5099887766",
    "candidate/orcid-0000-0001-2345-6789",
    "validation/A1-orcid",
    "validation/A3-openalex",
    "membership/A1-scholar",
    "membership/A3-site",
    "assignment/A1-forest",
}


def observed(results: Graph) -> set[tuple[str, str]]:
    out = set()
    for r in results.subjects(RDF.type, SH.ValidationResult):
        if results.value(r, SH.resultSeverity) != SH.Violation:
            continue          # warnings are advisory by design
        focus = str(results.value(r, SH.focusNode))
        comp = str(results.value(r, SH.sourceConstraintComponent)).split("#")[-1]
        out.add((focus.removeprefix(EX), comp))
    return out


def check_pattern_escaping() -> list[str]:
    """Guard against an over-escaped sh:pattern silently blocking every ingest.

    A regex in Turtle needs its backslashes doubled: `sh:pattern "[^\\\\s]+"`
    on disk unescapes to the regex `[^\\s]+`, the whitespace class we want. Write
    four backslashes by mistake — easy to do when a pattern is edited through a
    tool that re-escapes, or copied out of a Python string literal — and it
    unescapes to `[^\\\\s]`, a negated class over a literal backslash and the
    letter 's'. Every URL containing an 's' after the scheme is then rejected by
    a Violation-level constraint, so the shapes block the very records their
    sh:message says they accept, and they do it silently: the shapes file still
    parses, and a graph of *only* conforming data still reports violations that
    look like data problems.

    So assert the compiled behaviour, not the source text: resolve each pattern
    through rdflib exactly as pyshacl does, and check it against values that
    must match and values that must not.
    """
    import re

    shapes = Graph()
    shapes.parse(SHAPES, format="turtle")
    resolved = {str(o) for o in shapes.objects(None, SH.pattern)}

    # Select each pattern by an anchor unique to it. A loose substring is not
    # good enough: 'lto:' also occurs in lto:InternalProvenanceShape's
    # `^lto:` (a Warning-level detector for the internal provenance form,
    # which is SUPPOSED to reject http URLs), so matching on it would test that
    # shape against the wrong expectations.
    #
    # (anchor identifying the pattern, must-match, must-not-match)
    cases = [
        ("[^\\s]+|lto:",
         ["https://api.openalex.org/authors/A5023888391",
          "https://api.openalex.org/works/W2741809807",
          "https://example.org/directory/staff/42",
          "https://example-coastal-institute.org/staff/programme-office",
          "lto:people"],
         ["not a url", "ftp://x/y", "https://has space/x"]),
        ("ror\\.org",
         ["https://ror.org/03m2x1q45", "03m2x1q45"],
         ["ror.org/03m2x1q45", "https://ror.org/ZZZZZZZZZ"]),
        ("[0-9X]$",
         ["0000-0002-1825-0097", "0000-0002-1825-009X"],
         ["https://orcid.org/0000-0002-1825-0097", "0000-0002-1825-00"]),
        ("^A[0-9]+$",
         ["A5023888391"],
         ["https://openalex.org/A5023888391", "5023888391"]),
        # The bare source_url pattern used on edges, candidates and validation
        # results (no lto: alternative there — those are machine-generated
        # rows and always carry a real query URL).
        ("^https?://[^\\s]+$",
         ["https://api.openalex.org/works?filter=author.id:A5023888391",
          "https://pub.orcid.org/v3.0/0000-0002-1825-0097/record"],
         ["lto:people", "https://has space/x"]),
    ]

    problems = []
    for needle, good, bad in cases:
        hits = [p for p in resolved if needle in p]
        if not hits:
            problems.append(f"no sh:pattern found containing {needle!r} — "
                            f"a constraint was renamed or removed")
            continue
        for pat in hits:
            for v in good:
                if not re.match(pat, v):
                    problems.append(
                        f"sh:pattern {pat!r} REJECTS the legitimate value {v!r} — "
                        f"almost certainly an over-escaped backslash "
                        f"(\\\\\\\\s on disk instead of \\\\s); this would block "
                        f"valid records at Violation level")
            for v in bad:
                if re.match(pat, v):
                    problems.append(
                        f"sh:pattern {pat!r} ACCEPTS the invalid value {v!r}")
    return problems


def check_sameas_closure() -> list[str]:
    """The identity mechanism the co-author matching relies on.

    Two nodes sharing an ORCID must be inferred owl:sameAs under OWL-RL; two
    nodes colliding on a lto:localIdentifier must NOT be. No lto registry row
    carries a local identifier (there is no codp:-style cohort here), but the
    guard stays: upstream that value is a sha1 of name|orcid|email, so
    same-name people with no ORCID collide, and if the property is ever
    reintroduced it must never be inverse-functional. If lto.owl omits the
    property entirely the axiom cannot exist and this check passes — also
    correct.
    """
    import owlrl

    g = Graph()
    g.parse(ONTOLOGY, format="turtle")
    p = Namespace(EX + "p/")
    g.add((p.reg, RDF.type, LTO.RegistryPerson))
    g.add((p.reg, LTO.orcidId, Literal("0000-0002-1825-0097")))
    g.add((p.cand, RDF.type, LTO.CoauthorCandidate))
    g.add((p.cand, LTO.orcidId, Literal("0000-0002-1825-0097")))
    g.add((p.localA, RDF.type, LTO.RegistryPerson))
    g.add((p.localA, LTO.localIdentifier, Literal("065ae200269c6713")))
    g.add((p.localB, RDF.type, LTO.RegistryPerson))
    g.add((p.localB, LTO.localIdentifier, Literal("065ae200269c6713")))
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)

    def same(a, b):
        return (a, OWL.sameAs, b) in g or (b, OWL.sameAs, a) in g

    problems = []
    if not same(p.reg, p.cand):
        problems.append(
            "shared ORCID did NOT produce owl:sameAs — the inverse-functional "
            "identity block is broken and co-author matching would fall back "
            "to name comparison")
    if same(p.localA, p.localB):
        problems.append(
            "lto:localIdentifier collision produced owl:sameAs — two same-name "
            "people were merged; lto:localIdentifier must not be "
            "owl:InverseFunctionalProperty")
    return problems


def main() -> int:
    shapes = Graph()
    shapes.parse(SHAPES, format="turtle")
    data = Graph()
    data.parse(EXAMPLE, format="turtle")

    # Capture sizes BEFORE validating. pyshacl.validate() mutates the graphs it
    # is handed (it normalises the shapes graph in place, adding a couple of
    # triples), so reading len(shapes) afterwards over-reports the file by 2 and
    # any figure quoted from it will not reproduce when someone re-parses the
    # file themselves.
    n_shapes_triples = len(shapes)
    n_data_triples = len(data)

    conforms, results, _ = pyshacl.validate(
        data, shacl_graph=shapes, inference="none", advanced=True)

    got = observed(results)
    want = set(EXPECTED)
    missed = want - got
    unexpected = got - want
    false_positives = sorted(f for f, _ in unexpected if f in MUST_CONFORM)

    print(f"shapes   {n_shapes_triples:>4} triples  {SHAPES.name}")
    print(f"data     {n_data_triples:>4} triples  {EXAMPLE.name}")
    print(f"conforms: {conforms} (expected False — PART B violates on purpose)")
    print(f"violations: {len(got)} observed, {len(want)} expected\n")

    for key, why in sorted(EXPECTED.items()):
        print(f"  [{'OK  ' if key in got else 'MISS'}] {why}")

    problems: list[str] = []
    if conforms:
        problems.append("graph conformed — PART B violations are not being caught at all")
    for key in sorted(missed):
        problems.append(f"shape stopped firing: {EXPECTED[key]} ({key[0]}, {key[1]})")
    for f in false_positives:
        problems.append(f"FALSE POSITIVE on a conforming node: {f}")
    for f, c in sorted(unexpected):
        if f not in MUST_CONFORM:
            print(f"  [note] extra violation (not a regression): {f} / {c}")

    print()
    pattern_problems = check_pattern_escaping()
    problems.extend(pattern_problems)
    if not pattern_problems:
        print("  [OK  ] sh:pattern regexes resolve correctly (no over-escaped "
              "backslash blocking valid URLs / ORCIDs / RORs)")

    closure_problems = check_sameas_closure()
    problems.extend(closure_problems)
    if not closure_problems:
        print("  [OK  ] OWL-RL: shared ORCID -> owl:sameAs; "
              "localIdentifier collision -> no sameAs")

    if problems:
        print("\nFAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nPASS: all expected violations caught, no false positives, "
          "identity closure intact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
