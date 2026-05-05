# synthesis-networks (upstream)

This directory mirrors the data released by the COMPASS project alongside
Myers-Pigg et al., *Advancing the understanding of coastal disturbances with a
network-of-networks approach* (Ecosphere).

- Upstream repository: https://github.com/COMPASS-DOE/synthesis-networks
- Upstream commit at import: `main` branch as of 2026-04-23
- Upstream license: MIT — Copyright (c) 2023 Coastal Observations, Mechanisms,
  and Predictions Across Systems and Scales (COMPASS) Project

## Files

| File | Description |
|------|-------------|
| `Networks_table_updated.csv` | 52 observation, experiment, and monitoring networks with funding agency, management structure, geographic scope, disturbance flag, network category (CDEON / EON / LTMP / LTRN / ORC), and ecosystem-domain flags (Terrestrial, Freshwater, Marine, Atmospheric, Coastal). |
| `hexagons_Ecoregion_TableToExcel.xlsx` | Per-hexagon attribute table: WSA9 ecoregion, dominant land cover, area, per-hexagon counts of hazards (Hurricane … SLR) and counts of network sites within 50 km. Used for Figure 2 of the paper. |

## Relationship to cod-kmap

cod-kmap's existing `schema/vocab/networks.csv` lists networks that operate
coastal / ocean-observing facilities. The synthesis-networks dataset is broader
(including terrestrial, atmospheric, and freshwater networks studied in the
Ecosphere paper) and adds attributes we do not yet capture:

- management structure (`Bottom-Up` / `Hybrid` / `Directed`)
- primary funding agency
- disturbance-science flag
- network category (CDEON / EON / LTMP / LTRN / ORC)
- ecosystem-domain flags

See `agents/R10-synthesis-networks.md` for the planned harmonization path.
