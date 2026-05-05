# R-TER-NEON — National Ecological Observatory Network (all 81 sites)

## Scope

All 81 NEON field sites — 47 terrestrial + 34 aquatic — emitted as
**individual facility records**, each tagged with the `neon` network slug
and the corresponding domain. Treat each site as a long-term observatory
in its own right while preserving the NEON-as-a-network grouping.

NEON aquatic sites use `primary_sphere = "freshwater"` (streams + lakes)
or `"ocean-estuarine"` if any (currently none). NEON terrestrial sites
use `primary_sphere = "terrestrial"`. All NEON sites carry secondary
`atmosphere` because every site has a meteorological / flux tower or
phenology array.

## Sources

1. <https://www.neonscience.org/field-sites> — site directory (primary).
2. <https://www.neonscience.org/field-sites/about-field-sites> — site
   classification (core / gradient, terrestrial / aquatic, relocatable).
3. <https://www.neonscience.org/data-collection/neon-domains> — 20 domains.
4. <https://data.neonscience.org/> — data-portal URL pattern per site.
5. NEON site-specific landing pages, e.g.
   <https://www.neonscience.org/field-sites/jorn>.

## Inputs

- `schema/vocab/{spheres,networks,facility_types,ecosystem_types}.csv`.
- For domain polygons (overlay): `public/overlays/neon-domains.geojson`
  (already vendored from cod-kmap).

## Outputs

- `data/raw/R-TER-NEON/facilities_neon.json` — array of 81 records.

## Method

1. For each NEON site, emit one record with:
   - `record_id = "R-TER-NEON-<sequence>"`
   - `canonical_name` = official site name (e.g. "Jornada Experimental
     Range NEON Site").
   - `acronym` = NEON 4-letter site code (e.g. "JORN", "ABBY", "TOOL").
   - `parent_org` = "Battelle / National Ecological Observatory Network"
     (NEON is operated by Battelle for NSF).
   - `facility_type`:
     - `flux-tower` for terrestrial core sites with the NEON tower.
     - `field-station` (or `university-field-station` if hosted by one) for
       relocatable terrestrial sites.
     - `streamgage-network` for aquatic sites that are primarily NEON
       stream/lake gauges.
   - `country` = US (with PR for Domain 04 Guánica/Lajas, plus appropriate
     territory codes).
   - `networks = ["neon"]`. Add `lter` if the NEON site is co-located
     with an LTER reference site (e.g. JORN, KONZ, BART, ONAQ, NIWO,
     CPER, HARV, BONA, GUAN, OSBS, TOOL); add `usfs-rna-ef` for
     EFR-co-located sites (e.g. BART = Bartlett Experimental Forest).
   - `funders = [{ name: "NSF", relation: "parent-agency" }, { name: "Battelle", relation: "contract" }]`.
   - `data_portal_url` = `https://data.neonscience.org/data-products/explore?siteCodes=<ACRONYM>`.
   - `established` = construction-completion year (range 2014–2019 for
     most; earlier/later for some).
2. Use the NEON domain to assign `region` (e.g. "Domain 14 — Desert
   Southwest") and `ecosystem_types`.
3. Set `secondary_spheres = ["atmosphere"]` for terrestrial sites and
   `["atmosphere", "freshwater"]` for sites with both tower and stream.
4. For aquatic sites, set `facility_type = "streamgage-network"` and
   `primary_sphere = "freshwater"`, with secondary `terrestrial` (since
   they are paired to terrestrial reference sites).

## Known landmarks (must appear, all 81 NEON sites)

Domain 01 Northeast: BART (Bartlett), HARV (Harvard Forest).
Domain 02 Mid-Atlantic: SCBI (Smithsonian Conservation Biology Inst.),
SERC (Smithsonian Environmental Research Center), BLAN (Blandy Farm).
Domain 03 Southeast: OSBS (Ordway-Swisher), JERC (Jones Center), DSNY
(Disney Wilderness).
Domain 04 Atlantic Neotropical: GUAN (Guánica, PR), LAJA (Lajas, PR).
Domain 05 Great Lakes: STEI (Steigerwaldt-Chequamegon), TREE (Treehaven),
UNDE (UNDERC).
Domain 06 Prairie Peninsula: KONZ (Konza), KONA (Konza Cropland), UKFS
(University of Kansas Field Station).
Domain 07 Appalachians/Cumberland Plateau: GRSM (Great Smoky Mountains),
MLBS (Mountain Lake), ORNL (Oak Ridge).
Domain 08 Ozarks Complex: DELA (Dead Lake), LENO (Lenoir Landing), TALL
(Talladega).
Domain 09 Northern Plains: DCFS (Dakota Coteau), NOGP (Northern Great
Plains), WOOD (Woodworth).
Domain 10 Central Plains: CPER (Central Plains Experimental Range), STER
(North Sterling), RMNP (Rocky Mountain NP).
Domain 11 Southern Plains: CLBJ (Caddo-LBJ), OAES (Marvin Klemme).
Domain 12 Northern Rockies: YELL (Yellowstone NPS).
Domain 13 Southern Rockies / Colorado Plateau: NIWO (Niwot Ridge), MOAB
(Moab).
Domain 14 Desert Southwest: JORN (Jornada), SRER (Santa Rita).
Domain 15 Great Basin: ONAQ (Onaqui).
Domain 16 Pacific Northwest: ABBY (Abby Road), WREF (Wind River
Experimental Forest).
Domain 17 Pacific Southwest: SJER (San Joaquin), SOAP (Soaproot Saddle),
TEAK (Lower Teakettle).
Domain 18 Tundra: BARR (Utqiaġvik / Barrow), TOOL (Toolik).
Domain 19 Taiga: BONA (Bonanza Creek), DEJU (Delta Junction), HEAL
(Healy).
Domain 20 Pacific Tropical: PUUM (Pu'u Maka'ala, HI).

Plus 34 aquatic sites: ARIK, BARC, BIGC, BLDE, BLUE, BLWA, CARI,
COMO, CRAM, CUPE, FLNT, GUIL, HOPB, KING, LECO, LEWI, LIRO, MART,
MAYF, MCDI, MCRA, OKSR, POSE, PRIN, PRLA, PRPO, REDB, SUGG, SYCA,
TECR, TOMB, TOOK, WALK, WLOU.
