---
type: Data Archive
title: "Total Carbon Column Observing Network (TCCON) Data Archive"
description: "Caltech (lead) / NASA / DOE / international partners — repository holding long-term observatory records."
resource: "https://tccondata.org/"
tags: [repository, rest, cc-by-4.0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

TCCON archive (HDF5/NetCDF, GGG-processed Xgas retrievals from ground-based FTS). Per-site DOIs under 10.14291/TCCON.GGG2020.<SITE>R<rev> for the GGG2020 release. Wiki at tccon-wiki.caltech.edu lists all sites + per-site lead PIs. retrieved_at=2026-05-05; agent=J-A-AMERIFLUX-ARM [via J-A-AMERIFLUX-ARM]

# Access

- Archive home: <https://tccondata.org/>
- API root (`rest`): <https://tccondata.org/> — see the [rest guide](./access-rest.md)
- API documentation: <https://tccon-wiki.caltech.edu/>
- DOIs minted here start with `10.14291`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/x-netcdf | <https://tccondata.org/> | Browse tccondata.org → site → release; download per-site NetCDF |

# Depositing facilities

- **TCCON-LMT** TCCON Lamont (primary)
- **ARM-SGP** DOE ARM Southern Great Plains Central Facility (secondary)
- **US-PFa** WLEF / Park Falls Tall Tower (secondary)

# Data products

2 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [TCCON GGG2020.R0 Lamont, Oklahoma, USA](https://tccondata.org/) | netcdf | 2008-07-01–present | n/a |
| [TCCON GGG2020.R0 Park Falls, Wisconsin, USA](https://tccondata.org/) | netcdf | 2004-06-01–present | n/a |
