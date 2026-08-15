---
type: Data Archive
title: "Clean Air Status and Trends Network"
description: "U.S. Environmental Protection Agency / NPS — data-portal holding long-term observatory records."
resource: "https://www.epa.gov/castnet/"
tags: [data-portal, rest, epa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

CASTNET provides hourly ozone + weekly dry-deposition CSV downloads. EPA-operated with NPS partner sites. Public data via EPA download portal. retrieved_at=2026-05-05; agent=J-A-AMERIFLUX-ARM [via J-A-AMERIFLUX-ARM]

# Access

- Archive home: <https://www.epa.gov/castnet/>
- API root (`rest`): <https://www.epa.gov/castnet/download-data> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.epa.gov/castnet/documents-reports>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | GET | application/zip | <https://gaftp.epa.gov/castnet/CASTNET_Outgoing/data/{file}.zip> | curl -O 'https://gaftp.epa.gov/castnet/CASTNET_Outgoing/data/drydep_week_web.zip' |

# Depositing facilities

- **BBE401** CASTNET Big Bend NP (primary)

# Data products

1 addressable product catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [CASTNET BBE401 weekly dry deposition + hourly ozone](https://www.epa.gov/castnet/download-data) | csv | 1988-01-01–present | n/a |
