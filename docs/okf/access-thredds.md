---
type: Access Method
title: THREDDS / OPeNDAP
description: Walking THREDDS catalogs and subsetting over OPeNDAP or NCSS without downloading whole files.
tags: [thredds, opendap, dap, ncss, netcdf]
generated: { by: "claude-opus-5/lto-okf", at: 2026-08-14T03:58:00Z }
status: stable
---

A THREDDS Data Server (TDS) publishes a tree of **catalogs** whose
leaves are datasets, each reachable through one or more services:
HTTPServer (whole-file), OPeNDAP (lazy subsetting), NCSS (server-side
subset to NetCDF/CSV), WMS (tiles).

# Walk the catalog

Every catalog page has an XML twin — swap `.html` for `.xml`:

```
<base>/thredds/catalog.html          # human
<base>/thredds/catalog.xml           # machine
<base>/thredds/catalog/<path>/catalog.xml
```

```python
# siphon (Unidata) walks catalogs programmatically
from siphon.catalog import TDSCatalog
cat = TDSCatalog("<base>/thredds/catalog.xml")
print(list(cat.catalog_refs))        # sub-catalogs
ds = cat.datasets[0]
print(ds.access_urls)                # {'OPENDAP': ..., 'HTTPServer': ..., ...}
```

# OPeNDAP

The dataset URL (no extension) is an OPeNDAP endpoint; clients fetch
only the bytes a subset needs:

```python
import xarray as xr
ds = xr.open_dataset("<base>/thredds/dodsC/<path>/<file>.nc")
ds["temp"].sel(time="2024-06").mean()          # only this slice transfers
```

Inspect structure without a client: append `.dds` (structure), `.das`
(attributes), or `.ascii?var[0:1:10]` (values) to the `dodsC` URL.

# NetCDF Subset Service (NCSS)

Server-side subsetting to a clean file when you don't want a DAP client:

```bash
curl -o out.nc '<base>/thredds/ncss/<path>/<file>.nc?var=temp&north=37&south=31&west=-107&east=-106&time_start=2024-06-01T00%3A00%3A00Z&time_end=2024-06-30T23%3A59%3A59Z'
```

`?dataset.html` on any NCSS URL renders a form that builds the query
for you — build it there once, then script it.

# Whole files

The HTTPServer service is a plain download:
`<base>/thredds/fileServer/<path>/<file>.nc`.
