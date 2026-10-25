---
type: Data Archive
title: "NERRS Centralized Data Management Office"
description: "NOAA Office for Coastal Management / University of South Carolina, Baruch Marine Field Lab — observatory-network holding long-term observatory records."
resource: "https://cdmo.baruch.sc.edu/"
tags: [observatory-network, soap, nerrs-data-policy]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-10-25T17:45:12Z }
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
| data-download | POST | application/xml | <https://cdmo.baruch.sc.edu/webservices2/requests.cfc> | curl 'https://cdmo.baruch.sc.edu/webservices2/requests.cfc?wsdl'  # then SOAP exportAllParamsDateRangeXMLNew(tbl, mindate, maxdate, fieldlist); requires prior IP registration |

# Depositing facilities

- ACE Basin National Estuarine Research Reserve (primary)
- **ANERR** Apalachicola National Estuarine Research Reserve (primary)
- **CBNERR-MD** Chesapeake Bay-Maryland National Estuarine Research Reserve (primary)
- **CBNERR-VA** Chesapeake Bay-Virginia National Estuarine Research Reserve (primary)
- Connecticut National Estuarine Research Reserve (primary)
- **DNERR** Delaware National Estuarine Research Reserve (primary)
- Elkhorn Slough National Estuarine Research Reserve (primary)
- Grand Bay National Estuarine Research Reserve (primary)
- **GBNERR** Great Bay National Estuarine Research Reserve (primary)
- **GTMNERR** Guana Tolomato Matanzas National Estuarine Research Reserve (primary)
- He‘eia National Estuarine Research Reserve (primary)
- **HRNERR** Hudson River National Estuarine Research Reserve (primary)
- **JC NERR** Jacques Cousteau National Estuarine Research Reserve (primary)
- **JBNERR** Jobos Bay National Estuarine Research Reserve (primary)
- **KBNERR** Kachemak Bay National Estuarine Research Reserve (primary)
- Lake Superior National Estuarine Research Reserve (primary)
- Mission-Aransas National Estuarine Research Reserve (primary)
- **NBNERR** Narragansett Bay National Estuarine Research Reserve (primary)
- **NERRS** National Estuarine Research Reserve System (primary)
- North Carolina National Estuarine Research Reserve (primary)
- North Inlet-Winyah Bay National Estuarine Research Reserve (primary)
- Old Woman Creek National Estuarine Research Reserve (primary)
- Padilla Bay National Estuarine Research Reserve (primary)
- Rookery Bay National Estuarine Research Reserve (primary)
- San Francisco Bay National Estuarine Research Reserve (primary)
- **SINERR** Sapelo Island National Estuarine Research Reserve (primary)
- South Slough National Estuarine Research Reserve (primary)
- **TRNERR** Tijuana River National Estuarine Research Reserve (primary)
- Waquoit Bay National Estuarine Research Reserve (primary)
- Weeks Bay National Estuarine Research Reserve (primary)
- Wells National Estuarine Research Reserve (primary)
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
