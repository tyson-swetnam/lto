---
type: Data Archive
title: "NASA Earthdata Search / Common Metadata Repository"
description: "NASA Earth Science Data Systems — federation holding long-term observatory records."
resource: "https://search.earthdata.nasa.gov/"
tags: [federation, rest, nasa-public]
generated: { by: "claude-opus-5/lto-okf-generator", at: 2026-08-15T03:43:53Z }
status: stable
---

Cross-DAAC search & catalog (CMR). Federates NSIDC, ASF, GES DISC, LP DAAC, OB.DAAC, ORNL DAAC, PO.DAAC, SEDAC, etc. UMM-G/UMM-C JSON. Earthdata Login for downloads; Harmony service for subset/transform. retrieved_at=2026-05-06; agent=J-A-NSIDC-CRY [via J-A-NSIDC-CRY]

# Access

- Archive home: <https://search.earthdata.nasa.gov/>
- API root (`rest`): <https://cmr.earthdata.nasa.gov/search/> — see the [rest guide](./access-rest.md)
- API documentation: <https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html>
- DOIs minted here start with `10.5067`

# Documented calls

| Purpose | Method | Format | URL | Example |
|---|---|---|---|---|
| auth | GET | text/html | <https://urs.earthdata.nasa.gov/oauth/authorize> | OAuth2 authorize endpoint; for service-to-service use NASA Earthdata Login app credentials. |
| search | GET | application/json | <https://cmr.earthdata.nasa.gov/search/collections.json> | curl 'https://cmr.earthdata.nasa.gov/search/collections.json?keyword=sea+ice&data_center=NSIDC_CPRD&page_size=50' |
| search | GET | application/json | <https://cmr.earthdata.nasa.gov/search/granules.json> | curl 'https://cmr.earthdata.nasa.gov/search/granules.json?short_name=ATL06&version=007&temporal=2024-01-01T00:00:00Z,2024-01-31T23:59:59Z&bounding_box=-180,60,180,90&page_size=100' |

# Cloud buckets

See the [cloud-bucket guide](./access-buckets.md) for anonymous / requester-pays recipes.

| Provider | Bucket | Region | Access | Sample prefix |
|---|---|---|---|---|
| s3 | [asf-cumulus-prod-s1-slc](https://asf.alaska.edu/datasets/daac/sentinel-1/) | us-west-2 | registered-users | `S1A_IW_SLC__1SDV_20240101/` |
| s3 | [ornldaac-cumulus-prod-public](https://daac.ornl.gov/cgi-bin/dsviewer.pl) | us-west-2 | public-anon-egress | `above/ABoVE_AirSWOT/` |
| s3 | [podaac-ops-cumulus-public](https://podaac.jpl.nasa.gov/CloudFAQ) | us-west-2 | public-anon-egress | `L2/SWOT_KARIN/` |
