---
type: Data Archive
title: "NOAA Center for Operational Oceanographic Products and Services Data Portal"
description: "NOAA / National Ocean Service — data-portal holding long-term observatory records."
resource: "https://tidesandcurrents.noaa.gov/"
tags: [data-portal, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

CO-OPS operates the National Water Level Observation Network (NWLON), PORTS, and the National Current Observation Program. REST API serves water levels, predictions, met, currents in CSV/JSON/XML. Also Derived Product API (api.tidesandcurrents.noaa.gov/dpapi/prod/) for hi-tide flooding and sea-level trends. retrieved_at=2026-05-06; agent=K-USACE-NRL-NASA [via K-USACE-NRL-NASA]

# Access

- Archive home: <https://tidesandcurrents.noaa.gov/>
- API root (`rest`): <https://api.tidesandcurrents.noaa.gov/api/prod/> — see the [rest guide](./access-rest.md)
- API documentation: <https://api.tidesandcurrents.noaa.gov/api/prod/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/json | <https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product={product}&station={id}&begin_date={YYYYMMDD}&end_date={YYYYMMDD}&datum={datum}&units={units}&time_zone={tz}&format={format}> | curl 'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&station=8518750&begin_date=20240101&end_date=20240107&datum=MLLW&units=metric&time_zone=gmt&format=json&application=lto' |
| data-download | GET | application/json | <https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/htf/htf_annual.json?station={id}&year={YYYY}> | curl 'https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/htf/htf_annual.json?station=8518750&year=2023' |
| metadata | GET | application/json | <https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type={type}> | curl 'https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=waterlevels' |

# Depositing facilities

- **CO-OPS** NOAA Center for Operational Oceanographic Products and Services (primary)

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [NWLON Verified 6-Minute Water Levels](https://tidesandcurrents.noaa.gov/stations.html?type=Water+Levels) | csv | 1854-01-01–present | n/a |
| [Sea Level Trends — Relative Mean Sea Level Trends](https://tidesandcurrents.noaa.gov/sltrends/) | json | 1854-01-01–present | n/a |
