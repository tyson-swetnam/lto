---
type: Data Archive
title: "AERONET (AErosol RObotic NETwork)"
description: "NASA Goddard Space Flight Center — data-portal holding long-term observatory records."
resource: "https://aeronet.gsfc.nasa.gov/"
tags: [data-portal, rest, nasa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

AERONET federation of ~600 ground-based sun/sky photometers; CIMEL retrievals at L1/L1.5/L2. ASCII CSV via cgi-bin/print_web_data_v3. retrieved_at=2026-05-05; agent=J-A-AMERIFLUX-ARM [via J-A-AMERIFLUX-ARM]

# Access

- Archive home: <https://aeronet.gsfc.nasa.gov/>
- API root (`rest`): <https://aeronet.gsfc.nasa.gov/cgi-bin/print_web_data_v3> — see the [rest guide](./access-rest.md)
- API documentation: <https://aeronet.gsfc.nasa.gov/new_web/data_usage.html>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://aeronet.gsfc.nasa.gov/cgi-bin/print_web_data_v3?site={SITE}&year={YYYY}&month={MM}&day={DD}&year2={YYYY2}&month2={MM2}&day2={DD2}&AOD15=1&AVG=10> | curl 'https://aeronet.gsfc.nasa.gov/cgi-bin/print_web_data_v3?site=GSFC&year=2024&month=1&day=1&year2=2024&month2=12&day2=31&AOD15=1&AVG=10' |

# Depositing facilities

- **GSFC-AERO** AERONET GSFC (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [AERONET v3 L2 GSFC AOD + inversion products](https://aeronet.gsfc.nasa.gov/cgi-bin/data_display_aod_v3?site=GSFC) | csv | 1993-01-01–present | n/a |
