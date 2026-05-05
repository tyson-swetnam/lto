# F2 — Filter / search sidebar agent

## Scope
Left-side sidebar component: faceted filters + text search + result list.

## Outputs
- `web/src/filters.js`
- `web/src/state.js` (shared reactive store — tiny custom or `nanostores`)

## Facets
- **Facility type** — checkboxes driven by `schema/vocab/facility_types.csv`
- **Country / region** — US states grouped; then CA provinces; then LatAm
  countries; then Caribbean islands
- **Research area** — checkboxes from `schema/vocab/research_areas.csv`
  (collapsible parent / child tree)
- **Funder** — top-N funders from the DB (loaded dynamically); includes
  search-within-facet for long tail
- **Network** — checkboxes from `schema/vocab/networks.csv`

## Search
- Full-text across `canonical_name`, `acronym`, `parent_org`
- Debounced 200ms, runs a DuckDB `LIKE` query via F3

## URL state
All filter state encoded in URL query params (e.g.,
`?type=federal,university-marine-lab&area=ocean-acidification&q=PMEL`) so
views are shareable; parse on load, write on change with `history.replaceState`.

## Result list
- Virtualized list below filters
- Click → fly map to facility, open popup
- Shows name, type badge, country, lat/lng

## Integration points
- Publishes `filterState` to F3 which re-runs the SQL query
- Subscribes to F1 bbox so "limit to visible area" toggle works

## Deliverable
```
export function initFilters(container, state) { ... }
export function applyFilters(filterState) { ... }  // returns SQL WHERE fragment
```
