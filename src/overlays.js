// overlays.js — Map overlay layer manager.
//
// Loads public/overlays/manifest.json on startup and exposes:
//   - initOverlays(map, sidebarContainer, onChange)
//       builds the sidebar section, wires fetch-on-demand toggles, and
//       auto-enables the default-on overlays (everything except EPA /
//       NEON context layers).
//   - activeOverlays() → Array<{id, label, color}> for the legend control
//
// Overlays are fetched lazily the first time they are toggled on. Each
// overlay registers a single GeoJSON source and two MapLibre layers (fill +
// outline). Polygons sit beneath the facility cluster/point layers so the
// points stay clearly visible.

import maplibregl from 'maplibre-gl';
import { DATA_BASE } from './config.js';
import { isMapAvailable } from './map.js';

const MANIFEST_URL = `${DATA_BASE}overlays/manifest.json`;

// Overlays that should NOT render on first paint. Context layers for the
// US are less useful by default than the coastal + marine boundaries.
// New coastal-terrestrial layers default to OFF too, even though they're
// likely the most-requested layer for terrestrial-coast research, because:
// (a) coastal-fws-units alone is ~880 KB and four-on layers ≈ 2 MB which
// would slow first-paint, and
// (b) heavy overlap with the existing nps-coastal/nerr-reserves layers
// would clutter the default view. Users opt in from the sidebar.
const DEFAULT_OFF = new Set([
  'epa-regions', 'neon-domains',
  'coastal-fws-units', 'coastal-nps-units',
  'coastal-usfs-special', 'coastal-wilderness',
  'coastal-state-protected', 'coastal-ngo-private', 'ramsar-us',
  // 'neon-sites' is now small (61 polygons, 99 KB) and the user
  // explicitly asked for it visible by default. Default-on.
]);

// Layer ids that must stay on top of every overlay so the facility dots
// remain visible. Kept in sync with map.js. (Clustering was removed in
// favour of plain per-feature circles; see the explanatory comment there.)
const FACILITY_LAYERS = [
  'facility-points',
  'facility-points-hover',
];

let _map = null;
let _manifest = {};
let _active = new Set();
let _onChange = () => {};

// Track which overlays have had their data fetched so we don't refetch.
const _loaded = new Set();

export async function initOverlays(map, container, onChange) {
  _map = map;
  _onChange = onChange || (() => {});

  // No WebGL: there's no real map to attach overlay layers to. Hide the
  // overlay panel entirely rather than showing checkboxes that toggle
  // nothing. The Browse/Network/People/SQL/Stats tabs don't need overlays.
  if (!isMapAvailable()) {
    if (container) container.hidden = true;
    return;
  }

  try {
    const res = await fetch(MANIFEST_URL);
    _manifest = await res.json();
  } catch (e) {
    console.warn('overlays: manifest failed to load', e);
    return;
  }

  // Group overlays by category so the sidebar can render them as sections.
  const byCat = {};
  for (const [id, meta] of Object.entries(_manifest)) {
    (byCat[meta.category || 'other'] ??= []).push({ id, ...meta });
  }

  const CATEGORY_LABELS = {
    coastal: 'Coastal boundaries',
    'coastal-terrestrial': 'Coastal terrestrial protected areas',
    marine:  'Marine protected areas',
    context: 'Context layers',
  };

  const sec = document.createElement('div');
  sec.className = 'facet-section overlay-section';
  sec.innerHTML = `
    <div class="facet-header">
      <h2>Map overlays</h2>
      <span class="facet-toggle">&#9650;</span>
    </div>
    <div class="facet-body overlay-body"></div>
  `;
  sec.querySelector('.facet-header').addEventListener('click', () => {
    sec.classList.toggle('collapsed');
    sec.querySelector('.facet-toggle').innerHTML =
      sec.classList.contains('collapsed') ? '&#9660;' : '&#9650;';
  });

  const body = sec.querySelector('.overlay-body');
  const orderedCats = ['coastal', 'coastal-terrestrial', 'marine', 'context'];
  for (const cat of orderedCats) {
    if (!byCat[cat]) continue;
    const group = document.createElement('div');
    group.className = 'overlay-group';
    const label = CATEGORY_LABELS[cat] || cat;
    group.innerHTML = `<div class="overlay-group-label">${label}</div>`;
    for (const o of byCat[cat]) {
      const defaultOn = !DEFAULT_OFF.has(o.id);
      const row = document.createElement('label');
      row.className = 'overlay-row';
      row.innerHTML = `
        <input type="checkbox" data-overlay="${o.id}"${defaultOn ? ' checked' : ''} />
        <span class="overlay-swatch" style="background:${o.color}"></span>
        <span class="overlay-label">${o.label}</span>
      `;
      group.appendChild(row);
    }
    body.appendChild(group);
  }

  container.appendChild(sec);

  body.addEventListener('change', async (ev) => {
    const cb = ev.target;
    if (!(cb instanceof HTMLInputElement)) return;
    const id = cb.dataset.overlay;
    if (!id) return;
    if (cb.checked) {
      await showOverlay(id);
    } else {
      hideOverlay(id);
    }
    _onChange();
  });

  // Kick off the default-on overlays. showOverlay waits internally for the
  // map style + facility layers to be ready, so these are safe to fire now.
  const bootTargets = Object.keys(_manifest).filter((id) => !DEFAULT_OFF.has(id));
  Promise.allSettled(bootTargets.map((id) => showOverlay(id)))
    .then(() => _onChange())
    .catch((e) => console.warn('overlays: default-on boot failed', e));
}

function whenStyleReady() {
  return new Promise((resolve) => {
    if (_map.isStyleLoaded()) return resolve();
    _map.once('load', resolve);
  });
}

// Wait until every facility/cluster layer actually exists. isStyleLoaded()
// and the 'load' event can fire before map.js's user 'load' handler runs,
// so poll styledata and also fall back to a timed check.
function whenFacilityLayersReady() {
  const ready = () => FACILITY_LAYERS.every((id) => _map.getLayer(id));
  if (ready()) return Promise.resolve();
  return new Promise((resolve) => {
    let poll;
    const done = () => {
      if (!ready()) return;
      _map.off('styledata', done);
      if (poll) clearInterval(poll);
      resolve();
    };
    _map.on('styledata', done);
    poll = setInterval(done, 100);
  });
}

// Force the facility layers to sit above any overlays. MapLibre's moveLayer
// (with no beforeId) pushes a layer to the top of the stack.
function raiseFacilityLayers() {
  for (const id of FACILITY_LAYERS) {
    if (_map.getLayer(id)) _map.moveLayer(id);
  }
}

// Geometry kind per overlay so showOverlay / hideOverlay know which
// layer ids to flip. Populated by ensureLoaded after fetching the
// GeoJSON header. 'polygon' adds {fill, outline}; 'point' adds {circle}.
const _geomKind = new Map();

async function ensureLoaded(id) {
  if (_loaded.has(id)) return;
  await whenStyleReady();
  await whenFacilityLayersReady();
  const meta = _manifest[id];
  const url = `${DATA_BASE}overlays/${id}.geojson`;

  // Pre-fetch a small slice of the file to detect Point vs Polygon
  // features. We need this to choose layer types — a fill layer over
  // Point geometry renders nothing (which is why NEON / Ramsar
  // overlays appeared invisible). The fetched geojson is then handed
  // to MapLibre as the source data so we don't double-fetch.
  let geojson = null;
  let kind = 'polygon';
  try {
    const r = await fetch(url);
    if (r.ok) {
      geojson = await r.json();
      const firstGeom = (geojson.features || []).find((f) => f && f.geometry)?.geometry;
      if (firstGeom && (firstGeom.type === 'Point' || firstGeom.type === 'MultiPoint')) {
        kind = 'point';
      }
    }
  } catch (e) {
    console.warn(`[overlays] could not pre-fetch ${url}, falling back to polygon layers:`, e);
  }
  _geomKind.set(id, kind);

  _map.addSource(`ov-${id}`, geojson
    ? { type: 'geojson', data: geojson }
    : { type: 'geojson', data: url });

  // Insert beneath the first facility layer so the user's facility
  // points stay on top of polygon overlays.
  const beforeLayer = FACILITY_LAYERS.find((lid) => _map.getLayer(lid));

  if (kind === 'polygon') {
    _map.addLayer({
      id: `ov-${id}-fill`,
      type: 'fill',
      source: `ov-${id}`,
      layout: { visibility: 'none' },
      paint: { 'fill-color': meta.color, 'fill-opacity': 0.16 },
    }, beforeLayer);

    _map.addLayer({
      id: `ov-${id}-outline`,
      type: 'line',
      source: `ov-${id}`,
      layout: { visibility: 'none' },
      paint: {
        'line-color': meta.color,
        'line-width': 1.25,
        'line-opacity': 0.75,
      },
    }, beforeLayer);

    _map.on('click', `ov-${id}-fill`, (e) => {
      const f = e.features?.[0];
      if (!f) return;
      new maplibregl.Popup({ maxWidth: '280px' })
        .setLngLat([e.lngLat.lng, e.lngLat.lat])
        .setHTML(overlayPopup(id, f.properties || {}))
        .addTo(_map);
    });
    _map.on('mouseenter', `ov-${id}-fill`, () => { _map.getCanvas().style.cursor = 'pointer'; });
    _map.on('mouseleave', `ov-${id}-fill`, () => { _map.getCanvas().style.cursor = ''; });
  } else {
    // Point layer — circle marker with a coloured fill + white halo so
    // the points are visible regardless of basemap.
    _map.addLayer({
      id: `ov-${id}-circle`,
      type: 'circle',
      source: `ov-${id}`,
      layout: { visibility: 'none' },
      paint: {
        'circle-radius': [
          'interpolate', ['linear'], ['zoom'],
          3, 3,    // 3 px at zoom 3
          7, 5,
          12, 7,
        ],
        'circle-color': meta.color,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1.5,
        'circle-opacity': 0.92,
      },
    });   // No `beforeLayer` — points should sit on top of polygon overlays.

    _map.on('click', `ov-${id}-circle`, (e) => {
      const f = e.features?.[0];
      if (!f) return;
      new maplibregl.Popup({ maxWidth: '280px' })
        .setLngLat([e.lngLat.lng, e.lngLat.lat])
        .setHTML(overlayPopup(id, f.properties || {}))
        .addTo(_map);
    });
    _map.on('mouseenter', `ov-${id}-circle`, () => { _map.getCanvas().style.cursor = 'pointer'; });
    _map.on('mouseleave', `ov-${id}-circle`, () => { _map.getCanvas().style.cursor = ''; });
  }

  // Belt-and-braces: force every facility/cluster layer back to the top
  // in case an insertion race left one beneath an overlay.
  raiseFacilityLayers();
  _loaded.add(id);
}

function _layerIds(id) {
  const k = _geomKind.get(id) || 'polygon';
  return k === 'point'
    ? [`ov-${id}-circle`]
    : [`ov-${id}-fill`, `ov-${id}-outline`];
}

async function showOverlay(id) {
  await ensureLoaded(id);
  for (const lid of _layerIds(id)) {
    if (_map.getLayer(lid)) {
      _map.setLayoutProperty(lid, 'visibility', 'visible');
    }
  }
  raiseFacilityLayers();
  _active.add(id);
}

function hideOverlay(id) {
  if (!_loaded.has(id)) { _active.delete(id); return; }
  for (const lid of _layerIds(id)) {
    if (_map.getLayer(lid)) {
      _map.setLayoutProperty(lid, 'visibility', 'none');
    }
  }
  raiseFacilityLayers();
  _active.delete(id);
}

export function activeOverlays() {
  return Array.from(_active).map((id) => ({
    id,
    label: _manifest[id]?.label || id,
    color: _manifest[id]?.color || '#64748b',
  }));
}

function overlayPopup(id, p) {
  const meta = _manifest[id] || {};
  const rows = [];

  // Title line: use the full name, turn it into a link if we have a URL.
  if (p.name) {
    const inner = p.url
      ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a>`
      : esc(p.name);
    const acr = p.acronym ? ` <span class="popup-acr">(${esc(p.acronym)})</span>` : '';
    rows.push(`<div class="popup-name">${inner}${acr}</div>`);
  }

  // Category badge (color + network label) — unchanged.
  rows.push(`<div class="popup-meta"><span class="type-badge" style="background:${meta.color}">${esc(meta.label || id)}</span></div>`);

  // Designation / proclamation year (support both field names so we don't
  // break the legacy NEP `year` string).
  const designated = p.year_designated ?? p.year;
  if (designated) rows.push(`<div class="popup-row"><em>Designated:</em> ${esc(designated)}</div>`);

  if (p.state)             rows.push(`<div class="popup-row"><em>State:</em> ${esc(p.state)}</div>`);
  if (p.states)            rows.push(`<div class="popup-row"><em>States:</em> ${esc(p.states)}</div>`);
  if (p.hq)                rows.push(`<div class="popup-row"><em>HQ:</em> ${esc(p.hq)}</div>`);
  if (p.epa_region)        rows.push(`<div class="popup-row"><em>EPA Region:</em> ${esc(p.epa_region)}</div>`);
  if (p.area_sqmi)         rows.push(`<div class="popup-row"><em>Area:</em> ${esc(Number(p.area_sqmi).toLocaleString())} sq mi</div>`);
  if (p.manager)           rows.push(`<div class="popup-row"><em>Manager:</em> ${esc(p.manager)}</div>`);
  if (p.management)        rows.push(`<div class="popup-row"><em>Management:</em> ${esc(p.management)}</div>`);
  if (p.protection_level)  rows.push(`<div class="popup-row"><em>Protection:</em> ${esc(p.protection_level)}</div>`);
  if (p.domain_id)         rows.push(`<div class="popup-row"><em>NEON domain:</em> D${String(p.domain_id).padStart(2, '0')}</div>`);

  if (p.description) {
    rows.push(`<div class="popup-row popup-desc">${esc(p.description)}</div>`);
  }

  if (p.url) {
    rows.push(`<a class="popup-source" href="${esc(p.url)}" target="_blank" rel="noopener">Visit website</a>`);
  }

  return `<div class="popup">${rows.join('')}</div>`;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
