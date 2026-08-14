---
type: Access Method
title: ERDDAP — griddap & tabledap
description: URL grammar and download recipes for the ERDDAP servers in the LTO catalogue.
tags: [erddap, griddap, tabledap, netcdf, csv]
generated: { by: "claude-opus-5/lto-okf", at: 2026-08-14T03:58:00Z }
status: stable
---

ERDDAP serves gridded data (**griddap**) and tabular data (**tabledap**)
through a URL grammar that doubles as a query language: the file
extension picks the format, the query string subsets the data. Twelve
archives in this catalogue are ERDDAP servers ([index](./index.md)).

# Discover datasets

Every ERDDAP lists its datasets as data:

```
<base>/erddap/tabledap/allDatasets.csv?datasetID,title,dataStructure
<base>/erddap/search/index.csv?searchFor=temperature
```

# tabledap (in-situ / tabular)

```
<base>/erddap/tabledap/<datasetID>.<ext>?<vars>&<constraints>
```

- `<ext>`: `csv`, `csvp` (units in header), `nc`, `json`, `parquet` (newer servers), `htmlTable` (preview)
- `<vars>`: comma-separated column list; omit for all
- constraints: `time>=2020-01-01`, `latitude>=31&latitude<=37`, `station_id="JRN"`

Example — one year of a station's record as CSV:

```bash
curl -g '<base>/erddap/tabledap/<datasetID>.csv?time,temperature&time>=2024-01-01&time<2025-01-01'
```

(`curl -g` disables glob parsing so `[]`/`{}` in queries survive.)

# griddap (gridded / model / satellite)

```
<base>/erddap/griddap/<datasetID>.<ext>?<var>[(t1):stride:(t2)][(lat1):(lat2)][(lon1):(lon2)]
```

Example — a NetCDF subset:

```bash
curl -g -o subset.nc \
  '<base>/erddap/griddap/<datasetID>.nc?temp[(2024-06-01):1:(2024-06-30)][(31.5):(33.0)][(-107.0):(-106.0)]'
```

# Python

```python
# erddapy builds the URLs for you
from erddapy import ERDDAP
e = ERDDAP(server="<base>/erddap", protocol="tabledap")
e.dataset_id = "<datasetID>"
e.constraints = {"time>=": "2024-01-01"}
df = e.to_pandas()
```

Metadata for any dataset: `<base>/erddap/info/<datasetID>/index.csv`.
ERDDAP also exposes each dataset over [OPeNDAP](./access-thredds.md#opendap),
so `xarray.open_dataset('<base>/erddap/griddap/<datasetID>')` works directly.
