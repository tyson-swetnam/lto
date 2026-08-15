---
type: Access Method
title: Cloud buckets (S3 / GCS / Azure)
description: Anonymous, registered, and requester-pays access to the public-cloud buckets in the catalogue.
tags: [s3, gcs, azure, cloud, requester-pays]
generated: { by: "claude-opus-5/lto-okf", at: 2026-08-14T03:58:00Z }
status: stable
---

Twenty-nine cloud buckets are attached to archives in this catalogue
(the registry holds 66 rows; the rest are general-purpose public
datasets — Copernicus DEM, ERA5, MODIS, NAIP — not yet linked to an
archive and so not listed on any page). Each archive's concept doc
lists its buckets with provider, region, an access mode, and a sample
prefix; the 🔒 badge on the [Data tab](../index.md) marks the modes
that need credentials or payment.

# Anonymous S3 (`public-anon-egress`, `public-read`)

```bash
# AWS CLI without credentials:
aws s3 ls --no-sign-request s3://<bucket>/<prefix>/
aws s3 cp  --no-sign-request s3://<bucket>/<key> .
# Plain HTTPS works too:
curl -O https://<bucket>.s3.<region>.amazonaws.com/<key>
```

```python
import s3fs
fs = s3fs.S3FileSystem(anon=True)
fs.ls("<bucket>/<prefix>")
# Zarr/NetCDF stores open lazily:
import xarray as xr
ds = xr.open_zarr(fs.get_mapper("<bucket>/<prefix>/store.zarr"))
```

# Requester-pays (`requester-pays` 🔒)

You need AWS credentials and you pay egress:

```bash
aws s3 cp s3://<bucket>/<key> . --request-payer requester
```

```python
fs = s3fs.S3FileSystem(requester_pays=True)   # uses your AWS profile
```

# Registered users (`registered-users` 🔒)

The bucket's `documentation_url` (linked from its badge) describes the
sign-up; typically you receive scoped keys or presigned URLs — NEON and
some DOE products work this way.

**NASA Earthdata Cloud buckets belong here regardless of their labels**
(verified 2026-08-14): the `*-cumulus-prod-public` and `-protected`
buckets reject anonymous requests outright (`--no-sign-request` gets
403 AccessDenied). They need temporary S3 credentials from the DAAC's
`/s3credentials` endpoint (Earthdata Login), and only work in-region
(us-west-2) — e.g.
`https://data.nsidc.earthdatacloud.nasa.gov/s3credentials`. Out of
region, use the HTTPS `data.*.earthdatacloud.nasa.gov` URLs instead.
Note the ORNL DAAC bucket is `ornl-cumulus-prod-public` (not
`ornldaac-…`).

# GCS and Azure

```bash
gsutil ls gs://<bucket>/<prefix>/            # add -u <project> if requester-pays
azcopy copy 'https://<account>.blob.core.windows.net/<container>/<prefix>/*' . --recursive
```

Prefer listing with a prefix over crawling a whole bucket — several of
these buckets hold petabytes, and the sample prefix in the concept doc
is the curated entry point.
