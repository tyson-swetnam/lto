// overlay-facets.js — which map overlays a filter selection should hide.
//
// Overlays are static context layers: they never pass through query()'s
// WHERE clause. That produced a real bug — with the Arid sphere selected,
// facility POINTS filtered correctly but marine-sanctuary polygons and
// the 61 default-on NEON site polygons stayed painted, reading as
// unfiltered results. Same for the network facet: picking NEON left every
// estuarine-reserve polygon on screen.
//
// The decision is pure (ids + filter Sets in, boolean out) and lives here
// rather than in overlays.js so it can be exercised without MapLibre.
// overlays.js owns the effects: show/hide, the muted sidebar row, and the
// user-override bookkeeping.

// The sphere(s) an overlay's content belongs to. Slugs are the
// `spheres.slug` values (schema/vocab/spheres.csv) — 'ocean-estuarine',
// 'freshwater', not the display labels.
export const SPHERE_TAGS = {
  'nerr-reserves':           ['ocean-estuarine'],
  'nep-programs':            ['ocean-estuarine'],
  'marine-sanctuaries':      ['ocean-estuarine'],
  'marine-monuments':        ['ocean-estuarine'],
  'nps-coastal':             ['ocean-estuarine'],
  'coastal-fws-units':       ['ocean-estuarine'],
  'coastal-nps-units':       ['ocean-estuarine'],
  'coastal-usfs-special':    ['ocean-estuarine'],
  'coastal-wilderness':      ['ocean-estuarine'],
  'coastal-state-protected': ['ocean-estuarine'],
  'coastal-ngo-private':     ['ocean-estuarine'],
  'ramsar-us':               ['ocean-estuarine', 'freshwater'],
};

// Network slugs (schema/vocab/networks.csv) whose membership roll is what
// the layer draws. Only layers with clean 1:1 network provenance appear —
// the generic protected-area layers (wilderness, state/NGO preserves) are
// nobody's membership roll and stay sphere-governed.
export const NETWORK_TAGS = {
  'nerr-reserves':      ['nerrs'],
  'nep-programs':       ['nep'],
  'marine-sanctuaries': ['nms'],
  'marine-monuments':   ['marine-monument'],
  'nps-coastal':        ['nps-coastal'],
  'coastal-nps-units':  ['nps-coastal'],
  'neon-sites':         ['neon'],
};

// Overlays whose features mirror rows of `facilities` — every NEON site
// polygon is also a filterable facility point. Any narrowing facet makes
// them stale, so they hide wholesale and the correctly-filtered points
// carry the answer.
export const RESULTS_DUPLICATING = new Set(['neon-sites']);

// Facets that narrow the facility result set. `countries` and `areas` are
// deliberately absent: an overlay is not a country or a research-area
// claim, and hiding on those would strip context the user still needs.
const NARROWING = ['spheres', 'ecosystems', 'lifeZones', 'networks', 'types'];

/** True when any facet that narrows the facility result set is active. */
export function facetsNarrowing(filters) {
  return NARROWING.some((k) => filters?.[k]?.size > 0);
}

/**
 * Should overlay `id` be hidden under this filter selection?
 * Pure — the caller applies overrides and effects.
 */
export function overlayHiddenByFilters(id, filters) {
  if (!facetsNarrowing(filters)) return false;
  if (RESULTS_DUPLICATING.has(id)) return true;

  const spheres = filters?.spheres;
  const tags = SPHERE_TAGS[id];
  if (tags && spheres?.size && !tags.some((t) => spheres.has(t))) return true;

  const networks = filters?.networks;
  const nets = NETWORK_TAGS[id];
  if (nets && networks?.size && !nets.some((n) => networks.has(n))) return true;

  return false;
}
