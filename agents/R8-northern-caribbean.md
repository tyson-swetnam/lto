# R8 — Northern Caribbean coastal research facilities

## Scope
Island nations and territories in the northern Caribbean: Puerto Rico, US Virgin
Islands, Bahamas, Cuba, Jamaica, Cayman Islands, Haiti, Dominican Republic,
Turks & Caicos. Also include British Virgin Islands and the northern Lesser
Antilles (Anguilla, St. Maarten/St. Martin, Saint-Barthélemy, St. Kitts & Nevis,
Antigua & Barbuda, Montserrat) where research facilities exist.

Note: PR and VI are US territories; also appear in R3 (CARICOOS) and sometimes
R2. Use R8 as the primary record for PR/VI facilities that are neither federal
nor university owned, and set provenance accordingly to help D2 dedup.

## Sources
- https://caricoos.org/ (IOOS RA, Puerto Rico)
- http://www.caribbeancoralreefs.com/ (CARICOMP historical)
- https://cermes.cavehill.uwi.edu/ (UWI Centre for Resource Management and
  Environmental Studies)
- https://www.mona.uwi.edu/dbml/ (UWI Discovery Bay Marine Lab, Jamaica)
- https://www.cim.uh.cu/ (Cuba Centro de Investigaciones Marinas)
- https://www.tcitrust.tc/ (Turks & Caicos)
- https://www.perryinstitute.org/ (Bahamas)
- https://cmrc.org/ (Caribbean Marine Research Center — Bahamas, if active)
- UNESCO-IOC IOCARIBE member directory

## Inputs
- Wave 1 vocab CSVs
- R3 output (CARICOOS member list)

## Outputs
- `data/raw/R8/facilities_northern_caribbean.json`
- `data/raw/R8/notes.md`

## Method
1. Start with PR/VI facilities: UPR-Mayagüez Department of Marine Sciences
   (Magueyes Island), UPR-RP Center for Applied Tropical Ecology & Conservation,
   Univ of Virgin Islands Center for Marine & Environmental Studies.
2. Bahamas: Perry Institute for Marine Science (Lee Stocking / Exuma / Nassau),
   BREEF, Atlantis Blue Project, Gerace Research Centre (San Salvador).
3. Cuba: Centro de Investigaciones Marinas (U Havana), Centro Nacional de
   Áreas Protegidas, Acuario Nacional de Cuba.
4. Jamaica: UWI Discovery Bay Marine Laboratory, Port Royal Marine Lab (UWI).
5. Dominican Republic: Centro de Investigaciones de Biología Marina (CIBIMA-
   UASD), Fundación Dominicana de Estudios Marinos.
6. Haiti: Fondation pour la Protection de la Biodiversité Marine (FoProBiM).
7. Lesser Antilles: UWI-CERMES (Cave Hill, Barbados — technically eastern
   Caribbean but serves the region); St. Kitts CBEMN sites.

## Known landmarks (must appear)
- UPR-Mayagüez Department of Marine Sciences — Lajas (Magueyes), PR
- University of the Virgin Islands — St. Thomas + St. Croix
- CARICOOS — Mayagüez, PR (cross-listed with R3)
- Perry Institute for Marine Science — Nassau + Lee Stocking, Bahamas
- UWI Discovery Bay Marine Lab — Jamaica
- UWI Port Royal Marine Laboratory — Jamaica
- Centro de Investigaciones Marinas, U. de La Habana — Havana, Cuba
- Acuario Nacional de Cuba — Havana, Cuba
- Gerace Research Centre — San Salvador, Bahamas
- Turks and Caicos Reef Fund / DECR — Providenciales, TCI
- CIBIMA-UASD — Santo Domingo, DR
- UWI-CERMES — Cave Hill, Barbados
