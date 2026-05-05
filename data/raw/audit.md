# Data Audit — cod-kmap facilities (2026-04-19)

Scanned all 108 records across R1–R8. Issues found below (≤ 20 listed).

## Null / missing coordinates (hq.lat or hq.lng = null)
None found. All HQ lat/lng are populated.
(R4-0012 R/V Falkor *location* entry has null lat/lng, which is appropriate for a mobile vessel.)

## Empty research_areas
None found.

## established = null
None found.

## funders empty or only one entry
| record_id | canonical_name | issue |
|-----------|----------------|-------|
| R4-0008 | The Nature Conservancy — Oceans Program | 1 funder only |
| R4-0009 | New England Aquarium | 1 funder only |
| R4-0012 | Schmidt Ocean Institute | 1 funder only |
| R7-0003 | INIDEP (Argentina) | 1 funder only |
| R7-0005 | IFOP (Chile) | 1 funder only |
| R3-0012 | Ocean Observatories Initiative | 1 funder only |
| R3-0013 | Long-Term Ecological Research Network | 1 funder only |
| R7-0010 | Charles Darwin Foundation | 1 funder only |

## provenance.confidence = "medium" or "low"
| record_id | canonical_name | confidence |
|-----------|----------------|------------|
| R6-0009 | CICY Unidad Ciencias del Agua | medium |
| R6-0010 | ARAP (Panama) | medium |
| R8-0004 | Gerace Research Centre | medium |
| R8-0007 | UWI Port Royal Marine Laboratory | medium |
| R8-0008 | CIBIMA (Dominican Republic) | medium |
| R8-0009 | FoProBiM (Haiti) | medium |

## Thin research_areas (only 2 slugs)
| record_id | canonical_name | current slugs |
|-----------|----------------|---------------|
| R7-0003 | INIDEP | fisheries-and-aquaculture, marine-ecosystems |
| R7-0005 | IFOP | fisheries-and-aquaculture, marine-ecosystems |
| R6-0003 | INAPESCA | fisheries-and-aquaculture, marine-ecosystems |
| R6-0010 | ARAP | fisheries-and-aquaculture, marine-policy-and-socio-economics |

## Summary
- 0 records with null hq coords
- 0 records with null established
- 0 records with empty research_areas
- 8 records with only 1 funder
- 6 records with confidence "medium" (0 "low")
- 4 records with only 2 research_area slugs (thin coverage)

## Action taken
- Confidence upgrades applied to 6 medium-confidence records where the institution
  homepage is a primary source (R6-0009, R6-0010, R8-0004, R8-0007, R8-0008, R8-0009).
- research_areas expanded for R7-0003, R7-0005, R6-0003, R6-0010.
- Could not add real secondary funders for single-funder records without risking
  fabrication; left as-is with a note.
