import {
  initMap,
  renderFacilities,
  registerLegendOverlayProvider,
  refreshLegend,
  onViewportChange,
  featuresInView,
  TYPE_COLORS,
} from './map.js';
import { initFilters } from './filters.js';
import { initOverlays, activeOverlays } from './overlays.js';
import { initDB, loadFallback, query } from './db.js';
import { initListView, renderList } from './views/list.js';
import { initStatsView, renderStats } from './views/stats.js';
import { initDocsView, renderDocsView } from './views/docs.js';
import { initNetworkView, renderNetworkView } from './views/network.js';
import { initPeopleView, renderPeopleView } from './views/people.js';
import { initSqlView, renderSqlView } from './views/sql.js';
import { initRouter, currentPath } from './router.js';

const state = {
  filters: { types: new Set(), countries: new Set(), areas: new Set(), networks: new Set(), q: '' },
  lastFeatures: [],
  setFilters(update) {
    Object.assign(this.filters, update);
    refresh();
  },
};

const statusEl = document.getElementById('status');

// ── Hamburger / drawer wiring ───────────────────────────────────────
const toggle = document.getElementById('sidebar-toggle');
const backdrop = document.getElementById('sidebar-backdrop');
function setDrawer(open) {
  document.body.classList.toggle('sidebar-open', open);
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
}
toggle.addEventListener('click', () => setDrawer(!document.body.classList.contains('sidebar-open')));
backdrop.addEventListener('click', () => setDrawer(false));

// ── Init map ────────────────────────────────────────────────────────
const map = initMap(document.getElementById('map'), state);

// ── Init filter sidebar ─────────────────────────────────────────────
initFilters(document.getElementById('filters'), state);

// ── Init overlay layer panel (under the filters) ────────────────────
initOverlays(map, document.getElementById('overlays'), () => {
  refreshLegend();
});
registerLegendOverlayProvider(activeOverlays);

// ── Init other views ────────────────────────────────────────────────
initListView(document.getElementById('browse'));
initStatsView(document.getElementById('stats'));
initNetworkView(document.getElementById('network'));
initPeopleView(document.getElementById('people'));
initSqlView(document.getElementById('sql'));

// ── Debounced search + clear button ────────────────────────────────
const qEl = document.getElementById('q');
const qClear = document.getElementById('q-clear');
function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
qEl.addEventListener('input', debounce((ev) => {
  const val = ev.target.value;
  qClear.classList.toggle('visible', val.length > 0);
  state.setFilters({ q: val });
}, 200));
qClear.addEventListener('click', () => {
  qEl.value = '';
  qClear.classList.remove('visible');
  state.setFilters({ q: '' });
});

// ── Bottom "Facilities in view" panel ───────────────────────────────
//
// Lives beneath the map and shows the subset of `state.lastFeatures`
// whose coordinates fall inside the current map viewport. Updates:
//   - when the filter set changes (drives state.lastFeatures),
//   - when the user pans/zooms the map (onViewportChange fires),
//   - on initial bootstrap.
const mapBrowseEl = document.getElementById('map-browse');
const mapBrowseListEl = document.getElementById('map-browse-list');
const mapBrowseCountEl = document.getElementById('map-browse-count');
const mapBrowseToggleEl = document.getElementById('map-browse-toggle');

function escHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function normalizeFeature(f) {
  return f?.properties ?? f ?? {};
}

function renderMapBrowse(features) {
  const n = features.length;
  if (mapBrowseCountEl) mapBrowseCountEl.textContent = n.toLocaleString();
  if (!mapBrowseListEl) return;

  if (n === 0) {
    mapBrowseListEl.innerHTML =
      '<div class="map-browse-empty">No facilities in view. Zoom out or adjust filters.</div>';
    return;
  }

  // Sort by name for stable display.
  const sorted = [...features].sort((a, b) => {
    const an = String(normalizeFeature(a).name || '').toLowerCase();
    const bn = String(normalizeFeature(b).name || '').toLowerCase();
    return an < bn ? -1 : an > bn ? 1 : 0;
  });

  const rows = sorted.map((f) => {
    const p = normalizeFeature(f);
    const color = TYPE_COLORS[p.type] || '#64748b';
    const id = String(p.id ?? '');
    const url = p.url ? escHtml(p.url) : '';
    const nameCell = url
      ? `<a href="${url}" target="_blank" rel="noopener">${escHtml(p.name ?? '')}</a>`
      : escHtml(p.name ?? '');
    return `<tr data-id="${escHtml(id)}">
      <td class="col-name"><span class="map-browse-swatch" style="background:${color}"></span>${nameCell}</td>
      <td class="col-acronym">${escHtml(p.acronym ?? '')}</td>
      <td class="col-type">${escHtml((p.type ?? '').replace(/-/g, ' '))}</td>
      <td class="col-country">${escHtml(p.country ?? '')}</td>
    </tr>`;
  }).join('');

  mapBrowseListEl.innerHTML = `<table class="map-browse-table">
    <thead><tr>
      <th>Name</th><th>Acronym</th><th>Type</th><th>Country</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function updateMapBrowseFromViewport() {
  renderMapBrowse(featuresInView());
}

if (mapBrowseToggleEl) {
  mapBrowseToggleEl.addEventListener('click', () => {
    const collapsed = mapBrowseEl.classList.toggle('collapsed');
    mapBrowseToggleEl.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    // The map container just changed size — tell MapLibre to resize its
    // canvas and recompute bounds, then re-sync the in-view list.
    setTimeout(() => {
      try { map.resize(); } catch (_) { /* map not ready yet */ }
      scheduleMapBrowseUpdate();
    }, 200);
  });
}
// Throttle fast pan/zoom events so the list doesn't thrash.
let _browseRaf = null;
function scheduleMapBrowseUpdate() {
  if (_browseRaf) return;
  _browseRaf = requestAnimationFrame(() => {
    _browseRaf = null;
    updateMapBrowseFromViewport();
  });
}
onViewportChange(scheduleMapBrowseUpdate);

// ── Refresh: re-query and update active view ────────────────────────
async function refresh() {
  statusEl.textContent = 'Querying…';
  try {
    const features = await query(state.filters);
    state.lastFeatures = features;

    // Always push the new feature set onto the map source (even if the
    // active view isn't the map) so a tab-switch back to Map is instant
    // and reflects the current filters.
    renderFacilities(features);

    // Keep the "browse" / "stats" tabs in sync with filters too.
    renderList(features);
    renderStats(features);

    // The bottom "in view" panel always tracks the map viewport.
    scheduleMapBrowseUpdate();

    const n = features.length.toLocaleString();
    statusEl.innerHTML = `<strong>${n}</strong> facilit${features.length === 1 ? 'y' : 'ies'} match`;
  } catch (err) {
    console.error(err);
    statusEl.textContent = `Query failed: ${err.message}`;
  }
}

// ── View switching ──────────────────────────────────────────────────
const views = {
  '/':        document.getElementById('view-map'),
  '/browse':  document.getElementById('view-browse'),
  '/network': document.getElementById('view-network'),
  '/people':  document.getElementById('view-people'),
  '/sql':     document.getElementById('view-sql'),
  '/stats':   document.getElementById('view-stats'),
  '/docs':    document.getElementById('view-docs'),
};
function showView(path) {
  // Sub-routes like '/people/<id>' need to highlight their parent
  // (/people) — strip the trailing segment when looking up the view.
  const rootSeg = '/' + (path.split('/')[1] || '');
  Object.entries(views).forEach(([p, el]) => {
    el.classList.toggle('active', p === rootSeg);
  });
}

initRouter({
  '/': () => {
    showView('/');
    document.body.classList.remove('no-sidebar');
    setDrawer(false);
    renderFacilities(state.lastFeatures);
  },
  '/browse': () => {
    showView('/browse');
    document.body.classList.remove('no-sidebar');
    setDrawer(false);
    renderList(state.lastFeatures);
  },
  '/network': () => {
    showView('/network');
    document.body.classList.add('no-sidebar');
    setDrawer(false);
    // Network view uses DuckDB directly; kick the render (it's idempotent
    // and caches the graph so subsequent visits are fast).
    renderNetworkView();
  },
  '/people': (path) => {
    showView('/people');
    document.body.classList.add('no-sidebar');
    setDrawer(false);
    // /people/<person_id> jumps + highlights that researcher's card.
    const m = path.match(/^\/people\/(.+)$/);
    renderPeopleView(m ? decodeURIComponent(m[1]) : null);
  },
  '/sql': () => {
    showView('/sql');
    document.body.classList.add('no-sidebar');
    setDrawer(false);
    renderSqlView();
  },
  '/stats': () => {
    showView('/stats');
    document.body.classList.add('no-sidebar');
    setDrawer(false);
    renderStats(state.lastFeatures);
  },
  '/docs': (path) => {
    showView('/docs');
    document.body.classList.add('no-sidebar');
    setDrawer(false);
    // Build the persistent tab shell on first visit, then route the
    // active tab off the URL slug (e.g. '#/docs/methods' →
    // 'methods'). Sub-routes call '/docs' too via the router's
    // top-segment fall-through (see src/router.js).
    initDocsView(document.getElementById('docs'));
    renderDocsView(path);
  },
});

// ── Bootstrap ───────────────────────────────────────────────────────
(async () => {
  try {
    const fallback = await loadFallback();
    state.lastFeatures = fallback;
    renderFacilities(fallback);
    renderList(fallback);
    scheduleMapBrowseUpdate();
    statusEl.innerHTML = `<strong>${fallback.length.toLocaleString()}</strong> facilities (loading interactive query…)`;
  } catch (e) {
    statusEl.textContent = 'No data yet — run the ingest pipeline.';
  }
  try {
    await initDB();
    await refresh();
  } catch (e) {
    console.warn('DuckDB-Wasm unavailable, staying on GeoJSON fallback.', e);
  }
})();

// ── Legend collapses on small screens ───────────────────────────────
if (window.matchMedia('(max-width: 900px)').matches) {
  const intv = setInterval(() => {
    const el = document.querySelector('.legend-control');
    if (el) { el.classList.add('collapsed'); clearInterval(intv); }
  }, 200);
}
