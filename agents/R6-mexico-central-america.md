# R6 — Mexico and Central America coastal research facilities

## Scope
Federal, university, and NGO coastal/ocean research facilities in Mexico,
Guatemala, Belize, Honduras, El Salvador, Nicaragua, Costa Rica, and Panama.

## Sources
- https://www.gob.mx/ (Mexico — INAPESCA, CONAPESCA, CONANP, INECC, SEMAR-DIGAOHM)
- https://www.cicese.mx/
- https://www.icmyl.unam.mx/ (UNAM Instituto de Ciencias del Mar y Limnología)
- https://www.ecosur.mx/
- https://www.cinvestav.mx/ (Mérida unit — marine sciences)
- https://stri.si.edu/ (Smithsonian Tropical Research Institute — Panama)
- https://www.minae.go.cr/ (Costa Rica)
- https://www.marviva.net/ (regional NGO, HQ Panama)
- UNESCO-IOC IOCARIBE member directory
- https://obis.org/ — OBIS nodes in region

## Inputs
- Wave 1 vocab CSVs

## Outputs
- `data/raw/R6/facilities_mexico_central_america.json`
- `data/raw/R6/notes.md`

## Method
1. Start from Mexico: INAPESCA centers (CRIAP Ensenada, La Paz, Guaymas,
   Mazatlán, Manzanillo, Salina Cruz, Puerto Morelos, Tampico, Veracruz).
2. Add UNAM-ICML stations (Mazatlán, Puerto Morelos, Sisal).
3. CICESE (Ensenada) including Unidad La Paz.
4. ECOSUR Chetumal marine program.
5. Central America: CIMAR (UCR Costa Rica), MarViva regional offices, STRI
   Bocas del Toro + Naos Island (Panama), ICMyL Belize, CEM-UCA El Salvador.
6. Record funders: CONACyT (MX), PRONACES, national agencies, IDB projects.

## Known landmarks (must appear)
- CICESE — Ensenada, BC
- UNAM Instituto de Ciencias del Mar y Limnología — Mexico City HQ + Unidades
  Mazatlán, Puerto Morelos, Sisal
- INAPESCA HQ — Mexico City + CRIAP field centers
- ECOSUR — Chetumal, QR
- Smithsonian Tropical Research Institute — Panama City + Bocas del Toro
- Centro de Investigación en Ciencias del Mar y Limnología (CIMAR, UCR) — San
  José / Punta Morales, Costa Rica
- Hol Chan Marine Reserve research — Belize
- University of Belize Environmental Research Institute — Calabash Caye
