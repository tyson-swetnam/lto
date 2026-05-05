import maplibregl from 'maplibre-gl';
import { fetchCSV } from './csv.js';
import { DATA_BASE as BASE } from './config.js';

export const TYPE_COLORS = {
  federal: '#2563eb',
  state: '#f97316',
  'local-gov': '#eab308',
  'university-marine-lab': '#16a34a',
  'university-institute': '#15803d',
  nonprofit: '#9333ea',
  foundation: '#d4a017',
  network: '#7c3aed',
  'international-federal': '#0d9488',
  'international-university': '#14b8a6',
  'international-nonprofit': '#5eead4',
  industry: '#475569',
  vessel: '#0ea5e9',
  observatory: '#0369a1',
  virtual: '#94a3b8',
  // Coastal-terrestrial protected-area facility types. Colours match
  // the corresponding polygon overlays in public/overlays/manifest.json
  // so a facility's centroid dot has visual continuity with its
  // boundary polygon.
  'protected-area-federal': '#a16207',  // amber (matches coastal-fws-units)
  'protected-area-state':   '#0e7490',  // teal  (matches coastal-state-protected)
  'protected-area-private': '#a21caf',  // magenta (matches coastal-ngo-private)
};

function typeColorExpr() {
  const expr = ['match', ['get', 'type']];
  for (const [k, v] of Object.entries(TYPE_COLORS)) expr.push(k, v);
  expr.push('#64748b');
  return expr;
}

let map;
let _stubMode = false;
let _currentFeatures = [];

// Plug-in API used by overlays.js to publish what's currently rendered.
let _legendOverlayProvider = () => [];
export function registerLegendOverlayProvider(fn) {
  _legendOverlayProvider = fn || (() => []);
}
export function refreshLegend() {
  document.querySelector('.legend-control')?.dispatchEvent(new CustomEvent('legend:refresh'));
}

// True when the host has no usable WebGL context (e.g. a headless Linux box
// with llvmpipe software rendering, where MapLibre's `_setupPainter` throws).
// overlays.js and main.js use this to skip operations that would NPE on the
// stub map.
export function isMapAvailable() {
  return !_stubMode;
}

// Probe WebGL synchronously. MapLibre's constructor throws inside
// `_setupPainter` if the browser can't create a WebGL context, which kills
// the whole main.js module and breaks every other tab. Detect it ourselves
// first so we can render a graceful fallback and keep Browse / People / SQL /
// Stats / Network / Docs working.
function detectWebGL() {
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2')
      || c.getContext('webgl')
      || c.getContext('experimental-webgl');
    return !!gl;
  } catch (_) {
    return false;
  }
}

function renderNoWebGLFallback(container) {
  container.classList.add('map-no-webgl');
  container.innerHTML = `
    <div class="map-no-webgl-inner">
      <h2>Interactive map unavailable</h2>
      <p>The map view needs WebGL, but your browser couldn't create a WebGL
        context. This usually means hardware acceleration is disabled or the
        device has no GPU (e.g. a headless Linux session falling back to
        software rendering).</p>
      <p><strong>What works without WebGL:</strong> the
        <a href="#/browse">Browse</a>, <a href="#/network">Network</a>,
        <a href="#/people">People</a>, <a href="#/sql">SQL</a>,
        <a href="#/stats">Stats</a>, and <a href="#/docs">Docs</a> tabs above.</p>
      <p><strong>To get the map back:</strong> enable hardware acceleration in
        your browser settings, or in Chromium-based browsers visit
        <code>chrome://flags</code> and enable
        <em>"Override software rendering list"</em>.</p>
    </div>
  `;
}

// Lightweight stand-in for a maplibregl.Map. Implements only the surface that
// main.js, overlays.js, and this module poke at — every method is a no-op
// (or returns a sensible empty value) so callers don't have to special-case
// the missing map.
function makeStubMap() {
  const noop = () => {};
  const stub = {
    on: noop, off: noop, once: noop, fire: noop,
    addControl: noop, removeControl: noop,
    addSource: noop, removeSource: noop,
    addLayer: noop, removeLayer: noop, moveLayer: noop,
    setFilter: noop, setLayoutProperty: noop, setPaintProperty: noop,
    setData: noop,
    getSource: () => null,
    getLayer: () => null,
    getCanvas: () => ({ style: {} }),
    getBounds: () => ({ contains: () => true }),
    isStyleLoaded: () => false,
    resize: noop,
    flyTo: noop, fitBounds: noop, panTo: noop, jumpTo: noop,
    queryRenderedFeatures: () => [],
  };
  return stub;
}

const COASTLINE_URL =
  'https://raw.githubusercontent.com/martynafford/natural-earth-geojson/master/50m/physical/ne_50m_coastline.json';

export function initMap(container) {
  if (!detectWebGL()) {
    _stubMode = true;
    renderNoWebGLFallback(container);
    map = makeStubMap();
    return map;
  }

  map = new maplibregl.Map({
    container,
    style: 'https://tiles.openfreemap.org/styles/positron',
    center: [-85, 32],
    zoom: 3,
    attributionControl: false,
  });

  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');

  map.addControl(makeFitControl(), 'top-right');
  map.addControl(makeLegendControl(), 'bottom-left');

  map.on('load', () => {
    // Coastline reference line — subtle teal
    map.addSource('coastline', { type: 'geojson', data: COASTLINE_URL });
    map.addLayer({
      id: 'coastline-line',
      type: 'line',
      source: 'coastline',
      paint: {
        'line-color': '#0d6e6e',
        'line-width': 0.6,
        'line-opacity': 0.45,
      },
    });

    // Facilities source — NON-CLUSTERED.
    //
    // We used to run this source with cluster:true + clusterRadius:50, but
    // MapLibre-GL 4.7.1's GeoJSON source gets into a wedged state when the
    // source is added with empty features and then later setData()-ed with
    // real features while other sources (the default-on overlays) are still
    // loading. The cluster index never rebuilds, and 200 points render as
    // at most a single stray unclustered dot. At this dataset size (≈200
    // points) clustering isn't necessary for performance, and the user-
    // facing UX (viewport-driven browse list) is clearer without it.
    map.addSource('facilities', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    });

    map.addLayer({
      id: 'facility-points',
      type: 'circle',
      source: 'facilities',
      paint: {
        'circle-radius': 6,
        'circle-color': typeColorExpr(),
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#fff',
      },
    });

    map.addLayer({
      id: 'facility-points-hover',
      type: 'circle',
      source: 'facilities',
      filter: ['==', ['get', 'id'], ''],
      paint: {
        'circle-radius': 9,
        'circle-color': 'transparent',
        'circle-stroke-width': 2.5,
        'circle-stroke-color': '#0d6e6e',
      },
    });

    map.on('click', 'facility-points', (e) => {
      const feat = e.features[0];
      const coords = feat.geometry.coordinates.slice();
      const p = feat.properties;
      // MapLibre stringifies array-valued feature properties when a feature
      // passes through its tiler. Re-parse list fields back into real arrays.
      for (const key of ['areas', 'networks', 'funders', 'regions', 'region_kinds']) {
        if (typeof p[key] === 'string') {
          try { p[key] = JSON.parse(p[key]); } catch (_) { p[key] = []; }
        }
      }
      new maplibregl.Popup({ maxWidth: '320px' })
        .setLngLat(coords)
        .setHTML(popupHtml(p))
        .addTo(map);
    });

    map.on('mousemove', 'facility-points', (e) => {
      map.getCanvas().style.cursor = 'pointer';
      const id = e.features[0].properties.id || '';
      map.setFilter('facility-points-hover', ['==', ['get', 'id'], id]);
    });
    map.on('mouseleave', 'facility-points', () => {
      map.getCanvas().style.cursor = '';
      map.setFilter('facility-points-hover', ['==', ['get', 'id'], '']);
    });

    // Fire a custom 'facilities:sourceready' event so the rest of the app
    // can know the source exists and start painting/list-syncing.
    map.fire('facilities:sourceready');
  });

  return map;
}

/**
 * Compute which of the currently-rendered features fall inside the map's
 * current viewport bounds. Used by main.js to drive the bottom browse list
 * and the facility-count status — "only show what's actually visible".
 */
export function featuresInView() {
  if (!map) return _currentFeatures;
  const b = map.getBounds();
  return _currentFeatures.filter((f) => {
    const c = f.geometry?.coordinates;
    if (!Array.isArray(c)) return false;
    const [lng, lat] = c;
    return b.contains([lng, lat]);
  });
}

/** Subscribe to map move events so the UI can re-sync viewport-visible features. */
export function onViewportChange(handler) {
  const fire = () => handler(featuresInView());
  if (!map) return () => {};
  map.on('moveend', fire);
  map.on('zoomend', fire);
  return () => {
    map.off('moveend', fire);
    map.off('zoomend', fire);
  };
}

export function renderFacilities(features) {
  _currentFeatures = features;
  // No WebGL → no map → no source to paint. Stash the features so the
  // browse / stats / people tabs still render and bail before we attach
  // listeners that the stub map would never fire.
  if (_stubMode) return;
  const payload = { type: 'FeatureCollection', features };

  // The old gate was `map.isStyleLoaded()`, but that flips back to false every
  // time a new source gets added to the style — e.g. when the default-on
  // overlays kick off their lazy GeoJSON fetches in initOverlays(). In that
  // window the polled setData call never fires and the facilities source
  // stays empty even though its layers already exist. The only precondition
  // that actually matters here is "the `facilities` source has been created",
  // which happens synchronously inside `map.on('load', ...)`. Wait for that
  // instead.
  const trySet = () => {
    const src = map?.getSource('facilities');
    if (src) {
      src.setData(payload);
      return true;
    }
    return false;
  };

  if (trySet()) return;
  if (!map) {
    // Extremely early call (initMap hasn't returned yet): fall back to a
    // short poll until the Map instance is created.
    const iv = setInterval(() => {
      if (map) { clearInterval(iv); waitForSource(); }
    }, 50);
    return;
  }
  waitForSource();

  function waitForSource() {
    if (trySet()) return;
    const onStyleData = () => {
      if (trySet()) map.off('styledata', onStyleData);
    };
    map.on('styledata', onStyleData);
    // Safety net in case styledata never fires for this particular case.
    map.once('load', trySet);
  }
}

function popupHtml(p) {
  const color = TYPE_COLORS[p.type] || '#64748b';
  const nameHtml = p.url
    ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a>`
    : esc(p.name);
  const areas = Array.isArray(p.areas) && p.areas.length
    ? p.areas.slice(0, 4).map(esc).join(', ') : null;
  const networks = Array.isArray(p.networks) && p.networks.length
    ? p.networks.slice(0, 3).map(esc).join(', ') : null;
  const funders = Array.isArray(p.funders) && p.funders.length
    ? p.funders.slice(0, 3).map(esc).join(', ') : null;
  const regions = Array.isArray(p.regions) && p.regions.length
    ? p.regions.slice(0, 4).map(esc).join(', ') : null;

  return `<div class="popup">
    <div class="popup-name">${nameHtml}${p.acronym ? ` <span class="popup-acr">(${esc(p.acronym)})</span>` : ''}</div>
    <div class="popup-meta">
      <span class="type-badge" style="background:${color}">${esc(p.type || 'unknown')}</span>
      ${p.country ? `<span class="popup-country">${esc(p.country)}</span>` : ''}
    </div>
    ${p.parent_org ? `<div class="popup-row"><em>Org:</em> ${esc(p.parent_org)}</div>` : ''}
    ${areas ? `<div class="popup-row"><em>Research:</em> ${areas}</div>` : ''}
    ${networks ? `<div class="popup-row"><em>Networks:</em> ${networks}</div>` : ''}
    ${regions ? `<div class="popup-row"><em>Inside:</em> ${regions}</div>` : ''}
    ${funders ? `<div class="popup-row"><em>Funders:</em> ${funders}</div>` : ''}
    ${p.url ? `<a class="popup-source" href="${esc(p.url)}" target="_blank" rel="noopener">Visit website</a>` : ''}
  </div>`;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ── Custom controls ────────────────────────────────────────────────
function makeFitControl() {
  return {
    onAdd(m) {
      const div = document.createElement('div');
      div.className = 'maplibregl-ctrl fit-control';
      div.innerHTML = '<a href="#" title="Zoom to data">&#8982; Fit</a>';
      div.querySelector('a').addEventListener('click', (e) => {
        e.preventDefault();
        if (_currentFeatures.length === 0) return;
        const coords = _currentFeatures.map((f) => f.geometry?.coordinates).filter(Boolean);
        if (!coords.length) return;
        const lngs = coords.map((c) => c[0]);
        const lats = coords.map((c) => c[1]);
        m.fitBounds(
          [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
          { padding: 60 }
        );
      });
      return div;
    },
    onRemove() {},
  };
}

function makeLegendControl() {
  return {
    onAdd() {
      const div = document.createElement('div');
      div.className = 'maplibregl-ctrl legend-control';
      div.innerHTML = `
        <div class="legend-header">
          <span>Legend</span>
          <span class="legend-toggle">&#9650;</span>
        </div>
        <div class="legend-body">
          <div class="legend-section legend-points">
            <div class="legend-section-label">Facilities</div>
            <div class="legend-types" id="legend-types">Loading…</div>
          </div>
          <div class="legend-section legend-overlays" id="legend-overlays" hidden>
            <div class="legend-section-label">Overlays</div>
            <div id="legend-overlay-rows"></div>
          </div>
        </div>
      `;
      div.querySelector('.legend-header').addEventListener('click', () => {
        div.classList.toggle('collapsed');
        div.querySelector('.legend-toggle').innerHTML =
          div.classList.contains('collapsed') ? '&#9660;' : '&#9650;';
      });
      div.addEventListener('click', (e) => e.stopPropagation());
      div.addEventListener('wheel', (e) => e.stopPropagation());

      const refresh = () => {
        const ov = _legendOverlayProvider();
        const sec = div.querySelector('#legend-overlays');
        const rows = div.querySelector('#legend-overlay-rows');
        if (!ov || ov.length === 0) {
          sec.hidden = true;
          rows.innerHTML = '';
          return;
        }
        sec.hidden = false;
        rows.innerHTML = ov.map((o) =>
          `<div class="legend-row">
            <span class="legend-chip legend-chip-square" style="background:${o.color}"></span>
            <span>${esc(o.label)}</span>
          </div>`
        ).join('');
      };
      div.addEventListener('legend:refresh', refresh);

      // Initial population: facility types via vocab CSV. Only the
      // types that actually have facilities are shown — reserved slugs
      // (industry / local-gov / university-institute / vessel / virtual)
      // stay in the vocab file but are hidden from the legend so users
      // don't see always-empty chips. Keep this in sync with the
      // `typeSlugs` list in src/filters.js.
      const SHOWN_TYPES = new Set([
        'federal', 'state', 'university-marine-lab', 'nonprofit', 'foundation',
        'network', 'international-federal', 'international-university',
        'international-nonprofit', 'observatory',
      ]);
      fetchCSV(`${BASE}vocab/facility_types.csv`).then((rows) => {
        const body = div.querySelector('#legend-types');
        body.innerHTML = rows
          .filter((r) => SHOWN_TYPES.has(r.slug))
          .map((r) => {
            const color = TYPE_COLORS[r.slug] || '#64748b';
            return `<div class="legend-row">
              <span class="legend-chip" style="background:${color}"></span>
              <span>${esc(r.label)}</span>
            </div>`;
          }).join('');
      }).catch(() => {
        const body = div.querySelector('#legend-types');
        body.innerHTML = Object.entries(TYPE_COLORS).map(([slug, color]) =>
          `<div class="legend-row"><span class="legend-chip" style="background:${color}"></span><span>${slug}</span></div>`
        ).join('');
      });

      refresh();
      return div;
    },
    onRemove() {},
  };
}
