# R7 — South America coastal research facilities

## Scope
Coastal and marine research facilities on the Atlantic and Pacific coasts of
South America — Colombia, Venezuela, Guyana, Suriname, French Guiana (overseas
department of France — still include), Brazil, Uruguay, Argentina, Chile,
Peru, Ecuador (including Galápagos).

## Sources
- https://www.invemar.org.co/ (Colombia)
- https://www.imarpe.gob.pe/imarpe/ (Peru)
- https://www.inidep.edu.ar/ (Argentina)
- https://cenpat.conicet.gov.ar/ (CENPAT, Puerto Madryn)
- https://www.ifop.cl/ (Chile)
- https://www.shoa.cl/ (Chilean naval hydrographic)
- https://www.furg.br/ (FURG, Brazil)
- https://www.usp.br/ (USP IO, Brazil)
- https://www.io.usp.br/
- https://www.udec.cl/ (Universidad de Concepción — COPAS)
- https://www.inpa.gov.br/ (INPA coastal-Amazon)
- https://www.dinara.gub.uy/ (Uruguay)
- https://www.inocar.mil.ec/ (Ecuador naval)
- UNESCO-IOC member state directory; OBIS regional nodes

## Inputs
- Wave 1 vocab CSVs

## Outputs
- `data/raw/R7/facilities_south_america.json`
- `data/raw/R7/notes.md`

## Method
1. Enumerate national oceanographic / fisheries agencies per country.
2. Add leading university marine institutes (USP-IO, FURG-IO, UCV-IOV,
   UdeChile-CCO, UdeC-COPAS, U Magallanes, UFRJ-Oceanografia).
3. Capture CONICET institutes in Argentina (CENPAT, IBIOMAR, IADO).
4. Note Galápagos (Charles Darwin Foundation) separately — key landmark.
5. Record national funders (CONICET, CAPES, CNPq, CONICYT/ANID, CONCYTEC, etc.).

## Known landmarks (must appear)
- INVEMAR — Santa Marta, Colombia
- IMARPE — Callao, Peru
- INIDEP — Mar del Plata, Argentina
- CENPAT-CONICET — Puerto Madryn, Argentina
- IFOP — Valparaíso + regional offices, Chile
- SHOA — Valparaíso, Chile
- Universidade Federal do Rio Grande (FURG) — Rio Grande, RS, Brazil
- Instituto Oceanográfico da USP — São Paulo + Ubatuba + Cananéia
- COPAS Sur-Austral (UdeC) — Concepción, Chile
- Charles Darwin Foundation — Puerto Ayora, Galápagos, Ecuador
- INOCAR — Guayaquil, Ecuador
- DINARA — Montevideo, Uruguay
- Universidad del Magallanes (CHAIM / IDEAL) — Punta Arenas, Chile
- IVIC / EDIMAR — Venezuela
