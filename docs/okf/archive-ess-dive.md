---
type: Data Archive
title: "ESS-DIVE — Environmental System Science Data Infrastructure for a Virtual Ecosystem"
description: "Lawrence Berkeley National Laboratory / U.S. DOE Office of Biological and Environmental Research (BER) — repository holding long-term observatory records."
resource: "https://ess-dive.lbl.gov/"
tags: [repository, rest, cc-by-4.0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Primary repository for DOE BER Earth and Environmental Systems Sciences (terrestrial ecosystem, watershed, subsurface biogeochem, ARM, SBR, AmeriFlux). DataONE-compatible (Metacat-style). DOIs minted as 10.15485/<7-digit identifier>. Sandbox at https://api-sandbox.ess-dive.lbl.gov/ ; production at https://api.ess-dive.lbl.gov/. retrieved_at=2026-05-06; agent=J-A-ESS-DIVE-DOE [via J-A-ESS-DIVE-DOE]

# Access

- Archive home: <https://ess-dive.lbl.gov/>
- API root (`rest`): <https://api.ess-dive.lbl.gov/> — see the [rest guide](./access-rest.md)
- API documentation: <https://docs.ess-dive.lbl.gov/programmatic-tools/ess-dive-dataset-api>
- DOIs minted here start with `10.15485`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| landing | GET | text/html | <https://data.ess-dive.lbl.gov/datasets/doi:{doi}> | https://data.ess-dive.lbl.gov/datasets/doi:10.15485/1577260 |
| metadata | GET | application/json | <https://api.ess-dive.lbl.gov/packages/{doi}> | curl https://api.ess-dive.lbl.gov/packages/doi%3A10.15485%2F1577260 |
| search | GET | application/json | <https://api.ess-dive.lbl.gov/packages> | curl 'https://api.ess-dive.lbl.gov/packages?text=NGEE-Arctic&rowStart=1&pageSize=25' |

# Depositing facilities

- **EAST-RIVER** East River Watershed Long-Term Critical Zone Observatory (LTREB) (primary)
- **ORNL-NERP** Oak Ridge National Environmental Research Park (primary)
- **GUAN-SF** Bosque Estatal de Guánica (Guánica State Forest) (secondary)
- **MAR** Marcell Experimental Forest (secondary)
- **USDA-ARS-EL-RENO** USDA-ARS Grazinglands Research Laboratory (El Reno) (secondary)
- **USDA-ARS-AK** USDA-ARS Subarctic Agricultural Research Unit (Fairbanks) (secondary)
- **WBW-LTHS** Walker Branch Watershed Long-Term Hydrologic Station (secondary)
