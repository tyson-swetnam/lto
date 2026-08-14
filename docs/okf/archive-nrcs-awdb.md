---
type: Data Archive
title: "NRCS Air & Water Database (SCAN / SNOTEL / SNOLITE / CSAS)"
description: "USDA Natural Resources Conservation Service — observatory-network holding long-term observatory records."
resource: "https://wcc.sc.egov.usda.gov/"
tags: [observatory-network, soap, public-domain-us]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

SOAP/WSDL Air-and-Water-Database web service exposes Soil Climate Analysis Network (SCAN; ~219 stations), SNOTEL (~900+ snow-pack stations across 13 western states + Alaska), SNOLITE, and CSAS networks. Hourly + daily CSV via Report Generator and getData / getStationMetadata calls. NWCC station IDs are numeric (e.g. 2017 = Nunn #1 SCAN). retrieved_at=2026-05-06; agent=J-A-USDA [via J-A-USDA]

# Access

- Archive home: <https://wcc.sc.egov.usda.gov/>
- API root (`soap`): <https://wcc.sc.egov.usda.gov/awdbWebService/services> — see the [soap guide](./access-rest.md)
- API documentation: <https://wcc.sc.egov.usda.gov/web_service/AWDB_Web_Service_Reference.htm>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | text/csv | <https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customMultiTimeSeriesGroupByStationReport/{interval}/{station-triplet}/{vars}> | curl 'https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customMultiTimeSeriesGroupByStationReport/hourly/2017:CO:SCAN%7Cid=%22%22%7Cname/-167,0/SMS,STO,TOBS,PREC' |
| landing-page | GET | text/html | <https://wcc.sc.egov.usda.gov/nwcc/site?sitenum={station-id}> | curl 'https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=2037' |
| listing | GET | application/json | <https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations> | curl 'https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations?networkCds=SCAN&returnReservoirMetadata=false' |
| service-description | GET | application/xml | <https://wcc.sc.egov.usda.gov/awdbWebService/services?WSDL> | curl 'https://wcc.sc.egov.usda.gov/awdbWebService/services?WSDL' |

# Depositing facilities

- **SCAN-AdamsRanch** Adams Ranch SCAN Station #2001 (primary)
- **ATG-SNTL** Atigun Pass SNOTEL (primary)
- **BRK-SNTL** Brooks Lake SNOTEL (primary)
- **SCAN-Bushland2** Bushland #2 SCAN Station #2002 (primary)
- **SCAN-Crossroads** Crossroads SCAN Station #2003 (primary)
- **LYM-SNTL** Glacier Peak Snotel / Lyman Lake Snow Pillow (primary)
- **SCAN-Goodwell** Goodwell #2 SCAN Station #2034 (primary)
- **HYD-SNTL** Hayden Pass SNOTEL (primary)
- **IND-SNTL** Independence Mine SNOTEL (primary)
- **SCAN-LittleRiver** Little River SCAN Station #2009 (primary)
- **SCAN-Mahantango** Mahantango Creek SCAN Station #2030 (primary)
- **SCAN-MammothCave** Mammoth Cave SCAN Station #2031 (primary)
- **MAM-SNTL** Mammoth Pass SNOTEL (primary)
- **SCAN-Nunn** Nunn #1 SCAN Station #2017 (primary)
- **PAR-SNTL** Paradise SNOTEL (Mount Rainier) (primary)
- **SCAN-PowderMill** Powder Mill SCAN Station #2027 (primary)
- **SCAN-Reynolds** Reynolds Creek SCAN Station #2037 (primary)
- **TRN-SNTL** Trinity Lake SNOTEL (Bonanza Creek vicinity) (primary)
- **SCAN-WG1** Walnut Gulch #1 SCAN Station #2026 (primary)

# Data products

13 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [SCAN #2001 Adams Ranch hourly soil moisture, soil temperature, air temperature, precipitation, RH](https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customMultiTimeSeriesGroupByStationReport/hourly/2001:NM:SCAN%7Cid=%22%22%7Cname/-167,0/SMS,STO,TOBS,PREC,RHUM) | csv | 1996-10-01–present | n/a |
| [SCAN #2017 Nunn #1 hourly soil moisture / temperature / climate](https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=2017) | csv | 1997-08-01–present | n/a |
| [SCAN #2026 Walnut Gulch #1 hourly soil moisture / temperature / climate](https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=2026) | csv | 2002-08-01–present | n/a |
| [SCAN #2027 Powder Mill (BARC) hourly soil moisture / temperature / climate](https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=2027) | csv | 2002-09-01–present | n/a |
| [SCAN #2037 Reynolds Creek hourly soil moisture / temperature / climate](https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=2037) | csv | 2002-10-01–present | n/a |
| [SNOTEL Atigun Pass Daily SWE / Precipitation / Air Temp](https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/daily/957:AK:SNTL%7Cid=%22%22%7Cname/POR_BEGIN,POR_END/WTEQ::value,PREC::value,TAVG::value,TMIN::value,TMAX::value,SNWD::value) | csv | 1980-01-01–present | n/a |
| [SNOTEL Brooks Lake Daily SWE / Precipitation / Air Temp](https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/daily/352:WY:SNTL%7Cid=%22%22%7Cname/POR_BEGIN,POR_END/WTEQ::value,PREC::value,TAVG::value,TMIN::value,TMAX::value,SNWD::value) | csv | 1961-01-01–present | n/a |
| [SNOTEL Hayden Pass Daily SWE / Precipitation / Air Temp](https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/daily/522:CO:SNTL%7Cid=%22%22%7Cname/POR_BEGIN,POR_END/WTEQ::value,PREC::value,TAVG::value,TMIN::value,TMAX::value,SNWD::value) | csv | 1980-01-01–present | n/a |
| [SNOTEL Independence Mine Daily SWE / Precipitation / Air Temp](https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/daily/1091:AK:SNTL%7Cid=%22%22%7Cname/POR_BEGIN,POR_END/WTEQ::value,PREC::value,TAVG::value,TMIN::value,TMAX::value,SNWD::value) | csv | 1980-01-01–present | n/a |
| [SNOTEL Lyman Lake / Glacier Peak Daily SWE / Precipitation / Air Temp](https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/daily/685:WA:SNTL%7Cid=%22%22%7Cname/POR_BEGIN,POR_END/WTEQ::value,PREC::value,TAVG::value,TMIN::value,TMAX::value,SNWD::value) | csv | 1980-01-01–present | n/a |
