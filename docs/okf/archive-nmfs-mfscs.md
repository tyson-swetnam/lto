---
type: Data Archive
title: "NMFS Marine Fisheries Stock Assessment / Stock SMART"
description: "NOAA / National Marine Fisheries Service / Office of Science and Technology — data-portal holding long-term observatory records."
resource: "https://www.st.nmfs.noaa.gov/stocksmart"
tags: [data-portal, rest, noaa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-14T03:20:10Z }
status: stable
---

Stock SMART (formerly MFSCS) — NMFS national stock-assessment summary database. Time series of biomass, F, recruitment by stock. retrieved_at=2026-05-06; agent=K-NMFS [via K-NMFS]

# Access

- Archive home: <https://www.st.nmfs.noaa.gov/stocksmart>
- API root (`rest`): <https://apps-st.fisheries.noaa.gov/stocksmart/> — see the [rest guide](./access-rest.md)
- API documentation: <https://www.st.nmfs.noaa.gov/stocksmart/help>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-access | GET | application/json | <https://apps-st.fisheries.noaa.gov/stocksmart/api/assessments?stock={stock_id}> | curl 'https://apps-st.fisheries.noaa.gov/stocksmart/api/assessments?stock=walleye-pollock-eastern-bering-sea' |
