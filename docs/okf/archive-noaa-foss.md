---
type: Data Archive
title: "NOAA Fisheries One Stop Shop (FOSS)"
description: "NOAA / National Marine Fisheries Service — data-portal holding long-term observatory records."
resource: "https://www.fisheries.noaa.gov/foss/"
tags: [data-portal, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Public commercial landings, permits, observer summaries; Oracle APEX REST endpoints. Returns JSON. retrieved_at=2026-05-06; agent=K-NMFS [via K-NMFS]

# Access

- Archive home: <https://www.fisheries.noaa.gov/foss/>
- API root (`rest`): <https://www.fisheries.noaa.gov/foss/f?p=215:200> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.fisheries.noaa.gov/foss/f?p=215:1>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-access | GET | application/json | <https://www.fisheries.noaa.gov/foss/f?p=215:200:::NO::P200_DATA_SET:PERMITS> | curl 'https://www.fisheries.noaa.gov/foss/f?p=215:200:::NO::P200_DATA_SET:PERMITS' |
| data-access | GET | application/json | <https://www.fisheries.noaa.gov/foss/f?p=215:200:::NO::P200_DATA_SET:LANDINGS> | curl 'https://www.fisheries.noaa.gov/foss/f?p=215:200:::NO::P200_DATA_SET:LANDINGS' |
