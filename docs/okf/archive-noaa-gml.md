---
type: Data Archive
title: "NOAA Global Monitoring Laboratory"
description: "NOAA Office of Oceanic and Atmospheric Research — data-portal holding long-term observatory records."
resource: "https://gml.noaa.gov/"
tags: [data-portal, ftp, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

NOAA GML hosts atmospheric baseline (CCGG, HATS, Ozone+Water Vapor, GRAD/SURFRAD, AGGI). FTP at aftp.cmdl.noaa.gov + HTTPS browse. Many products under 10.15138 (Mauna Loa CO2 etc.); not all GML data has a DOI. retrieved_at=2026-05-05; agent=J-A-AMERIFLUX-ARM [via J-A-AMERIFLUX-ARM]

# Access

- Archive home: <https://gml.noaa.gov/>
- API root (`ftp`): <https://gml.noaa.gov/aftp/>
- API documentation: <https://gml.noaa.gov/data/>
- DOIs minted here start with `10.15138`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/plain | <https://gml.noaa.gov/aftp/data/radiation/surfrad/{Site_State}/{YYYY}/{site}{YYDOY}.dat> | curl https://gml.noaa.gov/aftp/data/radiation/surfrad/Bondville_IL/2024/bon24001.dat |
| data-download | GET | text/csv | <https://gml.noaa.gov/aftp/data/> | curl -O 'https://gml.noaa.gov/aftp/data/trace_gases/co2/in-situ/surface/txt/co2_mlo_surface-insitu_1_ccgg_MonthlyData.txt' |

# Depositing facilities

- **SMO** American Samoa Atmospheric Baseline Observatory (primary)
- **BRW** Barrow Atmospheric Baseline Observatory (primary)
- **MLO** Mauna Loa Observatory (primary)
- **SRF-BON** SURFRAD Bondville (primary)
- **SPO** South Pole Atmospheric Baseline Observatory (primary)
- **THD** Trinidad Head Atmospheric Baseline Observatory (primary)

# Data products

4 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [NOAA GML Barrow continuous CO2 + flask](https://gml.noaa.gov/dv/iadv/) | csv | 1973-01-01–present | n/a |
| [NOAA GML Mauna Loa monthly + weekly atmospheric CO2](https://gml.noaa.gov/ccgg/trends/data.html) | csv | 1958-03-01–present | n/a |
| [NOAA GML South Pole continuous CO2 + flask](https://gml.noaa.gov/dv/iadv/) | csv | 1957-01-01–present | n/a |
| [NOAA SURFRAD Bondville 1-min surface radiation](https://gml.noaa.gov/aftp/data/radiation/surfrad/Bondville_IL/) | text-fixed | 1995-04-01–present | n/a |
