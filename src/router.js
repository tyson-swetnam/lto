// router.js — Hash-based router for the multi-view SPA.
//
// Routes always begin with "#/" (e.g. "#/stats", "#/network"). Anything
// else in `location.hash` — most importantly "#area-xxxx" anchors used
// by the per-research-area TOC inside the Stats view — is an
// **in-page fragment** and must NOT trigger navigation. Without this
// guard, clicking a TOC entry would route to the unknown path
// "area-xxxx", fall through to the default '/' handler, and dump the
// user onto the Map tab.

let _routes = {};
let _currentPath = null;

function isRouteHash(h) {
  return typeof h === 'string' && h.startsWith('#/');
}

function getHash() {
  const h = location.hash || '#/';
  // Only "#/path" is a route. In-page fragments stay on whatever
  // route we're already on.
  if (!isRouteHash(h)) return _currentPath || '/';
  return h.slice(1);
}

function navigate(path) {
  if (path === _currentPath) return;
  _currentPath = path;

  // Top-level segment for tab highlighting + sidebar / handler lookup.
  // 'top' is a reserved global in browser context, so call it 'rootSeg'.
  const rootSeg = '/' + (path.split('/')[1] || '');

  // Update active tab styling. Sub-routes like '/people/<id>' light
  // up the parent tab '/people'.
  document.querySelectorAll('.tabs a[data-view]').forEach((a) => {
    a.classList.toggle('active', a.dataset.view === rootSeg);
  });

  // Hide/show sidebar for views that don't need it.
  const noSidebar = (rootSeg === '/docs' || rootSeg === '/stats'
                  || rootSeg === '/network' || rootSeg === '/sql'
                  || rootSeg === '/people');
  document.body.classList.toggle('no-sidebar', noSidebar);

  // Call route handler. Try exact match first; if the path has
  // sub-segments (e.g. '/people/<id>'), fall back to the top-level
  // handler which is responsible for parsing its own sub-routes.
  const handler = _routes[path] || _routes[rootSeg] || _routes['/'];
  if (handler) handler(path);
}

export function initRouter(routes) {
  _routes = routes;

  window.addEventListener('hashchange', () => {
    // Ignore in-page anchor changes — the browser already scrolled
    // the document to the target element; we don't need to (and
    // mustn't) re-route.
    if (!isRouteHash(location.hash)) return;
    navigate(getHash());
  });

  // Initial route
  navigate(getHash());
}

export function currentPath() {
  return _currentPath;
}
