---
type: Data Archive
title: "NOAA National Marine Sanctuaries Data"
description: "NOAA Office of National Marine Sanctuaries — program holding long-term observatory records."
resource: "https://sanctuaries.noaa.gov/science/data.html"
tags: [program, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

ONMS science portal aggregates condition reports + per-sanctuary monitoring datasets. No single canonical API; per-sanctuary feeds via SECOORA/CeNCOOS/NCEI/PIFSC ERDDAP. Programmatic access goes through NCEI archival packages. retrieved_at=2026-05-06; agent=J-A-OCEAN-AGGS [via J-A-OCEAN-AGGS]

# Access

- Archive home: <https://sanctuaries.noaa.gov/science/data.html>
- API documentation: <https://sanctuaries.noaa.gov/science/condition/>

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [noaa-coastwatch-pds](https://registry.opendata.aws/noaa-coastwatch/) | us-east-1 | public-read | `noaa-coastwatch-pds/coastwatch/products/` |

# Depositing facilities

- Florida Keys Marine Sanctuary (primary)
- Gray's Reef Marine Sanctuary (primary)
- Mallows Bay-Potomac River Marine Sanctuary (primary)
- Monitor Marine Sanctuary (primary)
- Stellwagen Bank Marine Sanctuary (primary)
