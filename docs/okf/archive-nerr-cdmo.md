---
type: Data Archive
title: "NERRS Centralized Data Management Office"
description: "NOAA Office for Coastal Management / University of South Carolina, Baruch Marine Field Lab — observatory-network holding long-term observatory records."
resource: "https://cdmo.baruch.sc.edu/"
tags: [observatory-network, soap, nerrs-data-policy]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Operates the System-Wide Monitoring Program (SWMP) for all 30 NERR reserves. Per-reserve, per-station files (water-quality datasonde, met, nutrients) downloadable via Advanced Query System (AQS) and via SOAP web services. CSV/ZIP per station per year. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://cdmo.baruch.sc.edu/>
- API root (`soap`): <https://cdmo.baruch.sc.edu/aqs/> — see the [soap guide](./access-rest.md)
- API documentation: <https://cdmo.baruch.sc.edu/data/qaqc.cfm>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/zip | <https://cdmo.baruch.sc.edu/aqs/zips/{station}{year}.zip> | curl -O https://cdmo.baruch.sc.edu/aqs/zips/grbgbwq2023.zip |
| data-download | POST | application/xml | <https://cdmo.baruch.sc.edu/webservices2/requests.cfc> | curl -X POST -d 'method=exportAllParamsXMLNew&Station_Code=grbgbwq&Min_Date=2023-01-01&Max_Date=2023-12-31' https://cdmo.baruch.sc.edu/webservices2/requests.cfc |

# Depositing facilities

- **NERR** ACE Basin NERR (primary)
- **NERR** Apalachicola NERR (primary)
- **NERR** Chesapeake Bay Maryland NERR (primary)
- **NERR** Chesapeake Bay Virginia NERR (primary)
- **NERR** Delaware NERR (primary)
- **NERR** Elkhorn Slough NERR (primary)
- **NERR** Grand Bay NERR (primary)
- **NERR** Great Bay NERR (primary)
- **NERR** Guana Tolomato Matanza NERR (primary)
- **NERR** He'eia NERR (primary)
- **NERR** Hudson River NERR (primary)
- **NERR** Jacques Cousteau NERR (primary)
- **NERR** Jobos Bay NERR (primary)
- **NERR** Kachemak Bay NERR (primary)
- **NERR** Lake Superior NERR (primary)
- **NERR** Mission Aransas NERR (primary)
- **NERR** Narragansett Bay NERR (primary)
- **NERRS** National Estuarine Research Reserve System (primary)
- **NERR** North Carolina NERR (primary)
- **NERR** North Inlet-Winyah Bay NERR (primary)
- **NERR** Old Woman Creek NERR (primary)
- **NERR** Padilla Bay NERR (primary)
- **NERR** Rookery Bay NERR (primary)
- **NERR** San Francisco Bay NERR (primary)
- **NERR** Sapelo Island NERR (primary)
- **NERR** South Slough NERR (primary)
- **NERR** Tijuana River NERR (primary)
- **NERR** Waquoit Bay NERR (primary)
- **NERR** Weeks Bay NERR (primary)
- **NERR** Wells NERR (primary)
- **OCM** NOAA Office for Coastal Management (host)

# Data products

29 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [ACE Basin NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=ace) | csv | 1995-01-01–present | n/a |
| [Apalachicola NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=apa) | csv | 1995-01-01–present | n/a |
| [Chesapeake Bay Maryland NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=cbm) | csv | 1995-01-01–present | n/a |
| [Chesapeake Bay Virginia NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=cbv) | csv | 1995-01-01–present | n/a |
| [Delaware NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=del) | csv | 1995-01-01–present | n/a |
| [Elkhorn Slough NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=elk) | csv | 1995-01-01–present | n/a |
| [Grand Bay NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=grb) | csv | 1999-01-01–present | n/a |
| [Great Bay NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=grb) | csv | 1995-01-01–present | n/a |
| [Guana Tolomato Matanzas NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=gtm) | csv | 2002-01-01–present | n/a |
| [He'eia NERR System-Wide Monitoring Program (SWMP)](https://cdmo.baruch.sc.edu/aqs/zips.cfm?reserve=hee) | csv | 2017-01-01–present | n/a |
