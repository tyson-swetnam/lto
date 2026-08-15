---
type: Data Archive
title: "DOE ARM Data Discovery (Atmospheric Radiation Measurement)"
description: "U.S. Department of Energy / Office of Science / BER — data-portal holding long-term observatory records."
resource: "https://adc.arm.gov/"
tags: [data-portal, rest, unknown]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

ARM Data Discovery serves NetCDF datastreams keyed by <site><instrument><facility>.<level> (e.g. sgpmetE13.b1). Open data (no fee) but requires a free ARM/OpenID account for download. Per-datastream DOIs under 10.5439/<suffix>. license=arm-data-policy (not in vocab; using 'unknown'). retrieved_at=2026-05-05; agent=J-A-AMERIFLUX-ARM [via J-A-AMERIFLUX-ARM]

# Access

- Archive home: <https://adc.arm.gov/>
- API root (`rest`): <https://adc.arm.gov/discovery/> — see the [rest guide](./access-rest.md)
- API documentation: <https://adc.arm.gov/armlive/>
- DOIs minted here start with `10.5439`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/json | <https://adc.arm.gov/armlive/data/query?user={USER}:{TOKEN}&ds={DATASTREAM}&start={YYYY-MM-DD}&end={YYYY-MM-DD}> | curl 'https://adc.arm.gov/armlive/data/query?user=alice:abc123&ds=sgpmetE13.b1&start=2024-01-01&end=2024-01-31' |
| search | GET | text/html | <https://adc.arm.gov/discovery/> | https://adc.arm.gov/discovery/#/results/site_code::sgp/instrument_class_code::met |

# Depositing facilities

- **ARM-NSA** DOE ARM North Slope of Alaska (primary)
- **ARM-SGP** DOE ARM Southern Great Plains Central Facility (primary)

# Data products

3 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [ARM NSA Surface Meteorological Station (MET) C1 b1](https://adc.arm.gov/discovery/#/results/site_code::nsa/instrument_class_code::met) | netcdf | 1998-01-01–present | n/a |
| [ARM SGP Carbon Dioxide Flux Measurement Systems (CO2FLX) C1](https://adc.arm.gov/discovery/#/results/instrument_code::co2flx) | netcdf | 2003-01-01–present | n/a |
| [ARM SGP Surface Meteorological Station (MET) E13 b1](https://adc.arm.gov/discovery/#/results/instrument_class_code::met) | netcdf | 1993-01-01–present | n/a |
