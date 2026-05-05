# F1 — Leaflet map agent

## Scope
Build the interactive Leaflet map component for the web UI.

## Outputs
- `web/src/map.js`
- `web/public/shoreline.geojson` — simplified NOAA shoreline overlay (optional)

## Requirements
- Default view: continental North America at zoom ~3 (center ~32°N, -85°W).
- Base layers (open / no API key):
  - OpenStreetMap standard (default)
  - CARTO Positron (light, for readability on mobile)
  - Esri Ocean Basemap (optional, via public ArcGIS URL — no key)
  - Layer-control widget to switch.
- Marker clustering: `leaflet.markercluster` for performance with >500 points.
- Marker styling: colored by `facility_type` (e.g., federal=blue,
  university=green, state=orange, network=purple, foundation=gold, intl=teal).
- Popup content:
  - Canonical name (link to URL)
  - Facility type badge, acronym, country
  - HQ address
  - Top 3 research areas
  - Top 3 funders (from funding_links aggregated)
  - Link to raw record (JSON) for debugging
- Click → open popup; hover → highlight in sidebar list (F2 integration).
- Respect filter state published by F2 (subscribe via shared state module).
- Emit current map bbox back to F2 so filters can be scoped to viewport.

## Data input
Receives an array of features from F3 (`db.js`) of shape:
```
{ id, name, acronym, type, country, lat, lng, url, funders, areas, networks }
```

## Deliverable
```
export function initMap(container, state) { ... }
export function renderFacilities(features) { ... }
```

## Non-goals
- Drawing vector overlays beyond shoreline.
- Routing, turn-by-turn, or any navigation features.
