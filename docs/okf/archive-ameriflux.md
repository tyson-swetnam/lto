---
type: Data Archive
title: "AmeriFlux Network Data Archive"
description: "Lawrence Berkeley National Laboratory (DOE BER) — repository holding long-term observatory records."
resource: "https://ameriflux.lbl.gov/"
tags: [repository, rest, ameriflux-data-policy]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

AmeriFlux Management Project (AMP) at LBNL. Hosts BASE format (CSV, half-hourly) and FLUXNET2015-style processed (NetCDF) eddy-covariance data for ~600 sites across the Americas. Per-site DOIs under 10.17190/AMF/<digit-suffix>; suffix differs per site. Data download requires accepting AmeriFlux Data Policy (CC-BY-4.0 or CC-BY-NC-4.0 by site). retrieved_at=2026-05-05; agent=J-A-AMERIFLUX-ARM [via J-A-AMERIFLUX-ARM]

# Access

- Archive home: <https://ameriflux.lbl.gov/>
- API root (`rest`): <https://ameriflux.lbl.gov/data/download-data/> — see the [rest guide](./access-rest.md)
- API documentation: <https://ameriflux.lbl.gov/data/data-processing-pipelines/>
- DOIs minted here start with `10.17190`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | POST | application/zip | <https://ameriflux.lbl.gov/data/download-data/> | POST with auth token + selected SITE_IDs (BASE or FLUXNET2015) — Data License acceptance required |
| metadata | GET | text/html | <https://ameriflux.lbl.gov/sites/siteinfo/{SITE_ID}> | curl https://ameriflux.lbl.gov/sites/siteinfo/US-Ha1 |
| metadata | GET | application/json | <https://amfcdn.lbl.gov/api/v1/site_display/AmeriFlux/{SITE_ID}> | curl https://amfcdn.lbl.gov/api/v1/site_display/AmeriFlux/US-Ha1 |

# Depositing facilities

- **US-Me2** AmeriFlux Metolius Mature Pine (primary)
- **US-MMS** AmeriFlux Morgan Monroe State Forest (primary)
- **US-Var** AmeriFlux Vaira Ranch (primary)
- **US-Bo1** Bondville AmeriFlux Tower (primary)
- **US-Ha1** Harvard Forest EMS Tower (primary)
- **US-Ho1** Howland Forest Main Tower (primary)
- **US-NR1** Niwot Ridge Forest Tower (primary)
- **US-PFa** WLEF / Park Falls Tall Tower (primary)
- **GUAN-SF** Bosque Estatal de Guánica (Guánica State Forest) (secondary)
- **JIE-CTR** Jones Center at Ichauway (secondary)
- **ORNL-NERP** Oak Ridge National Environmental Research Park (secondary)
- **USDA-ARS-EL-RENO** USDA-ARS Grazinglands Research Laboratory (El Reno) (secondary)
- **WBW-LTHS** Walker Branch Watershed Long-Term Hydrologic Station (secondary)
- **WREF-EF** Wind River Experimental Forest (secondary)

# Data products

10 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [AmeriFlux US-AR1 / US-AR2 ARS-El Reno tallgrass-prairie eddy-covariance towers](https://ameriflux.lbl.gov/sites/siteinfo/US-AR1) | csv | 2009-01-01–present | n/a |
| [AmeriFlux US-Bo1 Bondville BASE + FLUXNET2015](https://ameriflux.lbl.gov/sites/siteinfo/US-Bo1) | csv | 1996-01-01–2008-12-31 | n/a |
| [AmeriFlux US-Ha1 Harvard Forest EMS Tower BASE + FLUXNET2015 release](https://ameriflux.lbl.gov/sites/siteinfo/US-Ha1) | csv | 1991-01-01–present | n/a |
| [AmeriFlux US-Ho1 Howland Forest Main Tower BASE](https://ameriflux.lbl.gov/sites/siteinfo/US-Ho1) | csv | 1996-01-01–present | n/a |
| [AmeriFlux US-MMS Morgan Monroe State Forest BASE + FLUXNET2015](https://ameriflux.lbl.gov/sites/siteinfo/US-MMS) | csv | 1999-01-01–present | n/a |
| [AmeriFlux US-Me2 Metolius mature ponderosa pine BASE + FLUXNET2015](https://ameriflux.lbl.gov/sites/siteinfo/US-Me2) | csv | 2002-07-01–present | n/a |
| [AmeriFlux US-NR1 Niwot Ridge Forest BASE + FLUXNET2015](https://ameriflux.lbl.gov/sites/siteinfo/US-NR1) | csv | 1998-11-01–present | n/a |
| [AmeriFlux US-PFa Park Falls / WLEF Tall Tower BASE](https://ameriflux.lbl.gov/sites/siteinfo/US-PFa) | csv | 1995-01-01–present | n/a |
| [AmeriFlux US-Var Vaira Ranch BASE + FLUXNET2015](https://ameriflux.lbl.gov/sites/siteinfo/US-Var) | csv | 2000-10-01–present | n/a |
| [AmeriFlux US-Wrc Wind River Crane Site eddy-covariance tower](https://ameriflux.lbl.gov/sites/siteinfo/US-Wrc) | csv | 1998-01-01–2024-12-31 | n/a |
