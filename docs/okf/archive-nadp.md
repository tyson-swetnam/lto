---
type: Data Archive
title: "National Atmospheric Deposition Program"
description: "NADP / Wisconsin State Laboratory of Hygiene — data-portal holding long-term observatory records."
resource: "https://nadp.slh.wisc.edu/"
tags: [data-portal, rest, cc0]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

NADP runs five subnetworks: NTN (precipitation chemistry, 1978-), AIRMoN (daily precip), MDN (mercury deposition), AMNet (atmospheric mercury), AMoN (ammonia). Per-site CSV downloads (weekly + annual). Hosted by Wisconsin State Laboratory of Hygiene. Public data, no DOI prefix issued. retrieved_at=2026-05-05; agent=J-A-AMERIFLUX-ARM [via J-A-AMERIFLUX-ARM]

# Access

- Archive home: <https://nadp.slh.wisc.edu/>
- API root (`rest`): <https://api.slh.wisc.edu/nadp/nadpApiMain.php> — see the [rest guide](./access-rest.md)
- API documentation: <https://nadp.slh.wisc.edu/data/>

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| data-download | POST | text/csv | <https://api.slh.wisc.edu/nadp/nadpApiMain.php> | curl -X POST -d 'pageId=ntnWeekly&siteId=NH02&startYr=2020&endYr=2020&PWD=<nadpVariables.nadpAPIPassword from page source>' https://api.slh.wisc.edu/nadp/nadpApiMain.php |
| metadata | GET | application/json | <https://api.slh.wisc.edu/nadp/nadpApiMain.php?net={NET}&siteId={SITE_ID}&pageId=siteInfo> | curl 'https://api.slh.wisc.edu/nadp/nadpApiMain.php?net=NTN&siteId=NH02&pageId=siteInfo' |

# Depositing facilities

- **OR10** NADP H.J. Andrews NTN site (primary)
- **NH02** NADP Hubbard Brook NTN site (primary)
- **KS31** NADP Konza Prairie NTN site (primary)
- **US-NR1** Niwot Ridge Forest Tower (secondary)

# Data products

3 addressable products catalogued. Top by citations:

| Product | Format | Coverage | Citations |
|---|---|---|---|
| [NADP NTN KS31 weekly precipitation chemistry, Konza Prairie](https://nadp.slh.wisc.edu/sites/ntn-KS31.html) | csv | 1982-09-01–present | n/a |
| [NADP NTN NH02 weekly precipitation chemistry, Hubbard Brook](https://nadp.slh.wisc.edu/sites/ntn-NH02.html) | csv | 1978-07-01–present | n/a |
| [NADP NTN OR10 weekly precipitation chemistry, H.J. Andrews EF](https://nadp.slh.wisc.edu/sites/ntn-OR10.html) | csv | 1980-04-01–present | n/a |
