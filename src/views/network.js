// network.js — Knowledge map (MVG, Map Visualization with Group restriction).
//
// Replaces the previous force-directed knowledge graph with a country-like
// map where each polygon is one research area (parent-collapsed when small),
// polygon area is proportional to how much OBSERVATORY CAPACITY, DATA and
// PEOPLE that area carries, and organisations + people sit inside their
// polygon. Cross-area edges reveal interdisciplinary collaboration.
//
// SIZING METRIC — why it is not the facility count
// ------------------------------------------------
// Region area used to be proportional to research_areas_active.n_facilities.
// Measured against the shipped site parquet, LTO's catalogue holds 445
// facilities, of which 158 are place-type monitoring installations —
// protected areas (18), flux towers (27), streamgage networks (39),
// experimental forest ranges (40), LTAR sites (19), atmospheric baseline
// observatories (10), glacier-monitoring sites (5). That is nothing like
// cod-kmap's 94%-protected-area skew, but a raw facility count still
// measures catalogue coverage, not observatory capacity: a region holding
// dozens of lightly-staffed monitoring points outranked one whose sites
// publish addressable datasets and employ researchers.
//
// The cartogram weight is now DATA_AND_PEOPLE (see the areas query):
//
//   weight = n_organisations
//          + W_DATA_PROVIDER * n_facilities_with_an_archive_edge
//          + W_DATASET       * n_data_products
//          + W_PERSON        * n_people_anchored_here
//
// n_organisations counts non-protected-area facilities only. A "data
// provider" is a facility with at least one facility_archives edge
// (Wave J: its data lives in an authoritative archive); n_data_products
// counts addressable datasets in data_products per facility. The person
// term sums three cohorts that all resolve to this region:
// facility_personnel (the site directory), registry researchers linked to
// a site in this region, and registry researchers with no site link whose
// dominant science domain is this region. Coefficients are declared as
// constants below so the ranking is auditable rather than buried in a SQL
// expression.
//
// Protected areas are NOT deleted — they stay in the catalogue, in the SQL
// console, and behind the off-by-default "Protected areas" layer, which
// draws them as one aggregate chip per region rather than scattered marks.
// They are never counted as organisation units; unlike cod-kmap's,
// though, several DO hold archive links and personnel, and those data and
// people terms still count toward their region.
//
// Implements the KMap algorithm from Hossain, Moradi, Mondal & Kobourov,
// "Map Visualizations for Graphs with Group Restrictions" (Graphics
// Interface 2025, DOI 10.1145/3769872.3769900). Three steps:
//
//   1. Supergraph: one supernode per active research area, weight = the
//      data-and-people weight above, edges = cross-area facility-personnel
//      + co-author counts. Embed with d3-force using square collision so
//      each area gets a non-overlapping square sized by sqrt(weight).
//
//   2. Subgraph layout: for each area, run a small d3-force layout on its
//      facility + person nodes, then scale to fit inside its square.
//
//   3. Voronoi-merged polygons: compute Voronoi over all node positions
//      plus a ring of perimeter "anchor" points; for each area, union the
//      cells of its members via polygon-clipping. Smooth boundaries via
//      one Chaikin pass to soften the polygon outlines.
//
// docs/knowledge-map.md is the reader-facing description: the sizing
// metric, the viewport (fit-to-everything, zoom limits relative to that
// fit) and the screen-space label tiers implemented in the "Label engine"
// section below. PCL refinement, custom force terms and canvas rendering
// in a Web Worker are NOT implemented; an earlier comment pointed at a
// planning doc for them that was never committed.

import { getConn, whenReady, unwrapRow } from '../db.js';

// ── Module state ────────────────────────────────────────────────────
let _container = null;
let _layout = null;
let _layoutPromise = null;        // in-flight fetch + buildLayout
let _d3Promise = null;
let _delaunayPromise = null;
let _polygonClippingPromise = null;
let _showFacility = true;
let _showPerson = true;
// d3.zoom behavior + svg selection + d3 module captured during render
// so the TOC sidebar (and polygon clicks) can call zoom.transform
// programmatically using d3.zoomIdentity.
let _zoomBehavior = null;
let _zoomSvg = null;
let _d3Mod = null;
let _colorOf = null;
// Current d3.zoom transform and its scale. The SVG viewBox is the stage
// in CSS pixels (see render()), so k IS the world→screen scale: one layout
// unit occupies k CSS px. Nothing else composes into it.
let _zoomK = 1;
let _zoomT = null;
// The transform that frames EVERY polygon in the stage, recomputed on each
// resize. scaleExtent is expressed relative to its k (_fitK), so "zoom 4x"
// means the same thing on a phone and on a 27-inch monitor.
let _fitT = null;
let _fitK = 1;
// Stage size in CSS px, as last measured. Equal to the viewBox size.
let _stageW = 0;
let _stageH = 0;
// True once the user has panned or zoomed by hand (or asked for an area).
// While false, a resize re-fits the whole map; once true, a resize keeps
// the user's centre and zoom instead of yanking the view back.
let _userZoomed = false;
// ResizeObserver on #net-stage, created once per stage element.
let _resizeObs = null;
let _resizeRaf = 0;
// Pending requestAnimationFrame id for the label pass (0 = none queued).
let _labelRaf = 0;
// Cached label candidates (see buildLabelCandidates). null = rebuild on the
// next pass; set by markLabelsDirty() whenever a label selection changes.
let _labelCands = null;
// Mark scale last written to the dots, so a pan that does not change k
// does not rewrite 700 radii.
let _markScaleApplied = 0;
// The research area the user asked for (TOC row or polygon click). Its
// name is always drawn and its outline highlighted until Reset /
// double-click / another area.
let _pinnedAreaId = null;
let _polySel = null;
// Reference to the labels/dots selections so the label pass can address
// them without a full re-render.
let _labelSel = null;
let _areaLabelSel = null;
// Two-line variant of each area name (null for one-word names). Drawn as a
// second <text> so switching variant is a display toggle, not a rebuild.
let _areaWrapSel = null;
let _facLabelSel = null;
let _dotPersonSel = null;
let _dotFacSel = null;
// Root <g> that carries the d3.zoom transform.
let _rootG = null;
// Protected-area layer: OFF by default. One aggregate chip per region
// rather than one mark per site — see the protected_areas query.
let _showProtected = false;
let _paLabelSel = null;
let _paChipSel = null;
// Registry researcher name labels for the focused site, and the
// "(no site)" cohort captions for domain-placed researchers.
let _regLabelSel = null;
let _regDomainLabelSel = null;
// Selection for the facility sub-polygons themselves, captured so
// hover/zoom logic can address them later (e.g. dim non-hovered
// polygons in the same area to reveal a single institution).
let _facPolySel = null;

// ── Edge-reveal selection state ─────────────────────────────────────
// Individual cross-area edges are NO LONGER drawn at load. On the shipped
// parquet the full set is 80 deduplicated cross-area pairs, and drawEdges
// emits TWO <line> elements per edge (a wide transparent hit line for
// hover precision plus the visible line) = 160 elements, every one of them
// crossing the middle of the map. The result read as a hairball that hid
// the cartogram the layout exists to show.
//
// Instead exactly ONE node is selected at a time and only ITS incident
// edges exist in the DOM. null = nothing selected = zero edge elements.
// Held as a bare node id — facility_id or person_id, the same key space
// _layout.nodes uses — so render() can re-validate it against the freshly
// built layout and drop it if that node is no longer drawn.
let _selectedNodeId = null;
// Closure installed by render(): wipes the edge container and redraws the
// current selection's incident edges into it. It CAPTURES the live SVG
// group, so invalidateNetworkData() must null it — calling a stale one
// appends into a detached tree, the same class of bug the registry
// selections below are nulled for.
let _redrawEdgeReveal = null;
// The Escape-to-clear listener is attached once per page, not once per
// render(): render() re-runs on every People/Facilities toggle and on
// "Recompute layout", and re-attaching there would stack duplicate
// listeners for the lifetime of the tab.
let _escBound = false;

// ── Registry (researcher) layer state ───────────────────────────────
// The registry layer is OFF by default and its data is fetched lazily
// the first time it is switched on, so the initial map paint costs
// exactly what it costs today. See fetchRegistry() for the payload
// accounting.
let _showRegistry = false;
let _registry = null;            // indexed result of fetchRegistry()
let _registryPromise = null;     // in-flight fetch, so double-toggle is safe
// Which catalogued site is currently expanded into individual
// researcher nodes. null = no site selected (only site↔site ribbons
// are drawn). Exactly one site is expanded at a time — this is the
// gate that keeps a full registry of rows from ever becoming that many
// markers as the harvest grows the roster.
let _focusFacility = null;
// Selections owned by the registry layer, captured so onZoom() can
// counter-scale them and so a focus change can redraw only this layer.
let _regRootG = null;
let _regSiteLinkSel = null;
let _regNodeSel = null;
let _regNodeLinkSel = null;

// 33-step palette for area polygons. Tuned for distinguishability
// against a parchment background with low-alpha fills.
const AREA_PALETTE = [
  '#7c3aed', '#0d9488', '#d97706', '#dc2626', '#2563eb',
  '#059669', '#a16207', '#9333ea', '#0891b2', '#65a30d',
  '#e11d48', '#0284c7', '#ca8a04', '#7e22ce', '#16a34a',
  '#b45309', '#1d4ed8', '#15803d', '#a21caf', '#be123c',
  '#0369a1', '#4d7c0f', '#be185d', '#1e40af', '#166534',
  '#86198f', '#1e3a8a', '#854d0e', '#5b21b6', '#0c4a6e',
  '#365314', '#3f6212', '#172554',
];

const NODE_COLORS = {
  facility: '#0d6e6e',
  person:   '#0ea5e9',
  // Registry researchers are a THIRD colour, distinct from the
  // facility-directory people already on the map (#0ea5e9) and from the
  // teal facility markers (#0d6e6e).
  //
  // This was '#b45309', which IS AREA_PALETTE[15], so registry markers were
  // indistinguishable from whichever region drew that fill. Which region
  // that is depends on the data: colours are assigned by position in the
  // FILTERED (weight > 0) area list, so it moves whenever the weights move —
  // check against the live area ranking rather than naming one here.
  //
  // '#7c2d12' is absent from the 33-entry palette and sits 33.5 RGB units
  // from its nearest member, 158 from the facility teal and 270 from the
  // person sky. Check any replacement the same way before changing it.
  registry: '#7c2d12',
  registryEdge: '#c2410c',
  // Protected-area context layer. A muted olive, chosen the same way the
  // registry colour was: it is absent from the 33-entry AREA_PALETTE, and
  // its nearest palette member ('#4d7c0f') sits 49.4 RGB units away while it
  // is 103.8 from the facility teal and 198.9 from the person sky (Euclidean
  // over 8-bit RGB, the same metric the registry figures above use). Check
  // any replacement the same way.
  protected: '#65803a',
};
const NODE_RADIUS = { facility: 4, person: 3 };

// Registry-layer tuning.
//   FOCUS_NODE_CAP  — hard ceiling on researcher markers drawn for the
//                     focused site. registry_facilities ships EMPTY until
//                     the identity harvest lands, so today no site draws
//                     any; 48 keeps the densest plausible sub-polygon
//                     legible once links arrive, and the side panel lists
//                     the remainder.
//   SITE_LINK_MIN   — minimum co-publication total for a site↔site
//                     ribbon. Left at 1 deliberately: with the harvest not
//                     yet landed there are zero ribbons, and once it lands
//                     a threshold would silently delete weight-1 pairs
//                     (real site links) without saying so anywhere in the
//                     UI. The knob exists for when the registry grows;
//                     raising it means adding a note to the layer.
const FOCUS_NODE_CAP = 48;
const SITE_LINK_MIN  = 1;

// Layout tuning. Polygon area must be roughly proportional to area
// weight (n_facilities), so we size the supernode squares as
// side = SUPERNODE_SCALE * sqrt(weight) — a true cartogram.
//
// CRITICAL: with the previous (small) SUPERNODE_SCALE + a 50 px floor,
// dense areas (coastal-processes 70 facilities packed tightly) ended
// up with TINY Voronoi cells while sparse areas (great-lakes 2
// facilities far apart) got HUGE cells — visually inverted from the
// cartogram metric. Boosted scale to 24 and dropped the floor; we
// now also pepper interior 'decoration anchor' points inside every
// area's square so Voronoi cells tile the full square area, not just
// the immediate neighbourhood of real nodes. Result: polygon area
// closely tracks sqrt(weight)² = weight, as the paper intends.
const SUPERGRAPH_TICKS = 400;
const SUBGRAPH_TICKS   = 120;
const SUPER_PADDING    = 14;     // px gap between adjacent squares
const PERIMETER_PAD    = 0.18;   // anchor ring at 1+pad of layout bbox half-width
const PERIMETER_NODES  = 18;     // outer anchors around the entire layout
// side = SUPERNODE_SCALE * sqrt(weight). On the shipped lto parquet the
// data-and-people weight spans 1.7…465.7 across the 38 non-empty regions
// (of 84 active vocabulary terms; the 46 that carry nothing draw no
// polygon at all), so 34 gives sides of roughly 44…734 px before the
// viewBox fit — comparable canvas to the layout this replaced.
//
// SUPERNODE_MIN is deliberately set BELOW 34*sqrt(min weight) ≈ 44 so
// the floor binds for nothing in the current data. That matters: a
// binding floor inflates the smallest region's AREA by (min/true)², which
// is exactly the cartogram-lying behaviour this metric exists to remove.
// If a future region lands under it, the floor keeps it clickable — but
// check whether it is distorting the ranking before raising it.
const SUPERNODE_SCALE  = 34;     // side = scale * sqrt(weight)
const SUPERNODE_MIN    = 18;     // minimum side so a tiny region stays clickable
const DECOR_GRID       = 5;      // 5×5 = 25 decoration anchors per area square
const DECOR_JITTER     = 0.18;   // ±18% random jitter so cell boundaries aren't gridlike

// Fraction of a facility's sub-circle radius that a person marker may
// occupy. Named rather than inlined because the person spiral and the
// containment clamp that follows it MUST use the same number — when they
// were separate literals the clamp could not actually enforce the spiral's
// own bound. A facility sub-circle is a membership claim, so "inside the
// circle" is a correctness property of this map, not a spacing preference.
const PERSON_R_FRAC    = 0.88;

// ── Cartogram weight coefficients (see the header note) ─────────────
// Region area ∝ this weight. An organisation is worth 1. Holding an
// archive edge (facility_archives — "this site's data lives in an
// authoritative archive") is worth 3 on top of that. Unlike cod-kmap,
// where data providers were rare, 374 of lto's 445 catalogued facilities
// hold an archive edge, so this term shifts weight toward regions whose
// sites actually publish rather than acting as a rarity bonus; the
// discriminating terms are the datasets and the people. Each addressable
// data product adds 1.5 (469 products across 310 facilities on the
// shipped parquet), so a site with 8 datasets outweighs one with 1. A
// person is worth 0.35 so head-count lifts a region without letting it
// dominate one with data.
//
// Measured effect on the shipped site parquet (verify with the areas SQL
// below): weights span 1.7…465.7; Biogeochemistry (71 orgs, 99 products,
// 69 archive-linked sites, ~112 people) and Coastal processes (82 orgs,
// 72 products, 78 archive-linked sites) lead, with Biological
// oceanography third at roughly a third of their weight.
const W_DATA_PROVIDER = 3.0;
const W_DATASET       = 1.5;
const W_PERSON        = 0.35;

// ── Label sizing: on-screen pixels, not SVG units ───────────────────
// Every label class declares the size it should occupy ON THE SCREEN. The
// label pass draws each visible <text> under a `scale(1/k)` counter-
// transform, so font-size, halo width and offsets are all written in CSS
// px once, and the rendered text is the declared size at every zoom.
//
// The floor is the legibility gate. The tooltip is the user's stated size
// reference: .network-tooltip is 0.82rem on a 14 px root = 11.5 px body,
// with .tt-sub at 0.78rem = 10.9 px and .tt-kind at 0.7rem = 9.8 px. So
// 9.8 px is the smallest text this site already asks anyone to read, and
// LABEL_MIN_PX is set there. Every size below is >= the floor by
// construction; a label that cannot be drawn at its size is HIDDEN, never
// shrunk below it.
const LABEL_MIN_PX = 9.8;
// Area (region) names: the top of the hierarchy, sized like the tooltip
// title (.tt-name 0.92rem = 12.9 px) at the small end and up to 18 px for
// the heaviest region. This was 13–20 px; at the overview a 20 px name is
// wider than all but the largest polygons, so the top end came down.
const AREA_LABEL_PX       = { min: 12.0, max: 18.0 };
// Smaller tier an area name drops to before it is hidden (P0-3). 11 px is
// .tt-sub size, still above the floor.
const AREA_LABEL_PX_SMALL = 11.0;
// Last-resort tier for the AREA_TOP_N heaviest regions only: a single word
// such as "Biogeochemistry" has no two-line form, and on a phone the
// largest region was the one left unnamed at 11 px. 10 px is above the
// floor; lighter regions stop at AREA_LABEL_PX_SMALL so region names stay
// a step above institution names.
const AREA_LABEL_PX_MIN   = 10.0;
const AREA_TOP_N          = 3;
// Organisation names: tooltip-body size, never below the floor.
const FAC_LABEL_PX      = { min: 10.5, max: 14.0 };
// Researcher names: tooltip .tt-kind size at the small end.
const PERSON_LABEL_PX   = { min: 10.0, max: 13.5 };
// Registry-researcher names in the focused-site expansion.
const REG_LABEL_PX      = { min: 10.0, max: 12.5 };
// Protected-area aggregate chips.
const PA_LABEL_PX       = { min: 10.0, max: 12.0 };
// Halo (paint-order stroke) widths in screen px. Area names get the
// heaviest halo because they sit over facility fills and dots.
const HALO_PX = { area: 3.5, fac: 2.2, person: 2.4, reg: 2.0, pa: 2.0 };

// ── Label tiers: eligibility by ON-SCREEN SIZE, not by zoom level ───
// The old ZOOM_BANDS gated each class on raw d3 k. k had no fixed meaning
// on screen — it was relative to a viewBox cropped from the layout, so
// k = 1 was a world→screen scale of 0.264 at 1600 px, 0.207 at 1280 px and
// 0.091 on a phone — and the bands fired at different places on every
// display. A label now shows when the thing it names is big enough on the
// screen to hold it, which is the same test on every display:
//
//   area name    the name (width × AREA_LABEL_FIT) lies inside the polygon
//                on its top, middle and bottom rows, at the pole or at one
//                of the fallback positions placeArea() tries, preferring
//                one clear of the region's institutions. Tried as one line,
//                two lines, then at AREA_LABEL_PX_SMALL (and, for the
//                AREA_TOP_N heaviest regions, AREA_LABEL_PX_MIN); otherwise
//                hidden (the TOC and the tooltip carry the name). While the
//                polygon covers >= AREA_INSIDE_FRAC of the stage the user is
//                inside it: its name is pinned near the top of the stage
//                (placeAreaTop) instead of at its pole, so a deep zoom still
//                says which region it is in. A region covering >=
//                AREA_SCAN_FRAC whose name found no spot near its pole gets
//                the same top-row placement as a last try. The pinned area (TOC / polygon
//                click) is always named.
//   organisation its sub-polygon is >= FAC_MIN_POLY_PX across both ways and
//                >= FAC_LABEL_FIT × the label width.
//   researcher   their institution's sub-polygon is >= PERSON_MIN_FACPOLY_PX
//                across (a researcher with no institution drawn in the
//                region: the region >= PERSON_MIN_AREAPOLY_PX).
//   registry     the focused site's sub-polygon >= PERSON_MIN_FACPOLY_PX.
//   chips        protected-area chips and "N no site" captions: the region
//                >= CONTEXT_MIN_POLY_PX across.
const AREA_LABEL_FIT        = 1.0;
const AREA_INSIDE_FRAC      = 0.75;
// A region whose on-stage part covers this share of the stage, and whose
// name found no spot near its pole, is named on the topmost row of the
// stage where the name fits (placeAreaTop).
const AREA_SCAN_FRAC        = 0.2;
// Region-name placement (runLabelPass → placeArea): vertical shifts tried
// after the pole, as fractions of the vertical chord through it; how far
// inside the stage edge the pole must sit before alternative anchors in
// the region's on-stage part are tried; and the on-screen size (px, the
// region's smaller bbox side) from which its name also keeps off every
// institution dot, not only the ones being named.
const AREA_LABEL_SHIFTS     = [0, -0.22, 0.22, -0.34, 0.34];
const AREA_EDGE_MARGIN_PX   = 40;
const AREA_DOT_AVOID_PX     = 150;
const FAC_MIN_POLY_PX       = 40;
const FAC_LABEL_FIT         = 0.8;
const PERSON_MIN_FACPOLY_PX = 120;
const PERSON_MIN_AREAPOLY_PX = 480;
const CONTEXT_MIN_POLY_PX   = 60;

// ── Collision pass ──────────────────────────────────────────────────
// ONE greedy pass over every eligible label of every class, in screen
// space, highest priority first: pinned area > area > context chips >
// organisation > registry researcher > researcher. A label is drawn only
// when its padded box is fully on the stage and touches no label already
// placed. Boxes are looked up in a uniform grid of CULL_CELL_PX cells, so
// the pass is linear in the number of candidates instead of the old
// per-class O(n²) getBBox() loop (which never compared ACROSS classes —
// 115–267 cross-class overlaps at 1600 px — and never culled area names).
const LABEL_PAD_PX  = 3;
const CULL_CELL_PX  = 64;
// Box height of one text line, in em. Generous on purpose: Chrome's text
// bounding box for system-ui runs ~1.16 em, and a box that is too small
// lets glyphs touch.
const LINE_BOX_EM   = 1.25;
// Baseline-to-baseline distance of a wrapped area name, in em.
const LINE_GAP_EM   = 1.15;

// ── Viewport ────────────────────────────────────────────────────────
// FIT_PAD_PX     stage margin around the whole map at the fit
// AREA_FIT_PAD_PX stage margin around a polygon the user asked for
// MIN/MAX_ZOOM_MULT scaleExtent as multiples of the fit scale. Zoom-out
//                stops at the fitted view ("everything"): going further
//                only shrank the map into an empty stage. Zoom-in goes to
//                24x, or further when the stage needs it: the limit is
//                raised to the zoom that frames the smallest region in the
//                stage (see applyZoomExtents), so on a phone — where 24x
//                left the smallest region 170 px wide on a 374 px stage —
//                every region can still be brought up to full size.
// MAX_ZOOM_CAP_MULT  hard ceiling on that raise.
const FIT_PAD_PX      = 24;
const AREA_FIT_PAD_PX = 48;
const MIN_ZOOM_MULT   = 1.0;
const MAX_ZOOM_MULT   = 24;
const MAX_ZOOM_CAP_MULT = 200;
// Dots and ribbons keep a constant apparent size too, but their world-
// space growth is capped so zooming far out cannot inflate a 2.6-unit dot
// into a blob that swallows its sub-polygon.
const MARK_MAX_GROWTH = 2.0;
// Region outline and fill. Stroke widths are screen px (non-scaling).
const AREA_STROKE_PX           = 1.2;
const AREA_STROKE_PX_PINNED    = 3.0;
const AREA_FILL_OPACITY        = 0.18;
const AREA_FILL_OPACITY_PINNED = 0.30;

// Map a value onto a class's screen-px range with sqrt damping, then
// clamp into [min, max]. Guarantees the result is >= LABEL_MIN_PX for
// every range declared above.
function rampPx(range, value, denom) {
  const t = denom > 0 ? Math.sqrt(Math.max(0, value) / denom) : 0;
  const px = range.min + t * (range.max - range.min);
  return Math.max(LABEL_MIN_PX, range.min, Math.min(range.max, px));
}

// ── Async-import helpers ────────────────────────────────────────────
function loadD3() {
  if (_d3Promise) return _d3Promise;
  _d3Promise = import('https://esm.sh/d3@7');
  return _d3Promise;
}
function loadDelaunay() {
  if (_delaunayPromise) return _delaunayPromise;
  _delaunayPromise = import('https://esm.sh/d3-delaunay@6');
  return _delaunayPromise;
}
function loadPolygonClipping() {
  if (_polygonClippingPromise) return _polygonClippingPromise;
  _polygonClippingPromise = import('https://esm.sh/polygon-clipping@0.15.7');
  return _polygonClippingPromise;
}


// ── Data fetch ──────────────────────────────────────────────────────
// db.js releases whenReady() with no connection after its own start-up
// timeout (30 s), but on a cold load DuckDB-Wasm can take longer than that
// and still come up — one traced load released at 30.4 s and connected at
// 68.8 s. Throwing at the release left the map failed for good. Instead,
// poll getConn() for up to DB_WAIT_MS and say on the status line that the
// map is waiting.
const DB_WAIT_MS = 180000;
const DB_POLL_MS = 500;
const DB_NOT_READY = 'DuckDB connection not ready';

async function waitForConn() {
  try { await whenReady(); } catch (_) { /* polled below */ }
  let conn = getConn();
  if (conn) return conn;
  const t0 = Date.now();
  const statusEl = _container && _container.querySelector('#net-status');
  while (!conn && Date.now() - t0 < DB_WAIT_MS) {
    if (statusEl) {
      statusEl.textContent = 'Waiting for the database to start… '
        + `(${Math.round((Date.now() - t0) / 1000)} s)`;
    }
    await new Promise((r) => setTimeout(r, DB_POLL_MS));
    conn = getConn();
  }
  if (!conn) throw new Error(DB_NOT_READY);
  return conn;
}

async function fetchData() {
  const conn = await waitForConn();

  const queries = {
    // ACTIVE areas only — collapsed_into IS NULL means this area is its
    // own polygon. Collapsed areas are absorbed into their parent in the
    // facility/person primary tables already.
    //
    // `weight` is the DATA-AND-PEOPLE weight that sizes the region, NOT
    // n_facilities. n_facilities is still selected as raw_facilities so
    // the TOC and tooltips can state the catalogue count alongside the
    // metric that actually drives area. n_protected is reported so the
    // protected areas held back from the organisation count stay visible
    // in the UI instead of silently dropped.
    //
    // Coefficients are interpolated from the W_* constants above, so the
    // metric is edited in one place.
    areas: `
      WITH org AS (
        SELECT g.primary_area_id AS area_id,
               f.facility_id,
               (f.facility_type LIKE 'protected-area%') AS is_protected
        FROM   facilities f
        JOIN   facility_primary_groups g ON g.facility_id = f.facility_id
        WHERE  g.primary_area_id IS NOT NULL
      ),
      arc AS (
        -- Wave J: a facility with ANY archive edge is a data provider.
        SELECT DISTINCT facility_id
        FROM   facility_archives
      ),
      ds AS (
        SELECT facility_id, COUNT(DISTINCT product_id) AS n_datasets
        FROM   data_products
        GROUP  BY facility_id
      ),
      reg_site AS (
        SELECT facility_id, COUNT(DISTINCT canonical_id) AS n_reg
        FROM   registry_facilities
        GROUP  BY facility_id
      ),
      dir_people AS (
        SELECT facility_id, COUNT(DISTINCT person_id) AS n_dir
        FROM   facility_personnel
        GROUP  BY facility_id
      ),
      per_area AS (
        SELECT o.area_id,
               COUNT(*) FILTER (WHERE NOT o.is_protected)      AS n_org,
               COUNT(*) FILTER (WHERE o.is_protected)          AS n_protected,
               COALESCE(SUM(ds.n_datasets), 0)                 AS n_datasets,
               COUNT(DISTINCT CASE WHEN arc.facility_id IS NOT NULL
                                   THEN o.facility_id END)     AS n_data_providers,
               COALESCE(SUM(reg_site.n_reg), 0)                AS n_reg_sited,
               COALESCE(SUM(dir_people.n_dir), 0)              AS n_directory
        FROM   org o
        LEFT   JOIN arc         ON arc.facility_id         = o.facility_id
        LEFT   JOIN ds          ON ds.facility_id          = o.facility_id
        LEFT   JOIN reg_site    ON reg_site.facility_id    = o.facility_id
        LEFT   JOIN dir_people  ON dir_people.facility_id  = o.facility_id
        GROUP  BY o.area_id
      ),
      -- Registry researchers with NO site link, placed by dominant domain.
      -- They are people the region genuinely carries, so they count toward
      -- its weight even though they have no physical position.
      reg_domain AS (
        SELECT g.primary_area_id AS area_id, COUNT(*) AS n_reg_domain
        FROM   person_registry pr
        JOIN   person_primary_groups g ON g.person_id = pr.person_id
        WHERE  g.primary_area_id IS NOT NULL
          AND  pr.canonical_id NOT IN (SELECT canonical_id FROM registry_facilities)
        GROUP  BY g.primary_area_id
      )
      SELECT a.area_id                        AS id,
             a.label                          AS name,
             a.n_facilities                   AS raw_facilities,
             -- Every numeric column is cast to a plain SQL type that
             -- duckdb-wasm hands back as a JS number. This is load-bearing,
             -- not tidiness: multiplying an integer count by a JS-side
             -- decimal literal yields DECIMAL(38,2), and duckdb-wasm returns
             -- DECIMAL as an Arrow structured value, NOT a number. Number()
             -- on it is NaN, "NaN || 0" is 0, so "weight > 0" was false for
             -- EVERY area, data.areas came back empty, allNodes was empty,
             -- and the Voronoi bounds went NaN — "invalid bounds", blank map.
             -- HUGEINT (from SUM over BIGINT) has the same problem.
             -- duckdb-python returns a plain float for both, so this is
             -- invisible to any check that does not run in the browser.
             CAST(COALESCE(p.n_org, 0) AS INTEGER)            AS n_org,
             CAST(COALESCE(p.n_protected, 0) AS INTEGER)      AS n_protected,
             CAST(COALESCE(p.n_datasets, 0) AS INTEGER)       AS n_datasets,
             CAST(COALESCE(p.n_data_providers, 0) AS INTEGER) AS n_data_providers,
             CAST(COALESCE(p.n_reg_sited, 0)
                  + COALESCE(p.n_directory, 0)
                  + COALESCE(d.n_reg_domain, 0) AS INTEGER)   AS n_people,
             CAST(
               COALESCE(p.n_org, 0)
               + ${W_DATA_PROVIDER} * COALESCE(p.n_data_providers, 0)
               + ${W_DATASET}       * COALESCE(p.n_datasets, 0)
               + ${W_PERSON}        * (COALESCE(p.n_reg_sited, 0)
                                       + COALESCE(p.n_directory, 0)
                                       + COALESCE(d.n_reg_domain, 0))
               AS DOUBLE)                                     AS weight
      FROM   research_areas_active a
      LEFT   JOIN per_area   p ON p.area_id = a.area_id
      LEFT   JOIN reg_domain d ON d.area_id = a.area_id
      WHERE  a.collapsed_into IS NULL
      ORDER  BY a.area_id`,

    // One row per ORGANISATION with its primary area + display fields.
    // Protected areas are excluded here: they are context, not organisation
    // units. They stay catalogued, stay queryable in the SQL console, and
    // are drawn by the opt-in protected-areas layer as one aggregate chip
    // per region (see the protected_areas query below).
    facilities: `
      SELECT f.facility_id AS id,
             f.canonical_name AS name,
             f.acronym,
             f.country,
             f.facility_type AS f_type,
             f.url,
             g.primary_area_id AS area_id
      FROM   facilities f
      JOIN   facility_primary_groups g ON g.facility_id = f.facility_id
      WHERE  g.primary_area_id IS NOT NULL
        AND  f.facility_type NOT LIKE 'protected-area%'`,

    // Protected-area AGGREGATE, one row per region. Off-by-default layer.
    // Deliberately an aggregate, not one mark per site: the layer exists
    // to say "this region also contains N protected areas of these kinds",
    // which is legitimate observatory context (research natural areas,
    // wilderness monitoring sites), stated without scattering extra marks
    // over the cartogram. Counts come straight from this query, never
    // from prose.
    protected_areas: `
      SELECT g.primary_area_id AS area_id,
             COUNT(*)          AS n_protected,
             COUNT(DISTINCT f.facility_type) AS n_kinds,
             COUNT(*) FILTER (WHERE f.facility_type = 'protected-area-state')   AS n_state,
             COUNT(*) FILTER (WHERE f.facility_type = 'protected-area-federal') AS n_federal,
             COUNT(*) FILTER (WHERE f.facility_type = 'protected-area-private') AS n_private
      FROM   facilities f
      JOIN   facility_primary_groups g ON g.facility_id = f.facility_id
      WHERE  g.primary_area_id IS NOT NULL
        AND  f.facility_type LIKE 'protected-area%'
      GROUP  BY g.primary_area_id`,

    // Addressable data products per facility (Wave J) — drives the
    // dataset count on a site's tooltip and its label weight.
    fac_datasets: `
      SELECT facility_id,
             COUNT(DISTINCT product_id) AS n_datasets
      FROM   data_products
      GROUP  BY facility_id`,

    // Facilities holding at least one archive edge (Wave J) — the
    // "data provider" flag that drives the larger site marker.
    fac_archives: `
      SELECT DISTINCT facility_id
      FROM   facility_archives`,

    // One row per person with primary area + their importance metrics.
    // Importance combines:
    //   - n_pubs      : SUM(n_publications) across all areas the person
    //                   has work in (from person_area_metrics)
    //   - n_coauth    : SUM(n_co_authors)  across all areas
    //   - facility_funding_usd
    //                 : SUM(facility_area_funding.total_usd_nominal)
    //                   across every facility the person works at —
    //                   their "associated funding base" (a person at
    //                   WHOI gets WHOI's $1.5B, a person at a small
    //                   NEP gets ~$5M).
    // Used downstream for node-radius scaling so prolific +
    // well-funded researchers are visually larger.
    people: `
      WITH per_pa AS (
        -- CAST: SUM(INTEGER/BIGINT) is HUGEINT in DuckDB, which duckdb-wasm
        -- hands to JS as a BigInt — mixing it with plain numbers throws.
        -- scripts/qa.py check_view_sql_types gates on exactly this.
        SELECT person_id,
               CAST(SUM(n_publications)  AS DOUBLE) AS n_pubs,
               CAST(SUM(n_co_authors)    AS DOUBLE) AS n_coauth,
               CAST(SUM(total_citations) AS DOUBLE) AS total_citations
        FROM person_area_metrics
        GROUP BY person_id
      ),
      per_fund AS (
        -- One count per (person, facility): two roles at one facility must
        -- not add its funding twice (same rule as the People cards).
        SELECT fp.person_id,
               CAST(SUM(faf.total_usd_nominal) AS DOUBLE) AS facility_funding_usd
        FROM (SELECT DISTINCT person_id, facility_id FROM facility_personnel) fp
        JOIN facility_area_funding faf ON faf.facility_id = fp.facility_id
        GROUP BY fp.person_id
      )
      SELECT p.person_id AS id,
             p.name,
             p.orcid,
             p.openalex_id,
             p.homepage_url,
             g.primary_area_id        AS area_id,
             COALESCE(pa.n_pubs, 0)   AS n_pubs,
             COALESCE(pa.n_coauth, 0) AS n_coauth,
             COALESCE(pa.total_citations, 0) AS total_citations,
             COALESCE(pf.facility_funding_usd, 0) AS facility_funding_usd
      FROM   people p
      JOIN   person_primary_groups g ON g.person_id = p.person_id
      LEFT  JOIN per_pa  pa ON pa.person_id = p.person_id
      LEFT  JOIN per_fund pf ON pf.person_id = p.person_id
      WHERE  g.primary_area_id IS NOT NULL`,

    // Facility ↔ person via facility_personnel (intra+inter polygon).
    fac_pers: `
      SELECT facility_id AS source, person_id AS target,
             COUNT(*) AS w
      FROM   facility_personnel
      GROUP  BY facility_id, person_id`,

    // Per-person role/title/institution lookup for tooltips. A person
    // can hold roles at multiple facilities — we list-aggregate so the
    // tooltip can show each affiliation. Prefer key-personnel rows so
    // 'Director' / 'Principal Investigator' surfaces above 'Staff'.
    person_affiliations: `
      SELECT fp.person_id,
             list(struct_pack(
               role        := fp.role,
               title       := fp.title,
               facility_id := f.facility_id,
               facility    := COALESCE(f.acronym || ' — ' || f.canonical_name,
                                       f.canonical_name),
               is_key      := fp.is_key_personnel
             ) ORDER BY fp.is_key_personnel DESC, fp.role) AS roles
      FROM facility_personnel fp
      JOIN facilities f ON f.facility_id = fp.facility_id
      GROUP BY fp.person_id`,

    // Person → primary facility for the hierarchy layout. A person
    // might work at >1 facility; we pick their first key-personnel
    // row, falling back to alphabetic role if no key-flag set.
    person_primary_facility: `
      WITH ranked AS (
        SELECT person_id, facility_id,
               ROW_NUMBER() OVER (
                 PARTITION BY person_id
                 ORDER BY is_key_personnel DESC, role, facility_id
               ) AS rk
        FROM facility_personnel
      )
      SELECT person_id, facility_id
      FROM ranked WHERE rk = 1`,

    // Person ↔ person via co-authorship.
    coauthors: `
      SELECT person_a_id AS source, person_b_id AS target,
             co_pub_count AS w
      FROM   collaborations
      WHERE  co_pub_count >= 2`,
  };

  const out = {};
  for (const [k, sql] of Object.entries(queries)) {
    const r = await conn.query(sql);
    // unwrapRow converts Arrow Vector LIST<STRUCT> columns (e.g. the
    // `roles` array on person_affiliations) to plain JS arrays so the
    // downstream Array.isArray / .map / Map(...) usage works. Without
    // this, every person's tooltip showed an empty roles list because
    // Arrow Vectors fail Array.isArray.
    out[k] = r.toArray().map((row) => unwrapRow(row.toJSON()));
  }
  // Coerce BigInt counts to Number.
  for (const a of out.areas) {
    a.weight          = Number(a.weight) || 0;
    a.raw_facilities  = Number(a.raw_facilities) || 0;
    a.n_org           = Number(a.n_org) || 0;
    a.n_protected     = Number(a.n_protected) || 0;
    a.n_datasets      = Number(a.n_datasets) || 0;
    a.n_data_providers = Number(a.n_data_providers) || 0;
    a.n_people        = Number(a.n_people) || 0;
  }
  for (const e of out.fac_pers) e.w = Number(e.w) || 1;
  for (const e of out.coauthors) e.w = Number(e.w) || 1;
  for (const r of out.protected_areas) {
    r.n_protected = Number(r.n_protected) || 0;
    r.n_kinds     = Number(r.n_kinds) || 0;
    r.n_state     = Number(r.n_state) || 0;
    r.n_federal   = Number(r.n_federal) || 0;
    r.n_private   = Number(r.n_private) || 0;
  }

  // A region with weight 0 carries no organisation, no dataset and nobody,
  // so it has nothing to draw and no basis for an area. Dropping it here
  // (rather than giving it a min-side square) is what stops 15 empty
  // vocabulary terms from occupying map real estate. They remain in the
  // vocabulary and in the SQL console; the status line reports the count.
  const allAreas = out.areas;
  out.areas = allAreas.filter((a) => a.weight > 0);
  out.n_areas_empty = allAreas.length - out.areas.length;

  // Addressable data products per facility + the archive-edge provider
  // flag (Wave J).
  const dsBy = new Map(out.fac_datasets.map(
    (r) => [r.facility_id, Number(r.n_datasets) || 0]));
  const arcSet = new Set(out.fac_archives.map((r) => r.facility_id));
  for (const f of out.facilities) {
    f.n_datasets = dsBy.get(f.id) || 0;
    f.is_provider = arcSet.has(f.id);
  }

  // Protected-area aggregate, keyed by region, for the opt-in layer.
  out.protectedByArea = new Map(out.protected_areas.map((r) => [r.area_id, r]));

  // Build lookup tables for hierarchy + tooltip enrichment.
  const affilsBy = new Map(out.person_affiliations.map(
    (r) => [r.person_id, r.roles || []]));
  const primaryFacBy = new Map(out.person_primary_facility.map(
    (r) => [r.person_id, r.facility_id]));
  for (const p of out.people) {
    p.affiliations = affilsBy.get(p.id) || [];
    p.primary_facility_id = primaryFacBy.get(p.id) || null;
  }
  return out;
}


// ── Registry data fetch (lazy — only on first layer switch-on) ───────
//
// The layer is behind a switch instead of loading with the map so a
// session that only wants the research-area cartogram never pays for it.
// duckdb-wasm requests parquet over HTTP range reads, so the columns this
// view never touches (name parts, tier_score, affiliation_ror, i10_index,
// two_yr_mean_citedness, source bookkeeping) genuinely stay on the
// server — a column-projection saving, not a hopeful one.
//
// ROW COUNTS the browser receives, on the parquet shipped at the time of
// writing: person_registry carries the 116-identity core tier (88 site
// personnel + 28 affiliated scholars — the is_site_personnel /
// is_scholar cohorts). registry_facilities and registry_collaborations
// ship EMPTY until the OpenAlex/ORCID identity harvest lands, so roster,
// collabs and siteEdges all come back with 0 rows and every code path
// below must degrade to "layer on, nothing to draw yet" rather than
// error. The domain-placed cohorts (88 identities that resolve to a
// region via person_primary_groups) are the only registry marks the map
// can draw today; rosters and ribbons fill in as the harvest lands.
async function fetchRegistry() {
  const conn = await waitForConn();

  const queries = {
    // Researcher ↔ site roster. `graph_harvested` distinguishes
    // "no collaborators found" from "this identity was never part of
    // the co-authorship harvest", which is the difference between a
    // real zero and a not-yet-computed one. Until the harvest lands,
    // registry_collaborations ships EMPTY, so NOBODY counts as
    // harvested and the tooltip says "not yet computed" — the honest
    // reading of the current data. Once any edge exists, every identity
    // with an openalex_id was walkable by the harvester, and an empty
    // edge list becomes a real zero.
    // affiliation is deliberately NOT selected here — it is the
    // ROR-matched institution, i.e. the site row we already have.
    roster: `
      WITH harvest AS (
        SELECT COUNT(*) > 0 AS done FROM registry_collaborations
      )
      SELECT rf.facility_id,
             p.canonical_id,
             p.display_name,
             p.orcid,
             p.openalex_id,
             p.homepage_url,
             p.affiliation_country,
             p.person_id,
             p.tier_rank,
             COALESCE(p.works_count, 0)     AS works_count,
             COALESCE(p.cited_by_count, 0)  AS cited_by_count,
             COALESCE(p.h_index, 0)         AS h_index,
             COALESCE(p.lto_works_count, 0) AS lto_works_count,
             p.lto_share,
             (h.done AND p.openalex_id IS NOT NULL) AS graph_harvested
      FROM   registry_facilities rf
      JOIN   person_registry p ON p.canonical_id = rf.canonical_id
      CROSS  JOIN harvest h
      ORDER  BY rf.facility_id, p.tier_rank`,

    // Collaborator rows, densified to one row per (linked researcher,
    // collaborator) direction so the client never has to test both
    // orientations of the a<b storage convention.
    // other_facility_id is NULL when the collaborator has no site link
    // — they exist in the registry but have no position on this map.
    collabs: `
      WITH placed AS (
        SELECT canonical_id, facility_id FROM registry_facilities
      ),
      ends AS (
        SELECT canonical_id_a AS cid, canonical_id_b AS other,
               co_pub_count AS w, first_year, last_year
        FROM   registry_collaborations
        UNION ALL
        SELECT canonical_id_b AS cid, canonical_id_a AS other,
               co_pub_count AS w, first_year, last_year
        FROM   registry_collaborations
      )
      SELECT e.cid,
             e.other,
             e.w              AS co_pubs,
             e.first_year,
             e.last_year,
             p2.display_name  AS other_name,
             p2.affiliation   AS other_affiliation,
             pl2.facility_id  AS other_facility_id
      FROM   ends e
      JOIN   placed pl ON pl.canonical_id = e.cid
      JOIN   person_registry p2 ON p2.canonical_id = e.other
      LEFT   JOIN placed pl2 ON pl2.canonical_id = e.other
      ORDER  BY e.cid, e.w DESC`,

    // Site ↔ site co-publication aggregate: sum co_pub_count over
    // every researcher pair whose two endpoints sit at DIFFERENT
    // catalogued sites. This is the map-scale edge — 18 rows, versus
    // 5,300 researcher-level edges, so it can be drawn unconditionally.
    site_edges: `
      WITH placed AS (
        SELECT canonical_id, facility_id FROM registry_facilities
      ),
      pair AS (
        SELECT a.facility_id AS fa, b.facility_id AS fb,
               e.co_pub_count AS w,
               e.canonical_id_a AS ca, e.canonical_id_b AS cb
        FROM   registry_collaborations e
        JOIN   placed a ON a.canonical_id = e.canonical_id_a
        JOIN   placed b ON b.canonical_id = e.canonical_id_b
      )
      SELECT CASE WHEN fa < fb THEN fa ELSE fb END AS source,
             CASE WHEN fa < fb THEN fb ELSE fa END AS target,
             CAST(SUM(w) AS DOUBLE)                AS co_pubs,
             COUNT(*)                              AS n_pairs
      FROM   pair
      WHERE  fa <> fb
      GROUP  BY 1, 2
      ORDER  BY co_pubs DESC`,

    // ── PLACEMENT ROUTE 2: dominant science domain ───────────────────
    // A registry researcher with no site link has NO physical position.
    // Where person_primary_groups resolves a dominant research area for
    // them, they are placed in that REGION instead — which is a claim
    // about their science, not about where they work.
    //
    // Counts on the shipped site parquet: 116 core-tier rows, 0 with a
    // site link (registry_facilities fills with the identity harvest),
    // 88 domain-placed here, 28 with neither. The split is surfaced in
    // the status line and the scope note, because "placed in a region"
    // and "located at a site" are different statements and the map must
    // not conflate them.
    //
    // Aggregated per region deliberately: individually-drawn markers
    // scattered inside region polygons would be indistinguishable from
    // sited researchers, which is exactly the confusion to avoid. One
    // dashed cohort badge per region, expandable into a list, keeps the
    // distinction visible.
    domain_placed: `
      SELECT g.primary_area_id AS area_id,
             COUNT(*)          AS n_people,
             list(struct_pack(
               canonical_id  := pr.canonical_id,
               display_name  := pr.display_name,
               orcid         := pr.orcid,
               openalex_id   := pr.openalex_id,
               homepage_url  := pr.homepage_url,
               person_id     := pr.person_id,
               affiliation   := pr.affiliation,
               h_index       := COALESCE(pr.h_index, 0),
               lto_works     := COALESCE(pr.lto_works_count, 0)
             ) ORDER BY pr.tier_rank) AS people
      FROM   person_registry pr
      JOIN   person_primary_groups g ON g.person_id = pr.person_id
      WHERE  g.primary_area_id IS NOT NULL
        AND  pr.canonical_id NOT IN (SELECT canonical_id FROM registry_facilities)
      GROUP  BY g.primary_area_id`,

    // Registry-wide placement accounting, so the UI states coverage from
    // the data rather than from a hardcoded number.
    placement_totals: `
      WITH sited AS (SELECT DISTINCT canonical_id FROM registry_facilities)
      SELECT COUNT(*) AS n_registry,
             COUNT(*) FILTER (WHERE s.canonical_id IS NOT NULL) AS n_sited,
             COUNT(*) FILTER (WHERE s.canonical_id IS NULL
                                AND g.primary_area_id IS NOT NULL) AS n_domain,
             COUNT(*) FILTER (WHERE s.canonical_id IS NULL
                                AND g.primary_area_id IS NULL)     AS n_unplaced
      FROM   person_registry pr
      LEFT   JOIN sited s ON s.canonical_id = pr.canonical_id
      LEFT   JOIN person_primary_groups g ON g.person_id = pr.person_id`,

    // Intra-site co-publication, for the site tooltip ("N of the
    // researchers here publish with each other").
    site_internal: `
      WITH placed AS (
        SELECT canonical_id, facility_id FROM registry_facilities
      )
      SELECT a.facility_id       AS facility_id,
             CAST(SUM(e.co_pub_count) AS DOUBLE) AS co_pubs,
             COUNT(*)            AS n_pairs
      FROM   registry_collaborations e
      JOIN   placed a ON a.canonical_id = e.canonical_id_a
      JOIN   placed b ON b.canonical_id = e.canonical_id_b
      WHERE  a.facility_id = b.facility_id
      GROUP  BY 1`,
  };

  const out = {};
  for (const [k, sql] of Object.entries(queries)) {
    const r = await conn.query(sql);
    out[k] = r.toArray().map((row) => unwrapRow(row.toJSON()));
  }

  // ── Index into the shapes the renderer wants ─────────────────────
  const byFacility = new Map();
  for (const r of out.roster) {
    r.works_count         = Number(r.works_count) || 0;
    r.cited_by_count      = Number(r.cited_by_count) || 0;
    r.h_index             = Number(r.h_index) || 0;
    r.lto_works_count     = Number(r.lto_works_count) || 0;
    r.tier_rank           = Number(r.tier_rank) || 0;
    r.graph_harvested     = !!r.graph_harvested;
    if (!byFacility.has(r.facility_id)) byFacility.set(r.facility_id, []);
    byFacility.get(r.facility_id).push(r);
  }
  // tier_rank ASC = better rank, so this is "most prominent first".
  for (const list of byFacility.values()) {
    list.sort((a, b) => a.tier_rank - b.tier_rank);
  }

  const collabsBy = new Map();
  for (const c of out.collabs) {
    c.co_pubs = Number(c.co_pubs) || 0;
    if (!collabsBy.has(c.cid)) collabsBy.set(c.cid, []);
    collabsBy.get(c.cid).push(c);
  }

  const siteEdges = out.site_edges
    .map((e) => ({ ...e, co_pubs: Number(e.co_pubs) || 0,
                   n_pairs: Number(e.n_pairs) || 0 }))
    .filter((e) => e.co_pubs >= SITE_LINK_MIN);

  const internalBy = new Map(out.site_internal.map((r) => [
    r.facility_id,
    { co_pubs: Number(r.co_pubs) || 0, n_pairs: Number(r.n_pairs) || 0 },
  ]));

  // Per-site rollup for the tooltip + the panel header.
  const siteSummary = new Map();
  for (const [fid, list] of byFacility.entries()) {
    let harvested = 0, ltoVolume = 0, maxH = 0, withEdges = 0;
    for (const r of list) {
      if (r.graph_harvested) harvested++;
      ltoVolume += r.lto_works_count;
      if (r.h_index > maxH) maxH = r.h_index;
      if ((collabsBy.get(r.canonical_id) || []).length) withEdges++;
    }
    siteSummary.set(fid, {
      n_registry: list.length,
      n_harvested: harvested,
      n_with_edges: withEdges,
      lto_volume: ltoVolume,
      max_h: maxH,
      internal: internalBy.get(fid) || null,
    });
  }

  // Domain-placed cohorts, keyed by region.
  const domainByArea = new Map();
  for (const r of out.domain_placed) {
    const people = (Array.isArray(r.people) ? r.people : []).map((p) => ({
      ...p,
      h_index: Number(p.h_index) || 0,
      lto_works: Number(p.lto_works) || 0,
    }));
    domainByArea.set(r.area_id, {
      area_id: r.area_id,
      n_people: Number(r.n_people) || people.length,
      people,
    });
  }

  const pt = out.placement_totals[0] || {};

  return {
    byFacility, collabsBy, siteEdges, siteSummary, domainByArea,
    totals: {
      n_placed: out.roster.length,
      n_sites: byFacility.size,
      n_site_edges: siteEdges.length,
      n_with_edges: collabsBy.size,
      // Placement accounting straight out of SQL.
      n_registry:  Number(pt.n_registry)  || 0,
      n_sited:     Number(pt.n_sited)     || 0,
      n_domain:    Number(pt.n_domain)    || 0,
      n_unplaced:  Number(pt.n_unplaced)  || 0,
      n_domain_regions: domainByArea.size,
    },
  };
}

// Kick off the registry fetch at most once. Concurrent callers (an
// impatient double-click on the toggle) share the same promise, so we
// never issue the queries twice or leave a half-populated _registry.
function ensureRegistry() {
  if (_registry) return Promise.resolve(_registry);
  if (!_registryPromise) {
    _registryPromise = fetchRegistry()
      .then((r) => { _registry = r; return r; })
      .catch((err) => { _registryPromise = null; throw err; });
  }
  return _registryPromise;
}


// ── Step 1: supergraph layout (squares packed by area weight) ───────
function buildSupergraph(data) {
  const areaIds = new Set(data.areas.map((a) => a.id));
  const facById = new Map(data.facilities.map((f) => [f.id, f]));
  const perById = new Map(data.people.map((p) => [p.id, p]));

  // Cross-area edge weights from facility-person + co-author edges.
  const edgeW = new Map();
  function bump(a, b, w) {
    if (!a || !b || a === b) return;
    if (!areaIds.has(a) || !areaIds.has(b)) return;
    const k = a < b ? `${a}|${b}` : `${b}|${a}`;
    edgeW.set(k, (edgeW.get(k) || 0) + w);
  }
  for (const e of data.fac_pers) {
    const f = facById.get(e.source); const p = perById.get(e.target);
    if (f && p) bump(f.area_id, p.area_id, e.w);
  }
  for (const e of data.coauthors) {
    const a = perById.get(e.source); const b = perById.get(e.target);
    if (a && b) bump(a.area_id, b.area_id, e.w);
  }

  return {
    nodes: data.areas.map((a) => ({
      id: a.id, name: a.name, weight: a.weight,
      // True cartogram: side ∝ sqrt(weight) so AREA ∝ weight.
      // Min side just keeps 1-facility areas visible at all zoom levels.
      side: Math.max(SUPERNODE_MIN, SUPERNODE_SCALE * Math.sqrt(a.weight)),
    })),
    edges: [...edgeW.entries()].map(([k, w]) => {
      const [s, t] = k.split('|');
      return { source: s, target: t, w };
    }),
  };
}

async function layoutSupergraph(d3, sg, w, h) {
  const cx = w / 2, cy = h / 2;
  // STAGE ASPECT. Collision and centring are isotropic, so left alone the
  // squares settle into a roughly round (in practice slightly portrait,
  // 0.76) cluster whatever shape the stage is — and a 1.7:1 landscape stage
  // then frames it with half its width empty. Every pass below is
  // therefore run in an aspect-normalised frame, u = (x-cx)/√ar,
  // v = (y-cy)·√ar, in which the target ellipse (rx = R·√ar, ry = R/√ar)
  // is a circle: the seed ring is that ellipse, forceX/forceY pull
  // harder vertically than horizontally on a landscape stage, and
  // compactInward ranks and steps by normalised distance. Clamped so a
  // freak stage (a collapsed panel) cannot produce a one-row layout.
  const ar = Math.max(0.5, Math.min(2.4, (w > 0 && h > 0) ? w / h : 1));
  const sar = Math.sqrt(ar);
  // Seed positions on a ring proportional to weight so the simulation
  // converges quickly and large groups end up roughly central.
  const sorted = [...sg.nodes].sort((a, b) => b.weight - a.weight);
  // Seed radius must scale with the AREA the squares need, not with the
  // viewport. A fixed 0.36*min(w,h) ring bore no relation to how much room
  // the squares actually require, which left the arrangement far looser
  // than a cartogram should be. Sizing the ring to sqrt(total square area)
  // starts it near the size they need, so the passes below have only local
  // work to do.
  //
  // Measured over the full pipeline (this seed -> the d3 force simulation
  // below -> recenter -> relax passes), fill = sum of square areas /
  // bounding-box area, on the shipped area weights with MODELLED area-area
  // edges: mean fill 0.219 -> 0.439 over five edge sets; 0.382 -> 0.477
  // (aspect 0.86 -> 0.82) on a single hand-built set. The real supergraph
  // edges come from a SQL query that was not reconstructed, so treat the
  // direction as reliable and the magnitudes as indicative.
  let _sumSq = 0;
  for (const n of sg.nodes) _sumSq += n.side * n.side;
  const maxR = Math.max(Math.sqrt(_sumSq) * 0.80, Math.min(w, h) * 0.18);
  sorted.forEach((n, i) => {
    const t = i / Math.max(sorted.length - 1, 1);
    const r = t * maxR * 0.85 + 0.05 * maxR;
    const a = i * (2 * Math.PI / Math.max(sorted.length, 6)) + 0.1 * i;
    n.x = cx + r * sar * Math.cos(a);
    n.y = cy + (r / sar) * Math.sin(a);
  });

  // Square-collision: forceCollide treats each node as a circle of
  // radius r; we set r = side/sqrt(2) + padding/2 so square bounding
  // boxes don't quite touch. Approximation but visually adequate.
  const sim = d3.forceSimulation(sg.nodes)
    .alphaDecay(0.04)
    .force('link', d3.forceLink(sg.edges)
      .id((d) => d.id)
      .distance((d) => 30 + Math.sqrt(d.w) * 8)
      .strength(0.4))
    .force('charge', d3.forceManyBody()
      .strength((d) => -120 - d.weight * 4))
    .force('collide', d3.forceCollide()
      .radius((d) => d.side * 0.71 + SUPER_PADDING)
      .strength(1)
      .iterations(2))
    .force('center', d3.forceCenter(cx, cy).strength(0.05))
    // Anisotropic gravity: on a landscape stage (ar > 1) the vertical pull
    // is ar² times the horizontal one, so the cluster spreads sideways.
    .force('x', d3.forceX(cx).strength(0.05 / ar))
    .force('y', d3.forceY(cy).strength(0.05 * ar))
    .stop();
  for (let i = 0; i < SUPERGRAPH_TICKS; i++) sim.tick();

  // After force-sim, the cluster of squares may have drifted away
  // from the stage centre. Recenter so the whole layout sits in the
  // middle of the viewport — otherwise the SVG viewBox (computed
  // from node positions later) ends up offset and the map renders
  // partly above the visible area on first paint.
  function recenter() {
    let mnX = Infinity, mnY = Infinity, mxX = -Infinity, mxY = -Infinity;
    for (const n of sg.nodes) {
      const half = n.side * 0.71;
      if (n.x - half < mnX) mnX = n.x - half;
      if (n.y - half < mnY) mnY = n.y - half;
      if (n.x + half > mxX) mxX = n.x + half;
      if (n.y + half > mxY) mxY = n.y + half;
    }
    const ccx = (mnX + mxX) / 2, ccy = (mnY + mxY) / 2;
    const dx = cx - ccx, dy = cy - ccy;
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
    for (const n of sg.nodes) { n.x += dx; n.y += dy; }
  }
  recenter();

  // Resolve remaining overlap, then COMPACT.
  //
  // The previous version of this pass only ever pushed squares apart, never
  // pulled them together, so any dispersal the seed ring introduced was
  // permanent — the main reason the map carried so much inter-region
  // whitespace. compactInward() adds the missing inward pass: walk the
  // outermost square toward the centroid, keeping each step only when it
  // introduces no overlap.
  //
  // separateSquares() additionally corrects how overlap is measured. The old
  // test compared centre distance against (sideA+sideB)/2, i.e. it treated
  // axis-aligned squares as circles, which is wrong for squares offset
  // diagonally. Resolving on the axis of LEAST overlap is correct for
  // squares. NOTE: this is a latent-correctness fix, NOT a fix for observed
  // overlap — the d3 forceCollide stage above already resolves overlap, and
  // no configuration was found in which the shipped pipeline left squares
  // overlapping. Do not expect a visible change from this part.
  //
  // Both passes are deterministic, so the layout remains stable across
  // reloads for a given input.
  const overlapsAny = (nodes, moveIdx, nx, ny) => {
    const m = nodes[moveIdx];
    for (let i = 0; i < nodes.length; i++) {
      if (i === moveIdx) continue;
      const o = nodes[i];
      const half = (m.side + o.side) * 0.5 + SUPER_PADDING * 0.5;
      if (Math.abs(nx - o.x) < half && Math.abs(ny - o.y) < half) return true;
    }
    return false;
  };

  function separateSquares(iters) {
    for (let r = 0; r < iters; r++) {
      let moved = false;
      for (let i = 0; i < sg.nodes.length; i++) {
        for (let j = i + 1; j < sg.nodes.length; j++) {
          const a = sg.nodes[i], b = sg.nodes[j];
          const dx = b.x - a.x, dy = b.y - a.y;
          const half = (a.side + b.side) * 0.5 + SUPER_PADDING;
          const ox = half - Math.abs(dx);
          const oy = half - Math.abs(dy);
          if (ox <= 0 || oy <= 0) continue;      // already clear on an axis
          if (ox <= oy) {
            const s = (dx >= 0 ? 1 : -1) * ox * 0.5;
            a.x -= s; b.x += s;
          } else {
            const s = (dy >= 0 ? 1 : -1) * oy * 0.5;
            a.y -= s; b.y += s;
          }
          moved = true;
        }
      }
      if (!moved) break;
    }
  }

  // Median square side: the size below which compactInward lets a square
  // slide round an obstacle (see there).
  const slideMaxSide = [...sg.nodes].map((n) => n.side).sort((a, b) => a - b)[
    Math.floor(sg.nodes.length / 2)] || 0;
  function compactInward(steps) {
    for (let s = 0; s < steps; s++) {
      let ccx = 0, ccy = 0;
      for (const n of sg.nodes) { ccx += n.x; ccy += n.y; }
      ccx /= sg.nodes.length; ccy /= sg.nodes.length;
      // Rank and step in the aspect-normalised frame (see the top of this
      // function): moving toward the centroid along (u, v) in that frame is
      // a world step of (u·√ar, v/√ar), so a landscape layout is pulled in
      // harder from above and below than from the sides.
      const nd = (n) => Math.hypot((n.x - ccx) / sar, (n.y - ccy) * sar);
      const order = [...sg.nodes.keys()].sort((i, j) =>
        nd(sg.nodes[j]) - nd(sg.nodes[i]));
      let any = false;
      for (const i of order) {
        const n = sg.nodes[i];
        const vu = (ccx - n.x) / sar, vv = (ccy - n.y) * sar;
        const d = Math.hypot(vu, vv);
        if (d < 1e-9) continue;
        const step = Math.max(d * 0.05, 0.5);
        const nx = n.x + (vu / d) * step * sar;
        const ny = n.y + (vv / d) * step / sar;
        if (!overlapsAny(sg.nodes, i, nx, ny)) { n.x = nx; n.y = ny; any = true; continue; }
        // Blocked head-on: a SMALL square may slide along one axis instead.
        // Without this a chain of small squares on the rim blocked itself —
        // each one stopped by the next — and after the aspect stretch it
        // trailed off the side of the map as a one-row tail. Large squares
        // do not slide: they carry the stretched outline, and letting them
        // slide too packed the map back to round (1.31 on a 1.77 stage).
        if (n.side > slideMaxSide) continue;
        if (Math.abs(nx - n.x) > 0.25 && !overlapsAny(sg.nodes, i, nx, n.y)) { n.x = nx; any = true; }
        else if (Math.abs(ny - n.y) > 0.25 && !overlapsAny(sg.nodes, i, n.x, ny)) { n.y = ny; any = true; }
      }
      if (!any) break;
    }
  }

  // The force terms alone do not get there: charge and collision dominate
  // the weak anisotropic gravity and the cluster still settles nearly
  // round (measured 0.76–0.9 whatever the stage). So stretch the settled
  // arrangement from ITS aspect to the stage's — x by √(ar/cur), y by the
  // inverse, about the centre, which keeps every square's neighbours and
  // only changes the gaps — then let separateSquares resolve the overlaps
  // the squeeze creates and compactInward close the gaps in the
  // normalised frame. Those two passes pull the aspect part of the way
  // back (two 700-unit squares cannot sit in a narrow column), so the
  // round is repeated until the layout is within ~10% of the stage aspect,
  // at most ASPECT_ROUNDS times. A single fixed √ar stretch overshot on a
  // portrait phone (0.43 for a 0.68 stage) and undershot at 1280 px.
  const layoutAspect = () => {
    let mnX = Infinity, mnY = Infinity, mxX = -Infinity, mxY = -Infinity;
    for (const n of sg.nodes) {
      const half = n.side / 2;
      if (n.x - half < mnX) mnX = n.x - half;
      if (n.x + half > mxX) mxX = n.x + half;
      if (n.y - half < mnY) mnY = n.y - half;
      if (n.y + half > mxY) mxY = n.y + half;
    }
    return (mxX - mnX) / Math.max(1e-9, mxY - mnY);
  };
  const ASPECT_ROUNDS = 4;
  for (let round = 0; round < ASPECT_ROUNDS; round++) {
    const cur = layoutAspect();
    if (round > 0 && Math.abs(Math.log(cur / ar)) < 0.1) break;
    const st = Math.sqrt(Math.max(0.25, Math.min(4, ar / (cur > 0 ? cur : 1))));
    if (Math.abs(st - 1) > 0.02) {
      for (const n of sg.nodes) {
        n.x = cx + (n.x - cx) * st;
        n.y = cy + (n.y - cy) / st;
      }
    }
    separateSquares(400);
    compactInward(300);
    separateSquares(200);   // guarantee: no overlap survives compaction
  }

  // One more recenter after the relax pass.
  recenter();

  return new Map(sg.nodes.map((n) => [n.id, n]));
}


// ── Step 2: per-group subgraph layout, scale to fit ─────────────────
function membersOfArea(areaId, data) {
  const facs = data.facilities.filter((f) => f.area_id === areaId)
    .map((f) => ({ id: f.id, name: f.name, kind: 'facility',
                   acronym: f.acronym, country: f.country, url: f.url,
                   f_type: f.f_type, area_id: areaId,
                   n_datasets: f.n_datasets || 0,
                   is_provider: f.is_provider || false }));
  const peo = data.people.filter((p) => p.area_id === areaId)
    .map((p) => {
      // Composite "importance" weight per the user's request:
      // prioritize funding + collaborators, then publications.
      // Coefficients chosen so a well-funded heavy collaborator (~$50M
      // facility, 30 co-authors, 50 pubs) lands around weight ≈ 18,
      // while a junior researcher (no funding, 0 co-authors, 5 pubs)
      // lands at ≈ 2.2 — both visible, but very different sizes.
      const fundM = (p.facility_funding_usd || 0) / 1e6;
      const w = 0.6 * Math.sqrt(p.n_pubs || 0)
              + 1.2 * Math.sqrt(p.n_coauth || 0)
              + 0.7 * Math.sqrt(fundM);
      return {
        id: p.id, name: p.name, kind: 'person',
        orcid: p.orcid, openalex_id: p.openalex_id,
        homepage_url: p.homepage_url, area_id: areaId,
        // layoutAndFit() places a person inside their institution's circle
        // by this id. It used to be dropped here, so every researcher on the
        // map fell through to the interstitial "no institution recorded"
        // placement (hollow dot, italic name) — 529 of 529 on the shipped
        // parquet, whatever facility_personnel said.
        primary_facility_id: p.primary_facility_id || null,
        n_pubs: p.n_pubs, n_coauth: p.n_coauth,
        total_citations: p.total_citations,
        facility_funding_usd: p.facility_funding_usd,
        importance: w,
      };
    });
  return [...facs, ...peo];
}

function intraEdgesOfArea(members, data) {
  const ids = new Set(members.map((m) => m.id));
  const edges = [];
  for (const e of data.fac_pers) {
    if (ids.has(e.source) && ids.has(e.target)) {
      edges.push({ source: e.source, target: e.target, w: e.w });
    }
  }
  for (const e of data.coauthors) {
    if (ids.has(e.source) && ids.has(e.target)) {
      edges.push({ source: e.source, target: e.target, w: e.w });
    }
  }
  return edges;
}

// Decoration anchors per area: invisible nodes that own Voronoi cells
// inside the area's square, ensuring the resulting merged polygon
// closely matches the square's area (cartogram-correct sizing) instead
// of letting cells leak into sparse neighbours. Tagged with the area
// id so polygon-clipping rolls them up; tagged kind='__decor' so the
// renderer skips them.
function decorationAnchors(square, areaId) {
  const cx = square.x, cy = square.y;
  const half = square.side / 2;
  const out = [];
  const N = DECOR_GRID;
  for (let i = 0; i < N; i++) {
    for (let j = 0; j < N; j++) {
      // Cell-center (i+0.5)/N spans 0..1; map to ±half.
      const fx = (i + 0.5) / N - 0.5;
      const fy = (j + 0.5) / N - 0.5;
      // Random jitter so the resulting cell boundaries are irregular,
      // not a visible grid pattern. PRNG seeded by (area,i,j) so the
      // layout is reproducible across re-renders.
      const seed = (areaId.charCodeAt(0) || 0) * 31 + i * 7 + j * 13;
      const jx = (((seed * 9301 + 49297) % 233280) / 233280 - 0.5) * 2;
      const jy = (((seed * 4391 + 12347) % 233280) / 233280 - 0.5) * 2;
      const x = cx + (fx + jx * DECOR_JITTER) * 2 * half;
      const y = cy + (fy + jy * DECOR_JITTER) * 2 * half;
      out.push({
        id: `__decor_${areaId}_${i}_${j}`,
        kind: '__decor',
        area_id: areaId,
        x, y,
      });
    }
  }
  return out;
}

// Positions for people the area holds but no facility circle in it does:
// people with no primary_facility_id at all, and people whose primary
// facility is drawn in a DIFFERENT area's square. They belong to this
// research area — that is what person_primary_groups says — but the map
// must not put them inside an institution, because no record says they
// are in one here.
//
// Built on the same gap region decorationAnchors() already samples: the
// jittered grid over the square. The difference is that these points are
// VISIBLE nodes, so they additionally have to (a) miss every facility
// circle by a margin and (b) sit far enough inside the square edge that
// the marker and its label are not clipped by the polygon boundary. So
// this rejects grid cells instead of emitting all of them, and falls back
// to a perimeter ring when the circles leave too few free cells.
//
// Deterministic: same jitter PRNG, same seeding scheme, no Math.random.
// The layout must not reshuffle between reloads (see the SEED_PHI note).
function interstitialSlots(square, circles, count) {
  const cx = square.x, cy = square.y;
  // Keep clear of the square edge by the same fraction the facility
  // packing insets by (innerR = 0.84 * half), so a gap person is never
  // drawn outside the region polygon after the Voronoi clip.
  const half = (square.side / 2) * 0.88;
  const out = [];
  if (count <= 0) return out;

  // Margin scales with the square: a small region's whole square can be
  // narrower than a fixed pixel margin, which would reject every cell.
  const clearance = Math.max(2, square.side * 0.012);
  const free = (x, y) => {
    for (const c of circles) {
      if (Math.hypot(x - c.x, y - c.y) < c.r + clearance) return false;
    }
    return true;
  };

  // Denser than DECOR_GRID because we are rejecting most cells: the grid
  // has to yield `count` survivors after the circles take their bite.
  // Grows with demand so a 16-person gap list still gets distinct slots.
  const N = Math.max(DECOR_GRID * 2, Math.ceil(Math.sqrt(count * 6)) + 2);
  const seedBase = (square.id.charCodeAt(0) || 0) * 31;
  for (let i = 0; i < N; i++) {
    for (let j = 0; j < N; j++) {
      const fx = (i + 0.5) / N - 0.5;
      const fy = (j + 0.5) / N - 0.5;
      const seed = seedBase + i * 7 + j * 13;
      const jx = (((seed * 9301 + 49297) % 233280) / 233280 - 0.5) * 2;
      const jy = (((seed * 4391 + 12347) % 233280) / 233280 - 0.5) * 2;
      const x = cx + (fx + jx * DECOR_JITTER / N * DECOR_GRID) * 2 * half;
      const y = cy + (fy + jy * DECOR_JITTER / N * DECOR_GRID) * 2 * half;
      if (Math.abs(x - cx) > half || Math.abs(y - cy) > half) continue;
      if (free(x, y)) out.push({ x, y });
    }
  }

  // Fallback: an area whose circles nearly fill the square (marine
  // ecosystems packs 72 of them) can starve the grid. Walk a golden-angle
  // ring inward from the square edge and take the first free points. If
  // even that starves — circles covering essentially everything — we place
  // the remainder ON the square's inner edge rather than inside a circle,
  // because a slightly crowded edge marker still tells the truth and a
  // marker inside a circle does not.
  const RING_PHI = Math.PI * (3 - Math.sqrt(5));
  for (let s = 0; out.length < count && s < count * 60; s++) {
    const a = (s + 1) * RING_PHI;
    // Sweep the radius over the outer 45% of the square, where the gap
    // between the packed circles (innerR = 0.84 * half) and the edge is.
    const frac = 0.98 - 0.45 * ((s % 9) / 8);
    const x = cx + half * frac * Math.cos(a);
    const y = cy + half * frac * Math.sin(a);
    if (Math.abs(x - cx) > half || Math.abs(y - cy) > half) continue;
    if (free(x, y)) out.push({ x, y });
  }
  // Last resort. If the grid AND the ring both starve, do NOT fall back to a
  // blind point on the square edge: measured on a synthetic 200-circle / 20 px
  // square (radii hit the 5 px floor, so the circles spill past the square
  // and neither sampler finds a free cell), a blind edge ring put 48 of 200
  // gap markers inside a facility circle even though 18.8% of the region was
  // free. Instead pick the point of MAXIMUM clearance from the circles over a
  // dense scan — the same "as far from any institution as this square allows"
  // rule, just searched rather than guessed. Successive picks perturb the
  // start index so repeated calls do not stack on one point.
  const clearanceAt = (x, y) => {
    let m = Infinity;
    for (const c of circles) {
      const d = Math.hypot(x - c.x, y - c.y) - c.r;
      if (d < m) m = d;
    }
    return m;
  };
  const M = 24;                      // 24 x 24 scan; 576 probes, negligible here
  while (out.length < count) {
    let bx = cx, by = cy, bc = -Infinity;
    const skew = out.length * 0.37;   // decorrelate consecutive picks
    for (let i = 0; i < M; i++) {
      for (let j = 0; j < M; j++) {
        const x = cx + (((i + 0.5 + skew) % M) / M - 0.5) * 2 * half;
        const y = cy + (((j + 0.5 + skew) % M) / M - 0.5) * 2 * half;
        // Penalise re-using a point another gap person already holds, so a
        // starved area spreads its markers instead of stacking them.
        let cl = clearanceAt(x, y);
        for (const o of out) {
          const d = Math.hypot(x - o.x, y - o.y);
          if (d < cl) cl = d;
        }
        if (cl > bc) { bc = cl; bx = x; by = y; }
      }
    }
    out.push({ x: bx, y: by });
  }
  if (out.length <= count) return out;

  // The grid scan above emits survivors in row-major order, so simply
  // taking the first `count` puts them in adjacent cells — measured on the
  // shipped parquet, the closest pair of gap markers came out 2.71 px apart
  // (mangroves, 3 people in a 34.8 px square), i.e. overlapping dots.
  // Farthest-point subsampling instead spreads them over the whole free
  // region: same measurement, 25.02 px. Deterministic (always seeded from
  // candidate 0, no randomness) and O(candidates × count), which at these
  // sizes — 16 people is the largest gap list in the data — is trivial.
  const picked = [out[0]];
  const dmin = out.map((c) => Math.hypot(c.x - out[0].x, c.y - out[0].y));
  dmin[0] = -1;      // the seed is taken; -1 excludes it from re-selection
  while (picked.length < count) {
    let bi = -1, bd = -1;
    for (let i = 0; i < out.length; i++) {
      if (dmin[i] > bd) { bd = dmin[i]; bi = i; }
    }
    if (bi < 0) break;
    picked.push(out[bi]);
    dmin[bi] = -1;                       // -1 marks "already taken"
    for (let i = 0; i < out.length; i++) {
      if (dmin[i] < 0) continue;
      const d = Math.hypot(out[i].x - out[bi].x, out[i].y - out[bi].y);
      if (d < dmin[i]) dmin[i] = d;
    }
  }
  return picked;
}

// Pack facility sub-circles inside an area's square, then scatter
// each facility's people inside the corresponding circle. Returns a
// flat list of (facility nodes + person nodes + decoration anchors)
// that the Voronoi step consumes. A side-effect map tracks each
// facility's circle position + radius so the renderer can draw the
// translucent sub-polygon ring per institution.
async function layoutAndFit(d3, members, edges, square, facCircles) {
  // Even an empty area gets decoration anchors so its polygon
  // still appears at the right cartogram size.
  if (!members.length) {
    return decorationAnchors(square, square.id);
  }

  const cx = square.x, cy = square.y;
  const facs = members.filter((m) => m.kind === 'facility');
  const peo  = members.filter((m) => m.kind === 'person');

  // ── 1. Pack facility sub-circles inside the square ──────────────
  // Each facility's "weight" = 1 (itself) + n_personnel-at-facility,
  // so an institution with many researchers gets a larger sub-circle.
  // Radius ∝ sqrt(weight) to make AREA ∝ weight.
  const peopleAt = new Map();
  for (const p of peo) {
    if (!p.primary_facility_id) continue;
    peopleAt.set(p.primary_facility_id,
      (peopleAt.get(p.primary_facility_id) || 0) + 1);
  }

  // If facility-list is empty (rare; can happen if all primary_area
  // facilities have no personnel listed), invent a single phantom
  // circle covering the whole square so people still get placed.
  const bubbles = facs.length
    ? facs.map((f) => ({
        id: f.id, name: f.name, acronym: f.acronym, country: f.country,
        f_type: f.f_type, url: f.url, area_id: f.area_id,
        n_datasets: f.n_datasets || 0,
        is_provider: f.is_provider || false,
        // Sub-circle weight now includes datasets produced, so a small
        // institution that ships data is not drawn smaller than a large
        // one that ships none.
        weight: 1 + (peopleAt.get(f.id) || 0)
                  + W_DATASET * (f.n_datasets || 0),
        kind: 'facility',
      }))
    : [{ id: `__phantom_${square.id}`, name: '', kind: 'facility',
         area_id: square.id, weight: 1 }];

  const totalWeight = bubbles.reduce((s, b) => s + Math.sqrt(b.weight), 0);
  const innerR = (square.side / 2) * 0.84;  // 16% inset from square edge
  // Per-bubble radius. Min 5 px so single-person facilities are visible;
  // max ~innerR so a giant institution can't dwarf the whole area.
  const RFAC = 0.62 * innerR / Math.max(totalWeight, 1);
  // Deterministic golden-angle seed rather than Math.random(). Two reasons:
  // the layout is now stable across reloads for a given input (it was not —
  // every refresh reshuffled the sub-circles), and a spiral seed is already
  // roughly evenly spread, so the relaxation below starts closer to its
  // converged state.
  const SEED_PHI = Math.PI * (3 - Math.sqrt(5));
  bubbles.forEach((b, i) => {
    b.r = Math.min(innerR * 0.65, Math.max(5, RFAC * Math.sqrt(b.weight) * 1.5));
    const t = (i + 0.5) / bubbles.length;
    const rr = Math.sqrt(t) * Math.max(innerR - b.r, 0);
    const aa = (i + 1) * SEED_PHI;
    b.x = cx + rr * Math.cos(aa);
    b.y = cy + rr * Math.sin(aa);
  });

  // A single bubble has nothing to relax against — no charge pair, no
  // collision pair — so the simulation is a 220-tick no-op that only pulls it
  // to the centre, which we can do directly. 9 of 21 areas are in this case
  // (7 with no facilities at all, using the phantom bubble; 2 with exactly
  // one), so this skips 1,980 ticks. Measured honestly: the whole bubble-sim
  // stage is only ~90 ms across all areas even at 72 bubbles, so this is NOT
  // the load-time fix — the sequential CREATE VIEW round-trips in db.js were.
  // It is here because a no-op simulation is still wrong to run.
  if (bubbles.length > 1) {
    const bubSim = d3.forceSimulation(bubbles)
      .alphaDecay(0.05)
      .force('center', d3.forceCenter(cx, cy).strength(0.08))
      .force('charge', d3.forceManyBody().strength(-12))
      .force('collide',
        d3.forceCollide().radius((d) => d.r + 1.6).strength(1).iterations(2))
      .stop();
    for (let i = 0; i < 220; i++) bubSim.tick();
  } else {
    bubbles[0].x = cx;
    bubbles[0].y = cy;
  }

  // Clamp every bubble back inside the inner circle (the simulation
  // doesn't enforce containment); push toward center if it's drifted
  // outside. A few iterations because pushing one bubble can shove
  // its neighbour out.
  for (let pass = 0; pass < 30; pass++) {
    let moved = false;
    for (const b of bubbles) {
      const dx = b.x - cx, dy = b.y - cy;
      const d = Math.hypot(dx, dy) || 1e-6;
      const overshoot = d + b.r - innerR;
      if (overshoot > 0) {
        const k = (innerR - b.r) / d;
        b.x = cx + dx * k;
        b.y = cy + dy * k;
        moved = true;
      }
    }
    // Also re-resolve overlap via simple push.
    for (let i = 0; i < bubbles.length; i++) {
      for (let j = i + 1; j < bubbles.length; j++) {
        const a = bubbles[i], b = bubbles[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const minD = a.r + b.r + 1.6;
        const d = Math.hypot(dx, dy) || 1e-6;
        if (d < minD) {
          const push = (minD - d) / 2;
          const nx = dx / d, ny = dy / d;
          a.x -= nx * push; a.y -= ny * push;
          b.x += nx * push; b.y += ny * push;
          moved = true;
        }
      }
    }
    if (!moved) break;
  }

  // Record the bubble layout in the side-effect map for the renderer.
  for (const b of bubbles) {
    facCircles.set(b.id, { x: b.x, y: b.y, r: b.r,
                            area_id: square.id,
                            name: b.name, acronym: b.acronym,
                            country: b.country, f_type: b.f_type,
                            url: b.url,
                            n_datasets: b.n_datasets || 0,
                            is_provider: b.is_provider || false,
                            n_people: peopleAt.get(b.id) || 0 });
  }

  // ── 2. Place each facility node at its bubble center; people inside ──
  for (const f of facs) {
    const b = facCircles.get(f.id);
    if (b) { f.x = b.x; f.y = b.y; }
  }
  // People scattered inside their primary facility's circle. Use a
  // golden-angle spiral so positions are deterministic. We extend the
  // spiral out toward the bubble's perimeter (88% radius) so people
  // don't crowd the centre, and the spacing scales with the bubble's
  // actual size so dense institutions get equally-spaced names.
  const PHI = Math.PI * (3 - Math.sqrt(5));   // golden angle

  // STEP 1: resolve each person to a bubble THAT EXISTS IN THIS AREA, or
  // to no bubble at all. Two things are deliberately different from the
  // previous version, and both were wrong-membership bugs:
  //
  //   (a) The lookup is against this area's own bubbles, not against the
  //       global facCircles map. facCircles is filled as buildLayout walks
  //       the areas in area_id order, so `facCircles.get(fid)` could return
  //       a circle sitting in a DIFFERENT area's square, and the person was
  //       then drawn there — outside their own region's polygon entirely.
  //       Measured on the shipped parquet: 48 of the 243 people that reach
  //       the layout have a primary facility whose own primary area is not
  //       the person's primary area, and 21 of those 48 resolved to a
  //       foreign square because that facility's area sorts earlier.
  //
  //   (b) There is no `|| facCircles.get(bubbles[0].id)` fallback. Falling
  //       back to the FIRST bubble in the area asserted an institutional
  //       membership the data does not record, for 38 people (11 with no
  //       facility_personnel row at all, plus the 27 off-area cases whose
  //       lookup missed). Showing nothing is better than showing a wrong
  //       affiliation; these people now go to the interstitial space below.
  const localBubbles = new Map(bubbles.map((b) => [b.id, b]));
  const inside = [];      // [{ p, b }] — person has an institution drawn here
  const gap = [];         // people this polygon holds but no circle here does
  for (const p of peo) {
    const fid = p.primary_facility_id;
    const b = fid ? localBubbles.get(fid) : null;
    if (b) { inside.push({ p, b }); continue; }
    // Kept as two separate flags because they are two different statements
    // and the renderer marks them differently: "no affiliation on record"
    // vs "affiliation on record, but that institution is drawn in another
    // region". Neither is "member of an institution in this region".
    p.unaffiliated = !fid;
    p.offAreaAffil = !!fid;
    gap.push(p);
  }

  // STEP 2: affiliated people spiral inside their own circle. The index k
  // and the count n now come from THE SAME pass over `inside`. That is the
  // fix for markers escaping their circle: k used to come from a counter
  // keyed on the bubble OBJECT while n came from peopleAt, keyed on the
  // facility ID, so for anyone reaching the bubbles[0] fallback the two
  // disagreed — k could exceed n, t = (k + 0.5) / n went above 1, and
  // r = b.r * 0.88 * sqrt(t) put the marker outside the circle the map
  // captions it as being inside.
  const nPerBubble = new Map();
  for (const rec of inside) nPerBubble.set(rec.b, (nPerBubble.get(rec.b) || 0) + 1);
  const kPerBubble = new Map();
  for (const rec of inside) {
    const p = rec.p, b = rec.b;
    const k = kPerBubble.get(b) || 0;
    kPerBubble.set(b, k + 1);
    const n = nPerBubble.get(b) || 1;
    // t is in (0, 1] by construction now. The clamp stays anyway: this
    // radius must never leave the circle, and a future edit to either
    // counter should degrade the spacing, not the containment.
    const t = Math.min(1, Math.max(0, (k + 0.5) / Math.max(n, 1)));
    const r = b.r * PERSON_R_FRAC * Math.sqrt(t);
    const a = (k + 1) * PHI;
    p.x = b.x + r * Math.cos(a);
    p.y = b.y + r * Math.sin(a);
  }
  // Hard containment invariant, independent of the arithmetic above: a
  // person the map places in an institution's circle is inside it. The
  // sub-circle IS the membership claim, so this is not cosmetic.
  for (const rec of inside) {
    const p = rec.p, b = rec.b;
    const dx = p.x - b.x, dy = p.y - b.y;
    const d = Math.hypot(dx, dy);
    const rMax = b.r * PERSON_R_FRAC;
    if (d > rMax && d > 0) {
      p.x = b.x + dx * (rMax / d);
      p.y = b.y + dy * (rMax / d);
    }
  }

  // STEP 3: everyone else goes in the interstitial space — inside the area
  // square, outside every facility circle. They read as "this region's
  // researcher, no institution recorded here", which is what the data says.
  //
  // Obstacles are the REAL facility circles only. The phantom bubble is not
  // an institution, so in a facility-less area there is nothing to avoid and
  // gap people may use the whole square; its stated purpose ("so people
  // still get placed") no longer applies now that nobody is placed in it.
  if (gap.length) {
    const obstacles = facs.length ? bubbles : [];
    const slots = interstitialSlots(square, obstacles, gap.length);
    for (let i = 0; i < gap.length; i++) {
      gap[i].x = slots[i].x;
      gap[i].y = slots[i].y;
    }
  }

  // ── 3. Append decoration anchors so Voronoi tiles the area square ──
  // Anchors live in the gap between facility bubbles + the square
  // perimeter. They share the area_id so the outer polygon stretches
  // to the full square; they do NOT carry a facility_id, so they
  // don't end up inside any facility's sub-polygon should we ever
  // compute one.
  return [...facs, ...peo, ...decorationAnchors(square, square.id)];
}


// ── Step 3: Voronoi-merged country-like polygons ────────────────────
//
// CARTOGRAM ENFORCEMENT: after merging Voronoi cells per area, we
// INTERSECT each merged polygon with its supernode-square (slightly
// inflated). This guarantees polygon area ≤ square area, so dense
// areas can never be visually smaller than sparse ones — the
// cartogram math the paper assumes is now actually enforced.
//
// Without this clip, Voronoi cells along the periphery extend
// outward toward the anchor ring, ballooning the polygons of outer
// (sparse) areas. We brought the anchor ring much closer in too
// (1.05 × bbox half-radius instead of 1.2 ×) so even uncliped
// versions stay tighter, but the intersection is the real fix.
async function computePolygons(d3delaunay, polygonClipping, allNodes,
                                squares, w, h) {
  const PC = polygonClipping.default || polygonClipping;

  // Bounding box of all node positions, with modest padding.
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of allNodes) {
    if (n.x < minX) minX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.x > maxX) maxX = n.x;
    if (n.y > maxY) maxY = n.y;
  }
  const padX = (maxX - minX) * PERIMETER_PAD + 30;
  const padY = (maxY - minY) * PERIMETER_PAD + 30;
  const bbMinX = minX - padX, bbMinY = minY - padY;
  const bbMaxX = maxX + padX, bbMaxY = maxY + padY;
  const bbW = bbMaxX - bbMinX, bbH = bbMaxY - bbMinY;

  // Perimeter anchor ring — close to the bounding box so outer cells
  // don't extend wildly. 1.05× max half-extent is just outside the
  // outermost real nodes.
  const cxA = (bbMinX + bbMaxX) / 2;
  const cyA = (bbMinY + bbMaxY) / 2;
  const ringR = Math.max(bbW, bbH) * 0.55;
  const anchors = [];
  for (let i = 0; i < PERIMETER_NODES; i++) {
    const a = (i / PERIMETER_NODES) * 2 * Math.PI;
    anchors.push({
      id: `__anchor_${i}`,
      kind: '__anchor',
      x: cxA + ringR * Math.cos(a),
      y: cyA + ringR * Math.sin(a),
    });
  }

  // Voronoi clip extent only slightly beyond the anchor ring.
  const all = [...allNodes, ...anchors];
  const points = all.map((n) => [n.x, n.y]);
  const delaunay = d3delaunay.Delaunay.from(points);
  const voronoi = delaunay.voronoi([
    cxA - ringR * 1.05, cyA - ringR * 1.05,
    cxA + ringR * 1.05, cyA + ringR * 1.05,
  ]);

  // Group cell indices by area_id (perimeter anchors excluded).
  const cellsByArea = new Map();
  for (let i = 0; i < all.length; i++) {
    const n = all[i];
    if (n.kind === '__anchor') continue;
    const cell = voronoi.cellPolygon(i);
    if (!cell) continue;
    const list = cellsByArea.get(n.area_id) || [];
    list.push(cell);
    cellsByArea.set(n.area_id, list);
  }

  // For each area: union its cells, then INTERSECT with the area's
  // supernode square (inflated by 12% so the intersection isn't
  // perfectly square — it preserves the irregular Voronoi boundary
  // wherever the cells stay inside the square). This is the
  // cartogram clamp.
  const result = new Map();
  for (const [area, cells] of cellsByArea.entries()) {
    if (!cells.length) continue;
    const square = squares.get(area);
    if (!square) continue;

    // Union all the area's Voronoi cells into one polygon.
    let merged;
    try {
      merged = PC.union(...cells.map((c) => [c]));
    } catch (e) {
      console.warn('[mvg] polygon union failed for', area, e);
      merged = [[cells[0]]];
    }

    // Build the cartogram clip — the supernode square inflated 12% so
    // adjacent areas can still touch and look glued together.
    const half = square.side * 0.5 * 1.12;
    const cx = square.x, cy = square.y;
    const clipBox = [
      [
        [cx - half, cy - half],
        [cx + half, cy - half],
        [cx + half, cy + half],
        [cx - half, cy + half],
        [cx - half, cy - half],
      ],
    ];

    // Intersect Voronoi-union with the clip square. polygon-clipping
    // returns a MultiPolygon — we keep the LARGEST resulting polygon
    // (in case the intersection broke into pieces, which can happen
    // when the area's nodes are spread far apart across the bbox).
    let clipped;
    try {
      clipped = PC.intersection(merged, [clipBox]);
    } catch (e) {
      console.warn('[mvg] polygon intersection failed for', area, e);
      clipped = merged;
    }

    let bestRing = null, bestArea = -Infinity;
    for (const poly of clipped) {
      if (!poly || !poly[0] || poly[0].length < 3) continue;
      const a = Math.abs(d3PolygonArea(poly[0]));
      if (a > bestArea) { bestArea = a; bestRing = poly[0]; }
    }
    if (bestRing) result.set(area, chaikin(bestRing, 1));
  }
  return { polygons: result, bbox: { x: bbMinX, y: bbMinY, w: bbW, h: bbH } };
}

// Shoelace area (positive only used for picking largest ring).
function d3PolygonArea(ring) {
  let a = 0;
  for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
    a += ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
  }
  return a / 2;
}

// One pass of Chaikin's corner-cutting smoothing. Each edge contributes
// two new vertices at 1/4 and 3/4 along it. Closes the ring naturally.
function chaikin(ring, passes = 1) {
  let pts = ring;
  if (pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]) {
    pts = pts.slice(0, -1);
  }
  for (let p = 0; p < passes; p++) {
    const out = [];
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const a = pts[i], b = pts[(i + 1) % n];
      out.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]]);
      out.push([0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]]);
    }
    pts = out;
  }
  pts.push(pts[0]);  // close the ring
  return pts;
}

// Vertex mean + bbox of a ring. The closing vertex duplicates the first,
// so it is skipped rather than counted twice.
function ringStats(ring) {
  let n = ring.length;
  if (n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1]) n--;
  let sx = 0, sy = 0;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = ring[i][0], y = ring[i][1];
    sx += x; sy += y;
    if (x < x0) x0 = x; if (y < y0) y0 = y;
    if (x > x1) x1 = x; if (y > y1) y1 = y;
  }
  if (!n) return { cx: 0, cy: 0, x0: 0, y0: 0, x1: 0, y1: 0, w: 0, h: 0 };
  return { cx: sx / n, cy: sy / n, x0, y0, x1, y1, w: x1 - x0, h: y1 - y0 };
}

// Pole of inaccessibility — the interior point farthest from the outline,
// i.e. the centre of the largest inscribed circle. Inline port of the
// grid-refinement algorithm in Mapbox's polylabel (Agafonkin, ISC), kept
// here rather than imported because it is ~40 lines and the map already
// waits on three CDN modules. Cells are refined only while they could
// still beat the best point by more than `precision` (default 0.5% of the
// polygon's larger side).
function polylabel(ring, precision) {
  const st = ringStats(ring);
  const size = Math.min(st.w, st.h);
  if (!(size > 0)) return { x: st.cx, y: st.cy, d: 0 };
  const prec = precision || Math.max(st.w, st.h) / 200;
  const cell = (x, y, half) => {
    const d = ringSignedDist(x, y, ring);
    return { x, y, half, d, max: d + half * Math.SQRT2 };
  };
  // Ascending by `max`, so pop() yields the most promising cell.
  const queue = [];
  const push = (c) => {
    let lo = 0, hi = queue.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (queue[m].max < c.max) lo = m + 1; else hi = m; }
    queue.splice(lo, 0, c);
  };
  const h0 = size / 2;
  for (let x = st.x0; x < st.x1; x += size) {
    for (let y = st.y0; y < st.y1; y += size) push(cell(x + h0, y + h0, h0));
  }
  let best = cell(st.cx, st.cy, 0);
  const boxC = cell(st.x0 + st.w / 2, st.y0 + st.h / 2, 0);
  if (boxC.d > best.d) best = boxC;
  while (queue.length) {
    const c = queue.pop();
    if (c.d > best.d) best = c;
    if (c.max - best.d <= prec) continue;
    const h = c.half / 2;
    push(cell(c.x - h, c.y - h, h)); push(cell(c.x + h, c.y - h, h));
    push(cell(c.x - h, c.y + h, h)); push(cell(c.x + h, c.y + h, h));
  }
  return { x: best.x, y: best.y, d: best.d };
}

// Signed distance from (x, y) to the ring outline: positive inside.
function ringSignedDist(x, y, ring) {
  let inside = false, minSq = Infinity;
  for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
    const a = ring[i], b = ring[j];
    if ((a[1] > y) !== (b[1] > y)
        && x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
    let px = a[0], py = a[1];
    const dx = b[0] - px, dy = b[1] - py;
    if (dx !== 0 || dy !== 0) {
      const t = ((x - px) * dx + (y - py) * dy) / (dx * dx + dy * dy);
      if (t > 1) { px = b[0]; py = b[1]; } else if (t > 0) { px += dx * t; py += dy * t; }
    }
    const ex = x - px, ey = y - py;
    const sq = ex * ex + ey * ey;
    if (sq < minSq) minSq = sq;
  }
  return (inside ? 1 : -1) * Math.sqrt(minSq);
}

// Length of the ring's interior chord through (x, y): horizontal when
// `horizontal`, else vertical. 0 when the point is outside.
function chordThrough(ring, x, y, horizontal) {
  const hits = [];
  const along = horizontal ? 1 : 0;      // coordinate the line is fixed in
  const across = horizontal ? 0 : 1;
  const v = horizontal ? y : x;
  for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
    const a = ring[i], b = ring[j];
    if ((a[along] > v) !== (b[along] > v)) {
      hits.push(a[across] + (v - a[along]) * (b[across] - a[across]) / (b[along] - a[along]));
    }
  }
  hits.sort((p, q) => p - q);
  const u = horizontal ? x : y;
  for (let i = 0; i + 1 < hits.length; i += 2) {
    if (hits[i] <= u && u <= hits[i + 1]) return hits[i + 1] - hits[i];
  }
  return 0;
}


// ── Wait for the stage to have a real size ──────────────────────────
async function waitForStage(stage) {
  for (let i = 0; i < 20; i++) {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (w > 0 && h > 0) return { w, h };
    await new Promise((r) => requestAnimationFrame(r));
  }
  return { w: stage.clientWidth || 1000, h: stage.clientHeight || 700 };
}


// ── Top-level layout ────────────────────────────────────────────────
async function buildLayout(data, w, h) {
  const d3 = await loadD3();
  const d3delaunay = await loadDelaunay();
  const polygonClipping = await loadPolygonClipping();

  const sg = buildSupergraph(data);
  const squares = await layoutSupergraph(d3, sg, w, h);

  // Per-area subgraph layout. Now hierarchical — facilities are
  // packed as sub-circles inside each area's square, and people sit
  // inside their primary facility's circle. The facCircles map is
  // populated as a side-effect for the renderer.
  const facCircles = new Map();
  const allNodes = [];
  for (const a of data.areas) {
    const square = squares.get(a.id);
    if (!square) continue;
    const members = membersOfArea(a.id, data);
    const edges = intraEdgesOfArea(members, data);
    const placed = await layoutAndFit(d3, members, edges, square, facCircles);
    allNodes.push(...placed);
  }

  const polyOut = await computePolygons(d3delaunay, polygonClipping,
                                         allNodes, squares, w, h);

  // Sub-Voronoi: each facility gets its own polygon territory inside
  // its area polygon. Replaces the dashed sub-circles. Computed by
  // running a small Voronoi over (facility centers + perimeter
  // anchors sampled along the area polygon edge), then clipping each
  // facility's cell to the area polygon via polygon-clipping
  // intersection so cells don't poke outside the country boundary.
  const facPolygons = computeFacilitySubPolygons(
    d3delaunay, polygonClipping,
    data, facCircles, polyOut.polygons,
  );

  // Cross-area edges for rendering (one row per pair, weight summed).
  const memberArea = new Map(allNodes.map((n) => [n.id, n.area_id]));
  const crossW = new Map();
  function edgeKey(s, t) { return s < t ? `${s}|${t}` : `${t}|${s}`; }
  function addCross(s, t, w) {
    if (!memberArea.has(s) || !memberArea.has(t)) return;
    if (memberArea.get(s) === memberArea.get(t)) return;
    const k = edgeKey(s, t);
    crossW.set(k, (crossW.get(k) || 0) + w);
  }
  for (const e of data.fac_pers) addCross(e.source, e.target, e.w);
  for (const e of data.coauthors) addCross(e.source, e.target, e.w);
  const crossEdges = [...crossW.entries()].map(([k, w]) => {
    const [s, t] = k.split('|');
    return { source: s, target: t, w };
  });

  // Area-label anchors: the pole of inaccessibility (the interior point
  // farthest from the outline), not the vertex mean. The vertex mean of a
  // Chaikin-smoothed Voronoi union is biased toward whichever side carries
  // the most vertices and can sit near an edge, which is exactly where a
  // name has the least room. Each anchor also carries the polygon's
  // horizontal and vertical chord through it (hw, vh) and its bbox: the
  // label pass tests "does this name fit HERE" against the chord, not the
  // bbox, so an L-shaped region is not credited with width it does not
  // have at the anchor row.
  const labels = new Map();
  const polyBBox = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
  for (const a of data.areas) {
    const ring = polyOut.polygons.get(a.id);
    if (!ring || ring.length < 4) continue;
    const st = ringStats(ring);
    if (st.x0 < polyBBox.x0) polyBBox.x0 = st.x0;
    if (st.y0 < polyBBox.y0) polyBBox.y0 = st.y0;
    if (st.x1 > polyBBox.x1) polyBBox.x1 = st.x1;
    if (st.y1 > polyBBox.y1) polyBBox.y1 = st.y1;
    const pole = polylabel(ring);
    labels.set(a.id, {
      x: pole.x, y: pole.y, name: a.name, weight: a.weight,
      hw: chordThrough(ring, pole.x, pole.y, true),
      vh: chordThrough(ring, pole.x, pole.y, false),
      x0: st.x0, y0: st.y0, bw: st.w, bh: st.h,
    });
  }

  // Institution sub-polygons: centroid (the facility dot and its label
  // anchor) and bbox, computed ONCE here. Three call sites used to recompute
  // the vertex mean independently.
  for (const sp of facPolygons.values()) {
    const st = ringStats(sp.ring || []);
    sp.cx = st.cx; sp.cy = st.cy; sp.bw = st.w; sp.bh = st.h;
  }

  return {
    polygons: polyOut.polygons,
    bbox: polyOut.bbox,
    // Bounding box of every area polygon — what the fit transform frames.
    // (bbox above is the padded NODE box the Voronoi used, which is larger.)
    polyBBox,
    nodes: allNodes,
    crossEdges,
    labels,
    areas: data.areas,
    facCircles,
    facPolygons,
    // Protected-area aggregate per region + the count of vocabulary terms
    // that carry no organisation, dataset or person and so have no polygon.
    protectedByArea: data.protectedByArea || new Map(),
    nAreasEmpty: data.n_areas_empty || 0,
  };
}


// ── Protected-area layer (opt-in, aggregate only) ───────────────────
// Protected areas are legitimate observatory context — 18 are catalogued
// on the shipped parquet — but they are not organisation units, so they
// do not count toward a region's organisation term and are not drawn as
// individual marks. This layer draws ONE chip per region stating the
// count and the split by jurisdiction, which is what an aggregate can
// honestly support.
function drawProtectedLayer(root) {
  if (_paChipSel) { _paChipSel.remove(); _paChipSel = null; }
  _paLabelSel = null;
  markLabelsDirty();
  if (!_showProtected || !_layout || !_layout.protectedByArea) return;

  const chips = [];
  for (const [areaId, agg] of _layout.protectedByArea.entries()) {
    const lab = _layout.labels.get(areaId);
    if (!lab || !agg || !agg.n_protected) continue;
    chips.push({
      area_id: areaId, x: lab.x, y: lab.y, ...agg,
      // Chip text is the count, not a name — the region name is already
      // rendered by the area-label class directly above it.
      display: `▤ ${agg.n_protected} protected`,
      // Sized within PA_LABEL_PX by how many protected areas the chip
      // stands for, so a region holding 1,800 of them reads louder than
      // one holding 3. This used to pin every chip at PA_LABEL_PX.min,
      // which left the declared .max dead and made a 10.0-12.0 range a
      // misleading way to write "always 10.0".
      __basePx: PA_LABEL_PX.min,
    });
  }
  if (!chips.length) return;
  // Ramp against the largest chip in this render, so the scale is relative
  // to what is actually on screen rather than to a hard-coded maximum.
  const paMax = chips.reduce((m, c) => Math.max(m, c.n_protected || 0), 0);
  for (const c of chips) {
    c.__basePx = rampPx(PA_LABEL_PX, c.n_protected || 0, paMax);
  }

  const g = root.append('g').attr('class', 'mvg-pa-chips');
  _paChipSel = g;
  // Anchored on the region-label point and offset BELOW it by a fixed
  // number of SCREEN px (see buildLabelCandidates). The offset used to be
  // 22 layout units, which is 5.8 px on screen at the old first paint, so
  // the chip landed on the region name; it now also goes through the
  // collision pass, so the two can never be drawn on top of each other.
  _paLabelSel = labelTexts(g.attr('pointer-events', 'none')
    .selectAll('text').data(chips).enter().append('text'),
  (d) => d.__basePx, HALO_PX.pa)
    .attr('fill', '#3f6212')
    .attr('stroke', '#f7fee7')
    .text((d) => d.display);
  markLabelsDirty();
}


// Sub-Voronoi: per area, partition the area's polygon into facility
// territories. Returns Map(facility_id → {ring, area_id, name,
// acronym, country, f_type, url, n_people}).
function computeFacilitySubPolygons(d3delaunay, polygonClipping,
                                     data, facCircles, areaRings) {
  const PC = polygonClipping.default || polygonClipping;
  const result = new Map();
  // Group facilities by area_id.
  const facsByArea = new Map();
  for (const f of data.facilities) {
    if (!facsByArea.has(f.area_id)) facsByArea.set(f.area_id, []);
    facsByArea.get(f.area_id).push(f);
  }
  // For each area, run a small Voronoi over facility positions plus
  // anchors sampled along the area polygon edge so cells stay bounded.
  for (const [areaId, areaRing] of areaRings.entries()) {
    const facs = facsByArea.get(areaId) || [];
    if (!facs.length || !areaRing || areaRing.length < 4) continue;
    // Bbox of the area polygon for the Voronoi clip extent.
    let mnX = Infinity, mnY = Infinity, mxX = -Infinity, mxY = -Infinity;
    for (const [x, y] of areaRing) {
      if (x < mnX) mnX = x; if (y < mnY) mnY = y;
      if (x > mxX) mxX = x; if (y > mxY) mxY = y;
    }
    const padW = (mxX - mnX) * 0.4 + 10;
    const padH = (mxY - mnY) * 0.4 + 10;
    // Collect facility seed points (their bubble centers).
    const seeds = [];
    const seedFids = [];
    for (const f of facs) {
      const c = facCircles.get(f.id);
      if (!c) continue;
      seeds.push([c.x, c.y]);
      seedFids.push(f.id);
    }
    if (!seeds.length) continue;
    // Sample 12-32 anchor points along the polygon perimeter to bound
    // the Voronoi cells; spaced proportionally to perimeter length.
    const peri = polygonPerimeter(areaRing);
    const nAnchors = Math.max(12, Math.min(32, Math.round(peri / 28)));
    const peripheryAnchors = samplePerimeter(areaRing, nAnchors);
    // Push anchors slightly OUTWARD so seed cells own the inner area.
    // (Compute centroid; nudge each anchor 6% further along the radius.)
    let cgx = 0, cgy = 0;
    for (const [x, y] of areaRing) { cgx += x; cgy += y; }
    cgx /= areaRing.length; cgy /= areaRing.length;
    for (const a of peripheryAnchors) {
      const dx = a[0] - cgx, dy = a[1] - cgy;
      a[0] = cgx + dx * 1.05;
      a[1] = cgy + dy * 1.05;
    }
    const allPts = [...seeds, ...peripheryAnchors];
    let voro;
    try {
      const dl = d3delaunay.Delaunay.from(allPts);
      voro = dl.voronoi([
        mnX - padW, mnY - padH, mxX + padW, mxY + padH,
      ]);
    } catch (e) {
      console.warn('[mvg] sub-voronoi delaunay failed for area', areaId, e);
      continue;
    }
    const areaPoly = [areaRing];   // polygon-clipping wants a Polygon (rings)
    for (let i = 0; i < seeds.length; i++) {
      const cell = voro.cellPolygon(i);
      if (!cell) continue;
      let clipped;
      try {
        clipped = PC.intersection([cell], [areaPoly]);
      } catch (e) {
        // If clipping fails, fall back to the unclipped cell.
        clipped = [[cell]];
      }
      // Pick the largest sub-polygon.
      let bestRing = null, bestArea = -Infinity;
      for (const poly of clipped) {
        if (!poly || !poly[0] || poly[0].length < 3) continue;
        const ar = Math.abs(d3PolygonArea(poly[0]));
        if (ar > bestArea) { bestArea = ar; bestRing = poly[0]; }
      }
      if (!bestRing) continue;
      const fid = seedFids[i];
      const meta = facCircles.get(fid) || {};
      result.set(fid, {
        ring: chaikin(bestRing, 1),
        area_id: areaId,
        name: meta.name, acronym: meta.acronym, country: meta.country,
        f_type: meta.f_type, url: meta.url, n_people: meta.n_people || 0,
        n_datasets: meta.n_datasets || 0,
        is_provider: meta.is_provider || false,
      });
    }
  }
  return result;
}

function polygonPerimeter(ring) {
  let p = 0;
  for (let i = 1; i < ring.length; i++) {
    p += Math.hypot(ring[i][0] - ring[i - 1][0],
                    ring[i][1] - ring[i - 1][1]);
  }
  return p;
}

function samplePerimeter(ring, n) {
  const peri = polygonPerimeter(ring);
  const step = peri / n;
  const out = [];
  let acc = 0;
  let next = step / 2;
  for (let i = 1; i < ring.length; i++) {
    const ax = ring[i - 1][0], ay = ring[i - 1][1];
    const bx = ring[i][0], by = ring[i][1];
    const segLen = Math.hypot(bx - ax, by - ay) || 1e-6;
    while (next <= acc + segLen) {
      const t = (next - acc) / segLen;
      out.push([ax + (bx - ax) * t, ay + (by - ay) * t]);
      next += step;
    }
    acc += segLen;
  }
  return out;
}


// ── Registry layer geometry + rendering ─────────────────────────────
//
// PERFORMANCE POSTURE, stated plainly. This layer never draws the whole
// registry:
//
//   * Only site-linked identities can be placed, and registry_facilities
//     ships EMPTY until the identity harvest lands — today that is zero
//     researcher markers, and the layer degrades to the domain-placed
//     cohort rings plus an honest status line.
//   * At rest the layer draws ONE ribbon per site pair, aggregated from
//     the researcher-level edges whose two endpoints both sit at
//     catalogued sites — nothing per-researcher.
//   * Individual researcher markers appear only for the ONE site the
//     user selects, capped at FOCUS_NODE_CAP=48; the side panel lists
//     everyone past the cap.
//
// So the marker count stays bounded regardless of how the registry
// grows. No canvas fallback or worker is needed at this size.

// Where on the map does a catalogued site live? Prefer the centroid of
// its facility sub-polygon (the same point the facility dot uses), fall
// back to its packed bubble centre. Returns null for sites that are not
// on the map at all — a registry link can point at a facility with no
// primary research area, which means no polygon and no position.
function siteAnchor(facilityId) {
  if (!_layout) return null;
  const sp = _layout.facPolygons && _layout.facPolygons.get(facilityId);
  if (sp && sp.ring && sp.ring.length) {
    return { x: sp.cx, y: sp.cy, meta: sp };
  }
  const c = _layout.facCircles && _layout.facCircles.get(facilityId);
  if (c) return { x: c.x, y: c.y, r: c.r, meta: c };
  return null;
}

// Radius available for scattering researcher markers inside a site's
// sub-polygon. Uses the smaller bbox half-extent so the spiral stays
// inside even for elongated Voronoi cells, and clamps to a sane range
// so a huge cell doesn't fling markers to its corners.
function siteScatterRadius(facilityId) {
  const sp = _layout && _layout.facPolygons && _layout.facPolygons.get(facilityId);
  if (sp && sp.ring && sp.ring.length) {
    let mnX = Infinity, mnY = Infinity, mxX = -Infinity, mxY = -Infinity;
    for (const [x, y] of sp.ring) {
      if (x < mnX) mnX = x; if (y < mnY) mnY = y;
      if (x > mxX) mxX = x; if (y > mxY) mxY = y;
    }
    const half = Math.min(mxX - mnX, mxY - mnY) / 2;
    return Math.max(8, Math.min(90, half * 0.78));
  }
  const c = _layout && _layout.facCircles && _layout.facCircles.get(facilityId);
  return c ? Math.max(8, c.r * 0.85) : 20;
}

// Deterministic golden-angle spiral placement inside the focused site.
// Same construction the people-inside-a-bubble layout already uses, so
// the two layers look like they belong to the same map.
function placeFocusNodes(facilityId, rows) {
  const a0 = siteAnchor(facilityId);
  if (!a0) return [];
  const R = siteScatterRadius(facilityId);
  const PHI = Math.PI * (3 - Math.sqrt(5));
  const n = rows.length;
  return rows.map((r, k) => {
    const t = (k + 0.5) / Math.max(n, 1);
    const rad = R * Math.sqrt(t);
    const ang = (k + 1) * PHI;
    return { ...r,
             x: a0.x + rad * Math.cos(ang),
             y: a0.y + rad * Math.sin(ang) };
  });
}

// Marker radius from LTO-related output volume. lto_works_count is an
// UPPER BOUND on distinct LTO-topic papers (OpenAlex lists a work under
// every topic it carries), so it is used only as a monotone size cue
// and is always labelled "LTO-related output volume", never "papers".
function registryRadius(d) {
  return 2.2 + Math.min(3.4, Math.sqrt(d.lto_works_count || 0) * 0.22);
}

function registryTipHtml(d) {
  const collabs = (_registry && _registry.collabsBy.get(d.canonical_id)) || [];
  const lines = [`<strong>${escapeHtml(d.display_name)}</strong>`];
  const sub = [d.affiliation_country, d.h_index ? `h-index ${d.h_index}` : null]
    .filter(Boolean).join(' · ');
  if (sub) lines.push(`<small>${escapeHtml(sub)}</small>`);
  if (d.lto_works_count) {
    lines.push(`<small style="color:#b45309">LTO-related output volume ≤ ${d.lto_works_count}`
      + (d.works_count ? ` of ${d.works_count} works` : '') + '</small>');
  }
  if (collabs.length) {
    // collabs is ordered by co_pubs DESC in SQL, so [0] is the strongest
    // edge. Naming the collaborator's institution is what makes the edge
    // legible — "who, and where" rather than a bare count.
    const top = collabs[0];
    const where = top.other_affiliation
      ? ` <span style="color:#64748b">at ${escapeHtml(top.other_affiliation)}</span>`
      : '';
    lines.push(`<small style="color:#0c4a6e">${collabs.length} registry co-author`
      + `${collabs.length === 1 ? '' : 's'}</small>`
      + `<br><small>strongest: ${escapeHtml(top.other_name || '?')}`
      + ` — ${top.co_pubs} co-publication${top.co_pubs === 1 ? '' : 's'}${where}</small>`);
  } else if (d.graph_harvested) {
    lines.push('<small style="color:#64748b">no registry co-authors found</small>');
  } else {
    // The honest distinction the caveats demand: this identity was
    // never part of the co-authorship harvest, so an empty edge list
    // means "not computed", not "publishes alone".
    lines.push('<small style="color:#92400e">co-authorship not yet computed '
      + 'for this identity</small>');
  }
  lines.push('<small style="color:#94a3b8">click for ORCID / profile</small>');
  return lines.join('<br>');
}

// Site ribbon tooltip: names both endpoints and is explicit that the
// weight is a summed pair count, not a paper count.
function siteLinkTipHtml(e) {
  const a = (_layout.facPolygons && _layout.facPolygons.get(e.source))
         || (_layout.facCircles && _layout.facCircles.get(e.source)) || {};
  const b = (_layout.facPolygons && _layout.facPolygons.get(e.target))
         || (_layout.facCircles && _layout.facCircles.get(e.target)) || {};
  const nm = (m, id) => escapeHtml(m.acronym || m.name || id);
  return '<strong>Co-publication between sites</strong>'
    + `<br>${nm(a, e.source)} ↔ ${nm(b, e.target)}`
    + `<br><small>${e.co_pubs} co-publication${e.co_pubs === 1 ? '' : 's'}`
    + ` across ${e.n_pairs} researcher pair${e.n_pairs === 1 ? '' : 's'}</small>`
    + '<br><small style="color:#94a3b8">click a site to list its researchers</small>';
}

// Draw (or redraw) everything the registry layer owns into _regRootG.
// The group itself is created once during render() at a fixed z
// position, so a focus change only swaps its children — no layer
// re-append, no z-order drift, no orphaned <g> left behind.
function drawRegistryLayer(d3, tip) {
  if (!_regRootG) return;
  _regRootG.selectAll('*').remove();
  _regSiteLinkSel = null;
  _regNodeSel = null;
  _regNodeLinkSel = null;
  _regLabelSel = null;
  _regDomainLabelSel = null;
  _markScaleApplied = 0;
  markLabelsDirty();
  if (!_showRegistry || !_registry || !_layout) return;

  // ── Site ↔ site ribbons (always on when the layer is on) ─────────
  const linkData = [];
  for (const e of _registry.siteEdges) {
    const a = siteAnchor(e.source);
    const b = siteAnchor(e.target);
    if (!a || !b) continue;          // one endpoint has no map position
    linkData.push({ ...e, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
  }
  if (linkData.length) {
    const maxW = Math.max(...linkData.map((e) => e.co_pubs));
    const g = _regRootG.append('g').attr('class', 'mvg-reg-links')
      .attr('fill', 'none');
    // Wide transparent hit line first, visible ribbon on top — same
    // two-layer pattern the cross-area edges use, so thin ribbons are
    // still hoverable.
    g.append('g')
      .attr('stroke', 'transparent').attr('stroke-width', 9)
      .attr('stroke-linecap', 'round')
      .style('pointer-events', 'stroke').style('cursor', 'help')
      .selectAll('line').data(linkData).enter().append('line')
      .attr('x1', (e) => e.x1).attr('y1', (e) => e.y1)
      .attr('x2', (e) => e.x2).attr('y2', (e) => e.y2)
      .on('mouseenter', (ev, e) => showTip(tip, ev, siteLinkTipHtml(e)))
      .on('mousemove', (ev, e) => showTip(tip, ev, siteLinkTipHtml(e)))
      .on('mouseleave', () => hideTip(tip));
    _regSiteLinkSel = g.append('g')
      .attr('stroke', NODE_COLORS.registryEdge)
      .attr('stroke-opacity', 0.5)
      .attr('stroke-linecap', 'round')
      .style('pointer-events', 'none')
      .selectAll('line').data(linkData).enter().append('line')
      .attr('x1', (e) => e.x1).attr('y1', (e) => e.y1)
      .attr('x2', (e) => e.x2).attr('y2', (e) => e.y2)
      .attr('stroke-width', (e) => 0.6 + 2.4 * Math.sqrt(e.co_pubs / maxW));
    _regSiteLinkSel.each(function (e) {
      e.__baseW = 0.6 + 2.4 * Math.sqrt(e.co_pubs / maxW);
    });
  }

  // ── Domain-placed cohorts: one badge per region ───────────────────
  // These researchers have NO site. The badge is drawn as a DASHED,
  // hollow ring at the region centroid — deliberately unlike the solid
  // filled site markers — with a "(no site)" caption, so a domain-placed
  // person can never be mistaken for someone located at a facility.
  const domainData = [];
  for (const [areaId, coh] of (_registry.domainByArea || new Map()).entries()) {
    const lab = _layout.labels.get(areaId);
    if (!lab || !coh.n_people) continue;
    domainData.push({ ...coh, area_id: areaId, x: lab.x, y: lab.y - 26,
                      area_name: lab.name || areaId });
  }
  if (domainData.length) {
    const maxN = Math.max(...domainData.map((d) => d.n_people));
    const domRadius = (d) => 5 + 7 * Math.sqrt(d.n_people / maxN);
    const g = _regRootG.append('g').attr('class', 'mvg-reg-domain');
    const rings = g.selectAll('circle').data(domainData).enter().append('circle')
      .attr('cx', (d) => d.x).attr('cy', (d) => d.y)
      .attr('r', domRadius)
      .attr('fill', 'none')
      .attr('stroke', NODE_COLORS.registry)
      .attr('stroke-width', 1.6)
      .attr('stroke-dasharray', '3,2.5')
      .style('cursor', 'pointer')
      .on('mouseenter', (ev, d) => showTip(tip, ev, domainCohortTipHtml(d)))
      .on('mouseleave', () => hideTip(tip))
      .on('click', (ev, d) => { ev.stopPropagation(); renderDomainPanel(d); });
    rings.each(function (d) { d.__baseR = domRadius(d); });
    // Caption. Its own text class, tiered with the protected-area chips
    // (region >= CONTEXT_MIN_POLY_PX on screen) — it annotates a region.
    // Anchored on the top of the ring; the label pass lifts it a few
    // screen px above. See buildLabelCandidates().
    for (const d of domainData) d.__basePx = PA_LABEL_PX.min;
    const caps = labelTexts(g.append('g').attr('pointer-events', 'none')
      .selectAll('text').data(domainData).enter().append('text'),
    (d) => d.__basePx, HALO_PX.reg)
      .attr('fill', NODE_COLORS.registry)
      .attr('stroke', '#fff7ed')
      .text((d) => `${d.n_people} no site`);
    _regDomainLabelSel = caps;
  } else {
    _regDomainLabelSel = null;
  }

  // ── Focused site: individual researcher markers ──────────────────
  if (!_focusFacility) { renderRegistryPanel(null); return; }
  const roster = _registry.byFacility.get(_focusFacility) || [];
  const shown = roster.length
    ? placeFocusNodes(_focusFacility, roster.slice(0, FOCUS_NODE_CAP))
    : [];
  if (!shown.length) {
    // Either the site has no registry links, or it has no position on
    // this map (a registry link can point at a facility with no primary
    // research area, hence no polygon). Either way: no markers, and the
    // panel must not keep showing the previous site's roster.
    renderRegistryPanel(null);
    return;
  }
  const posBy = new Map(shown.map((d) => [d.canonical_id, d]));

  // Researcher ↔ researcher edges for the focused set. Two cases:
  //   both endpoints in view → straight line between the two markers
  //   collaborator at another placed site → line to that site's anchor
  // Collaborators with no site link are NOT drawn (they have no
  // position); the panel reports how many were omitted.
  const nodeLinks = [];
  let offMapEdges = 0;
  for (const d of shown) {
    for (const c of (_registry.collabsBy.get(d.canonical_id) || [])) {
      const near = posBy.get(c.other);
      if (near) {
        // Draw each intra-focus pair once.
        if (d.canonical_id > c.other) continue;
        nodeLinks.push({ x1: d.x, y1: d.y, x2: near.x, y2: near.y,
                         co_pubs: c.co_pubs, kind: 'internal',
                         a: d.display_name, b: c.other_name });
      } else if (c.other_facility_id) {
        const anch = siteAnchor(c.other_facility_id);
        if (!anch) { offMapEdges++; continue; }
        nodeLinks.push({ x1: d.x, y1: d.y, x2: anch.x, y2: anch.y,
                         co_pubs: c.co_pubs, kind: 'external',
                         a: d.display_name, b: c.other_name });
      } else {
        offMapEdges++;
      }
    }
  }
  if (nodeLinks.length) {
    _regNodeLinkSel = _regRootG.append('g').attr('class', 'mvg-reg-node-links')
      .attr('fill', 'none')
      .attr('stroke', NODE_COLORS.registryEdge)
      .style('pointer-events', 'none')
      .selectAll('line').data(nodeLinks).enter().append('line')
      .attr('x1', (e) => e.x1).attr('y1', (e) => e.y1)
      .attr('x2', (e) => e.x2).attr('y2', (e) => e.y2)
      .attr('stroke-opacity', (e) => e.kind === 'internal' ? 0.55 : 0.28)
      .attr('stroke-dasharray', (e) => e.kind === 'external' ? '2,2' : null)
      .attr('stroke-width', (e) => 0.4 + Math.log(1 + e.co_pubs) * 0.28);
    _regNodeLinkSel.each(function (e) {
      e.__baseW = 0.4 + Math.log(1 + e.co_pubs) * 0.28;
    });
  }

  _regNodeSel = _regRootG.append('g').attr('class', 'mvg-reg-nodes')
    .selectAll('circle').data(shown).enter().append('circle')
    .attr('cx', (d) => d.x).attr('cy', (d) => d.y)
    .attr('r', registryRadius)
    .attr('fill', NODE_COLORS.registry)
    .attr('fill-opacity', 0.9)
    .attr('stroke', '#fff')
    .attr('stroke-width', 0.7)
    .style('cursor', 'pointer')
    .on('mouseenter', (ev, d) => showTip(tip, ev, registryTipHtml(d)))
    .on('mouseleave', () => hideTip(tip))
    .on('click', (ev, d) => { ev.stopPropagation(); openRegistryProfile(d); });
  _regNodeSel.each(function (d) { d.__baseR = registryRadius(d); });

  // Researcher NAME LABELS at the focused site. These are the only
  // registry names drawn on the map, and only once the site's sub-polygon
  // is >= PERSON_MIN_FACPOLY_PX on screen: at the fit zoom a site is a few
  // dozen pixels across and 48 names would be unreadable regardless of
  // size.
  const maxH = Math.max(1, ...shown.map((d) => d.h_index || 0));
  for (const d of shown) d.__basePx = rampPx(REG_LABEL_PX, d.h_index || 0, maxH);
  _regLabelSel = labelTexts(_regRootG.append('g').attr('class', 'mvg-reg-labels')
    .attr('pointer-events', 'none')
    .selectAll('text').data(shown).enter().append('text'),
  (d) => d.__basePx, HALO_PX.reg)
    .attr('fill', '#7c2d12')
    .attr('stroke', '#fff7ed')
    .text((d) => shortName(d.display_name));
  markLabelsDirty();

  renderRegistryPanel(roster, shown.length, offMapEdges);
}

// Click-through for a registry researcher. Registry rows are keyed on
// canonical_id, not people.person_id, so the People directory route
// only works for the minority that carry a person_id. Everyone else
// gets their ORCID (or OpenAlex) profile, which is the identifier the
// registry is actually built on.
function openRegistryProfile(d) {
  if (!d) return;
  if (d.person_id) {
    location.hash = `#/people/${encodeURIComponent(d.person_id)}`;
    return;
  }
  const url = d.orcid ? `https://orcid.org/${d.orcid}`
            : d.openalex_id ? `https://openalex.org/${d.openalex_id}`
            : d.homepage_url || null;
  if (url) window.open(url, '_blank', 'noopener');
}

// Drop the revealed-edge subset and take it out of the DOM. Module-level
// so the non-render() call sites (the registry panel's Clear button) can
// reach it without duplicating the two-line dance, and so it is a no-op
// rather than a crash when there is no live SVG to redraw into.
function clearNodeSelection() {
  if (!_selectedNodeId) return;
  _selectedNodeId = null;
  if (_redrawEdgeReveal) _redrawEdgeReveal();
}

// Focus a site (or clear focus with null) and redraw only the registry
// layer. Cheap enough to call on every click — it touches one <g>.
function setFocusFacility(facilityId) {
  _focusFacility = (_focusFacility === facilityId) ? null : facilityId;
  if (!_d3Mod) return;
  drawRegistryLayer(_d3Mod, ensureTooltip());
  onZoom(_zoomK);
  if (!_focusFacility) renderRegistryPanel(null);
}

// Side panel listing the focused site's roster. Shows every linked
// researcher — including the ones past FOCUS_NODE_CAP that have no
// marker — so the cap never silently hides people.
function renderRegistryPanel(roster, nDrawn, offMapEdges) {
  const panel = _container && _container.querySelector('#net-reg-panel');
  if (!panel) return;
  if (!roster || !roster.length || !_focusFacility) {
    panel.hidden = true;
    panel.innerHTML = '';
    return;
  }
  const meta = (_layout.facPolygons && _layout.facPolygons.get(_focusFacility))
            || (_layout.facCircles && _layout.facCircles.get(_focusFacility)) || {};
  const sum = _registry.siteSummary.get(_focusFacility) || {};
  const title = escapeHtml(meta.acronym || meta.name || _focusFacility);
  const rows = roster.map((r, i) => {
    const collabs = _registry.collabsBy.get(r.canonical_id) || [];
    const badge = collabs.length
      ? `<span class="mvg-reg-badge">${collabs.length}</span>`
      : (r.graph_harvested
          ? '<span class="mvg-reg-badge is-zero" title="Harvested — no registry co-authors found">0</span>'
          : '<span class="mvg-reg-badge is-unknown" title="Co-authorship not yet computed for this identity">–</span>');
    return `<li class="${i < nDrawn ? '' : 'is-unplotted'}">
      <button type="button" class="mvg-reg-row" data-cid="${escapeHtml(r.canonical_id)}">
        <span class="mvg-reg-name">${escapeHtml(r.display_name)}</span>
        ${badge}
      </button></li>`;
  }).join('');
  const capNote = roster.length > nDrawn
    ? `<p class="mvg-reg-note">${nDrawn} of ${roster.length} plotted on the map;
       the rest are listed here.</p>`
    : '';
  // n_with_edges counts researchers holding at least one edge, which is NOT
  // the same as "co-authorship computed": a harvested researcher can be
  // computed and still have zero edges inside the registry. n_harvested is
  // the coverage figure; n_with_edges is the result. Reporting them
  // separately keeps the badge legend ("–" means not harvested) honest.
  const edgeNote = sum.n_with_edges != null
    ? `<p class="mvg-reg-note">${sum.n_harvested} of ${roster.length} have
       co-authorship computed; ${sum.n_with_edges} hold at least one link here.
       <span class="mvg-reg-badge is-unknown">–</span>
       means not yet harvested, not zero.</p>`
    : '';
  const offNote = offMapEdges
    ? `<p class="mvg-reg-note">${offMapEdges} co-author link${offMapEdges === 1 ? '' : 's'}
       point outside the catalogued sites and are not drawn.</p>`
    : '';
  panel.hidden = false;
  panel.innerHTML = `
    <div class="mvg-reg-head">
      <h3>${title}</h3>
      <button type="button" id="net-reg-clear" class="btn-ghost">Clear</button>
    </div>
    <p class="mvg-reg-note">${roster.length} core-tier researcher${roster.length === 1 ? '' : 's'}
      linked by ROR match${sum.internal
        ? ` · ${sum.internal.co_pubs} co-publications among them` : ''}</p>
    ${capNote}${edgeNote}${offNote}
    <ol class="mvg-reg-list">${rows}</ol>`;
  // Clear drops BOTH selections the map can be holding: the focused site
  // (which owns this panel) and the revealed edge subset. They are set by
  // different gestures — shift-click focuses a site, plain click reveals a
  // node's edges — but "Clear" is the only always-visible reset in the UI,
  // so it must not leave edges on screen with nothing on the page
  // explaining what they belong to.
  panel.querySelector('#net-reg-clear')
    .addEventListener('click', () => { clearNodeSelection(); setFocusFacility(null); });
  panel.querySelectorAll('.mvg-reg-row').forEach((btn) => {
    btn.addEventListener('click', () => {
      const r = roster.find((x) => x.canonical_id === btn.dataset.cid);
      if (r) openRegistryProfile(r);
    });
  });
}


// ── Render ─────────────────────────────────────────────────────────
async function render() {
  const statusEl = _container.querySelector('#net-status');
  const stage = _container.querySelector('#net-stage');
  if (!stage) return;
  try {
    const { w, h } = await waitForStage(stage);
    statusEl.textContent = 'Loading data…';
    const d3 = await loadD3();
    _d3Mod = d3;
    if (!_layout) {
      // One fetch + layout at a time: a route revisit or a layer toggle
      // while the database is still starting must not start a second one.
      if (!_layoutPromise) {
        _layoutPromise = (async () => {
          const data = await fetchData();
          statusEl.textContent = 'Computing knowledge map (this takes 5-10 s)…';
          return buildLayout(data, w, h);
        })().finally(() => { _layoutPromise = null; });
      }
      _layout = await _layoutPromise;
    }
    updateStatus();

    stage.innerHTML = '';
    // VIEWPORT. The viewBox is the stage itself in CSS px (0 0 w h), so one
    // SVG unit is one CSS pixel and the d3.zoom scale k IS the world→screen
    // scale. The first view is a zoom TRANSFORM that frames the bounding box
    // of every polygon (fitTransform), recomputed whenever the stage
    // changes size.
    //
    // This replaced a viewBox cropped to the "weighted core" — the polygons
    // holding 80% of the weight, plus 8% — under preserveAspectRatio meet.
    // That crop cut the outer regions off at the bottom of the stage (4 of
    // 38 polygons clipped at 1600 px), kept the layout's portrait aspect so
    // half a landscape stage stayed empty, and made k relative to a box
    // whose size depended on the window, so the zoom bands that keyed off k
    // fired at a different on-screen scale on every display.
    _stageW = stage.clientWidth || w;
    _stageH = stage.clientHeight || h;
    // Every label element is about to be replaced.
    _shownEls = new Set();
    _labelCands = null;
    const svg = d3.select(stage).append('svg')
      .attr('viewBox', `0 0 ${_stageW} ${_stageH}`)
      .attr('preserveAspectRatio', 'xMidYMid meet')
      .attr('class', 'mvg-svg');
    const root = svg.append('g').attr('class', 'mvg-root');
    _rootG = root;

    // d3.zoom — captured so the TOC + polygon clicks can call it. The zoom
    // handler itself only moves the root group; labels and marks are
    // re-evaluated in a requestAnimationFrame-throttled pass (at most once
    // per frame) plus one final pass when the gesture ends. The old handler
    // re-sized and re-culled every label synchronously on every wheel event
    // (10–123 ms each).
    const zoom = d3.zoom()
      .on('zoom', (ev) => {
        root.attr('transform', ev.transform);
        _zoomT = ev.transform;
        _zoomK = ev.transform.k;
        // A sourceEvent means a person did this (wheel, drag, pinch); a
        // programmatic zoom.transform has none.
        if (ev.sourceEvent) _userZoomed = true;
        scheduleLabelPass();
      })
      .on('end', () => onZoom());
    _zoomBehavior = zoom;
    _zoomSvg = svg;
    applyZoomExtents();
    svg.call(zoom);
    // Double-click on the map frames everything again (d3's default
    // double-click zooms in 2x, which nobody needs with a wheel and a TOC).
    svg.on('dblclick.zoom', null);
    svg.on('dblclick.mvgfit', (ev) => { ev.preventDefault(); resetToFit(true); });
    // First view: everything. A re-render (layer toggle) keeps the view
    // the user had, as long as they had moved it.
    if (_userZoomed && _zoomT) svg.call(zoom.transform, _zoomT);
    else svg.call(zoom.transform, _fitT);
    observeStage(stage);

    const tip = ensureTooltip();

    // Layer 1: polygons
    const areaList = _layout.areas;
    const colorOf = new Map(areaList.map((a, i) => [a.id, AREA_PALETTE[i % AREA_PALETTE.length]]));
    _colorOf = colorOf;
    const polyG = root.append('g').attr('class', 'mvg-polys');
    // Region outlines are drawn with a NON-SCALING stroke, i.e. in screen
    // px: a 1.4-unit world stroke was a 0.35 px hairline at the overview
    // and a 4 px bar at 8x. The pinned (asked-for) region gets a heavier
    // outline and fill — see applyAreaHighlight().
    _polySel = polyG.selectAll('path').data(areaList).enter().append('path')
      .attr('d', (a) => {
        const ring = _layout.polygons.get(a.id);
        return ring ? `M${ring.map((p) => p.join(',')).join('L')}Z` : '';
      })
      .attr('fill', (a) => colorOf.get(a.id))
      .attr('fill-opacity', AREA_FILL_OPACITY)
      .attr('stroke', (a) => colorOf.get(a.id))
      .attr('stroke-opacity', 0.9)
      .attr('stroke-width', AREA_STROKE_PX)
      .attr('vector-effect', 'non-scaling-stroke')
      .style('cursor', 'pointer')
      .on('mouseenter', function (ev, a) {
        d3.select(this).attr('fill-opacity', 0.32);
        const lab = _layout.labels.get(a.id);
        if (lab) showTip(tip, ev, areaTipHtml(a));
      })
      .on('mouseleave', function (ev, a) {
        d3.select(this).attr('fill-opacity', a.id === _pinnedAreaId
          ? AREA_FILL_OPACITY_PINNED : AREA_FILL_OPACITY);
        hideTip(tip);
      })
      .on('click', (ev, a) => zoomToArea(a.id));

    // Layer 1.5: facility SUB-POLYGONS inside each area polygon.
    // Each institution gets its own Voronoi territory, clipped to its
    // area polygon. Fill-opacity NOW VARIES BY PERSONNEL COUNT — the
    // bigger the institution (more researchers mapped here), the
    // stronger the fill — so adjacent sub-polygons are visually
    // distinguishable instead of all reading as the same shade.
    if (_showFacility && _layout.facPolygons && _layout.facPolygons.size) {
      const facData = [..._layout.facPolygons.entries()]
        .map(([id, p]) => ({ id, ...p }));
      // Map n_people → fill-opacity. Range 0.06–0.24 so even tiny
      // institutions register without large ones blasting saturation.
      const maxPeople = Math.max(1, ...facData.map((d) => d.n_people || 0));
      const baseOpacity = (d) => {
        const t = Math.sqrt((d.n_people || 0) / maxPeople); // sqrt-damped
        return 0.06 + t * 0.18;
      };
      _facPolySel = root.append('g').attr('class', 'mvg-facpolys')
        .selectAll('path').data(facData).enter().append('path')
        .attr('d', (d) => d.ring
          ? `M${d.ring.map((p) => p.join(',')).join('L')}Z`
          : '')
        .attr('fill', (d) => colorOf.get(d.area_id) || '#94a3b8')
        .attr('fill-opacity', baseOpacity)
        .attr('stroke', (d) => colorOf.get(d.area_id) || '#64748b')
        .attr('stroke-opacity', 0.7)
        .attr('stroke-width', 0.6)
        .style('cursor', 'pointer');
      _facPolySel.each(function (d) { d.__baseOpacity = baseOpacity(d); });
      _facPolySel
        .on('mouseenter', function (ev, d) {
          // Bump THIS polygon, dim the others in the same area so the
          // hovered institution + its people stand out within the
          // country.
          d3.select(this).attr('fill-opacity', Math.min(0.45, (d.__baseOpacity || 0.1) * 2.5));
          if (_facPolySel) {
            _facPolySel.filter((o) => o !== d && o.area_id === d.area_id)
              .attr('fill-opacity', (o) => (o.__baseOpacity || 0.1) * 0.45);
          }
          showTip(tip, ev, facilityCircleTipHtml(d));
        })
        .on('mouseleave', function () {
          if (_facPolySel) {
            _facPolySel.attr('fill-opacity', (o) => o.__baseOpacity || 0.1);
          }
          hideTip(tip);
        })
        .on('click', (ev, d) => {
          // The sub-polygon IS the institution's territory, so clicking it
          // selects the same node the facility dot at its centroid does —
          // the dot is a ~4 px target and the polygon is the forgiving
          // version of it. Same modifier convention as the dot handler
          // below: plain click reveals that facility's incident edges,
          // shift-click keeps the two historical destinations
          // ("show me who works here" with the registry layer on, the
          // site's website with it off).
          //
          // toggleNodeSelection is declared further down in this same
          // function scope; it is initialised long before any click can
          // fire, so the forward reference is safe.
          ev.stopPropagation();
          if (ev.shiftKey) {
            if (_showRegistry) { setFocusFacility(d.id); return; }
            if (d.url) window.open(d.url, '_blank', 'noopener');
            return;
          }
          toggleNodeSelection(d.id);
        });
    } else {
      _facPolySel = null;
    }

    // Layer 2: cross-area edges — CLICK TO REVEAL, nothing at rest.
    //
    // These used to be drawn in full at every paint. drawEdges emits TWO
    // <line> elements per edge (see its comment), so the shipped 80
    // cross-area pairs put 160 line elements across the middle of the map
    // before the user had asked for a single one, and the cartogram the
    // whole layout exists to communicate was read as a hairball. The edge
    // set is now scoped to ONE selected node: click a facility, a
    // researcher dot or a researcher label to reveal its incident edges,
    // click it again / click the background / press Escape to remove them.
    //
    // The three visibility buckets below are UNCHANGED and still do the
    // same job — they keep an edge from dangling into an invisible node:
    //   - facility ↔ facility       → Facilities ON
    //   - person ↔ facility         → BOTH ON  (person-bridging that
    //                                  terminates on a facility dot)
    //   - person ↔ person           → People ON
    // Previously a person↔facility edge was bucketed as "person" and
    // kept showing after Facilities was toggled off, leaving ghost
    // lines pointing at hidden facility dots.
    const nodeIdx = new Map(_layout.nodes.map((n) => [n.id, n]));
    const edgeKind = (e) => {
      const a = nodeIdx.get(e.source); const b = nodeIdx.get(e.target);
      const ak = a ? a.kind : null; const bk = b ? b.kind : null;
      if (ak === 'person' && bk === 'person') return 'pp';
      if (ak === 'person' || bk === 'person') return 'pf';
      return 'ff';
    };
    // Incident-edge index: node id → every cross-area edge that touches
    // it. Built once per paint (80 edges on the shipped parquet, so the
    // cost is nil) so a click never walks the whole edge list, and so the
    // reveal cannot accidentally become O(edges) per mousedown if the
    // graph grows.
    const incident = new Map();
    for (const e of _layout.crossEdges) {
      if (!incident.has(e.source)) incident.set(e.source, []);
      incident.get(e.source).push(e);
      if (!incident.has(e.target)) incident.set(e.target, []);
      incident.get(e.target).push(e);
    }
    // Container for the revealed subset. Appended HERE, at the z position
    // the three edge groups used to occupy, so revealed edges still paint
    // BELOW the facility dots, person dots and labels that follow. Its
    // children are created and destroyed by redrawEdgeReveal() below; it
    // is empty at first paint.
    const edgeRevealG = root.append('g').attr('class', 'mvg-edge-reveal');
    // Area-id → display name lookup for the edge tooltip.
    const areaName = new Map(_layout.areas.map((a) => [a.id, a.name]));
    // Tooltip HTML for an edge — describes the two endpoints, the
    // research areas they bridge, and the underlying weight (the
    // count of facility-personnel + co-author connections that
    // collapsed into this single line).
    const edgeTipHtml = (e, kind) => {
      const a = nodeIdx.get(e.source) || {};
      const b = nodeIdx.get(e.target) || {};
      const aArea = areaName.get(a.area_id) || a.area_id || '';
      const bArea = areaName.get(b.area_id) || b.area_id || '';
      const labelKind = kind === 'pp' ? 'Co-authorship'
                      : kind === 'pf' ? 'Researcher ↔ Facility'
                      :                  'Facility ↔ Facility';
      const aLine = `${escapeHtml(a.name || a.id || '?')} <small style="color:#64748b">(${a.kind || '?'}, ${escapeHtml(aArea)})</small>`;
      const bLine = `${escapeHtml(b.name || b.id || '?')} <small style="color:#64748b">(${b.kind || '?'}, ${escapeHtml(bArea)})</small>`;
      const wLabel = kind === 'pp' ? `${e.w} co-publication${e.w === 1 ? '' : 's'}`
                   : kind === 'pf' ? `${e.w} shared author${e.w === 1 ? '' : 's'} / appointment${e.w === 1 ? '' : 's'}`
                   :                  `${e.w} shared connection${e.w === 1 ? '' : 's'}`;
      return `<strong>${labelKind}</strong>`
           + `<br>${aLine}`
           + `<br>${bLine}`
           + `<br><small style="color:#0c4a6e">bridges <em>${escapeHtml(aArea)}</em> ↔ <em>${escapeHtml(bArea)}</em></small>`
           + `<br><small>${wLabel}</small>`;
    };
    // Draws TWO line layers per bucket: an invisible wide "hit"
    // line for hover precision (thin strokes are otherwise nearly
    // impossible to hover with a mouse), and the visible coloured
    // line on top. Hover handlers live on the hit line.
    // Appends into edgeRevealG rather than root: the group is wiped on
    // every selection change, which is what removes revealed edges from
    // the DOM instead of merely hiding them.
    const drawEdges = (cls, arr, stroke, opacity, baseW, kind) => {
      if (!arr.length) return;
      const g = edgeRevealG.append('g').attr('class', cls).attr('fill', 'none');

      // Invisible hit line — wide, transparent, clickable.
      g.append('g').attr('class', `${cls}-hit`)
        .attr('stroke', 'transparent')
        .attr('stroke-width', 8)
        .attr('stroke-linecap', 'round')
        .style('pointer-events', 'stroke')
        .style('cursor', 'help')
        .selectAll('line').data(arr).enter().append('line')
        .attr('x1', (e) => (nodeIdx.get(e.source) || {}).x)
        .attr('y1', (e) => (nodeIdx.get(e.source) || {}).y)
        .attr('x2', (e) => (nodeIdx.get(e.target) || {}).x)
        .attr('y2', (e) => (nodeIdx.get(e.target) || {}).y)
        .on('mouseenter', function (ev, e) {
          showTip(tip, ev, edgeTipHtml(e, kind));
          // Highlight the matching VISIBLE line so the user can see
          // which one they're inspecting.
          const idx = arr.indexOf(e);
          d3.select(this.parentNode.parentNode)
            .select(`g.${cls}-vis`).selectAll('line')
            .attr('stroke-opacity', (_, i) => i === idx ? Math.min(1, opacity * 3) : opacity);
        })
        .on('mousemove', function (ev, e) { showTip(tip, ev, edgeTipHtml(e, kind)); })
        .on('mouseleave', function () {
          hideTip(tip);
          d3.select(this.parentNode.parentNode)
            .select(`g.${cls}-vis`).selectAll('line')
            .attr('stroke-opacity', opacity);
        });

      // Visible coloured line — pointer-events none so the wide hit
      // line below it owns the cursor interactions.
      g.append('g').attr('class', `${cls}-vis`)
        .attr('stroke', stroke)
        .attr('stroke-opacity', opacity)
        .style('pointer-events', 'none')
        .selectAll('line').data(arr).enter().append('line')
        .attr('x1', (e) => (nodeIdx.get(e.source) || {}).x)
        .attr('y1', (e) => (nodeIdx.get(e.source) || {}).y)
        .attr('x2', (e) => (nodeIdx.get(e.target) || {}).x)
        .attr('y2', (e) => (nodeIdx.get(e.target) || {}).y)
        .attr('stroke-width', (e) => baseW + Math.log(1 + e.w) * 0.3);
    };
    // Wipe the reveal group and rebuild it for whatever _selectedNodeId
    // currently is. Called on every selection change and re-entrant by
    // design: selectAll('*').remove() takes the previous subset OUT of the
    // DOM, so with no selection this layer costs exactly zero elements
    // rather than a set of opacity-0 lines still being hit-tested.
    //
    // The three bucket calls below keep the ORIGINAL gating verbatim, so
    // the People / Facilities toggles still decide what may be revealed:
    // a pf edge needs BOTH layers on (its endpoints are one of each), ff
    // needs Facilities, pp needs People. An edge whose far endpoint is a
    // hidden node kind therefore still cannot appear — the same ghost-line
    // bug the buckets were introduced for.
    const redrawEdgeReveal = () => {
      edgeRevealG.selectAll('*').remove();
      if (!_selectedNodeId) return;
      const mine = incident.get(_selectedNodeId);
      if (!mine || !mine.length) return;
      const sub = { ff: [], pf: [], pp: [] };
      for (const e of mine) {
        const k = edgeKind(e);
        if (sub[k]) sub[k].push(e);
      }
      // Same class names, colours, opacities and widths as before, so the
      // revealed lines read identically to the old always-on layer and
      // any CSS keyed on mvg-edges-* still applies. drawEdges installs the
      // hit-line + tooltip pair, so edgeTipHtml hover works on the
      // revealed subset unchanged.
      if (_showFacility) drawEdges('mvg-edges-ff', sub.ff, '#94a3b8', 0.18, 0.35, 'ff');
      if (_showFacility && _showPerson) drawEdges('mvg-edges-pf', sub.pf, '#7dd3fc', 0.30, 0.45, 'pf');
      if (_showPerson) drawEdges('mvg-edges-pp', sub.pp, '#0ea5e9', 0.55, 0.6, 'pp');
    };
    // Publish the closure so the node click handlers further down, the
    // background/Escape clear, and the registry panel's Clear button can
    // all drive the same single code path.
    _redrawEdgeReveal = redrawEdgeReveal;

    // A selection surviving from the previous paint must be re-validated:
    // "Recompute layout" and the People/Facilities toggles both re-enter
    // render(), and a node id that is no longer in _layout.nodes (or whose
    // kind is now hidden) would leave a selection that can never be
    // cleared by clicking the node again, because the node is not there to
    // click. Drop it rather than carry a dangling reference.
    if (_selectedNodeId) {
      const selNode = nodeIdx.get(_selectedNodeId);
      const kindVisible = selNode
        && ((selNode.kind === 'person' && _showPerson)
            || (selNode.kind === 'facility' && _showFacility));
      if (!kindVisible) _selectedNodeId = null;
    }
    redrawEdgeReveal();

    // Toggle selection for a node datum. Clicking the selected node again
    // clears it, which is the "click the same node again" affordance; any
    // other node moves the selection. Only one node is ever selected, so
    // the DOM never holds more than that node's incident edges.
    const toggleNodeSelection = (id) => {
      _selectedNodeId = (_selectedNodeId === id) ? null : id;
      redrawEdgeReveal();
      // Deliberately NO onZoom() call. Cross-area edge stroke-widths are
      // world-space (baseW + log(1+w)*0.3) and were never counter-scaled
      // by onZoom even when this layer was always on — only the registry
      // ribbons are. Revealed edges keep that behaviour so a reveal looks
      // the same as the old layer did at the same zoom.
    };

    // Researcher dots and researcher name labels share this handler.
    // Plain click = reveal that person's incident edges (and clear on a
    // second click); shift-click = the previous behaviour, navigate to
    // their card in the People directory. Both marks are small targets
    // and a stray click used to change route, which made exploring the
    // map hostile; the reveal has to be the default gesture and the
    // navigation the deliberate one.
    const onNodeClick = (ev, d) => {
      if (!d || !d.id) return;
      ev.stopPropagation();
      if (ev.shiftKey) { onPersonClick(d); return; }
      toggleNodeSelection(d.id);
    };

    // Background click clears the selection. Bound on the SVG (not the
    // stage div) so it fires for the parchment between polygons; the
    // polygon path itself has its own click handler that calls
    // zoomToArea, and clicking a polygon is not "clicking a node", so it
    // should also drop the edge subset — hence the clear lives here and
    // catches the bubbled polygon click too. Node handlers below call
    // ev.stopPropagation() so their own click does not immediately
    // undo itself via this listener.
    //
    // DRAG GUARD. d3.zoom pans on mousedown-drag, and the browser still
    // fires a 'click' on mouseup at the end of that gesture. Without a
    // guard, panning the map to look at the revealed edges would clear
    // them. So record where the pointer went down and only treat the
    // click as a deliberate background click if it barely moved. 4 px is
    // the usual click-vs-drag threshold and is well under the distance
    // any intentional pan covers.
    //
    // Named 'click.mvgclear' / 'mousedown.mvgclear' so this registration
    // can never displace another unnamed listener on the same element,
    // and so svg.call(zoom)'s own typenames stay untouched.
    const CLICK_SLOP_PX = 4;
    let downX = 0, downY = 0;
    svg.on('mousedown.mvgclear', (ev) => { downX = ev.clientX; downY = ev.clientY; });
    svg.on('click.mvgclear', (ev) => {
      if (!_selectedNodeId) return;
      if (Math.hypot(ev.clientX - downX, ev.clientY - downY) > CLICK_SLOP_PX) return;
      _selectedNodeId = null;
      redrawEdgeReveal();
    });

    // Escape clears the selection. Bound to the document once per page,
    // NOT once per render(): render() re-enters on both node toggles and
    // on "Recompute layout", so binding here without the guard would stack
    // one listener per toggle for the lifetime of the tab. The listener
    // reads the module-level _redrawEdgeReveal rather than closing over
    // this paint's redrawEdgeReveal, so it always drives the LIVE SVG
    // instead of a detached one from a superseded paint.
    if (!_escBound) {
      _escBound = true;
      document.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Escape') return;
        if (!_selectedNodeId) return;
        _selectedNodeId = null;
        if (_redrawEdgeReveal) _redrawEdgeReveal();
      });
    }

    // Layer 3: nodes. Researchers now render as NAME LABELS (top-N
    // per area by composite importance) so the map looks like the
    // UArizona KMap reference image. Lower-importance researchers
    // still get small dots so they're not invisible. Facilities stay
    // as small dots at their bubble centres.
    //
    // Top-N per area is computed from the composite weight set in
    // membersOfArea(). Font-size scales by sqrt(importance) so the
    // most-prominent name is biggest.
    const facNodes = _layout.nodes.filter((n) => n.kind === 'facility');
    const perNodes = _layout.nodes.filter((n) => n.kind === 'person');

    // Bucket people by area; pick the top N labels per area.
    const PER_AREA_LABEL_LIMIT = 14;
    const personByArea = new Map();
    for (const p of perNodes) {
      if (!personByArea.has(p.area_id)) personByArea.set(p.area_id, []);
      personByArea.get(p.area_id).push(p);
    }
    const labelledIds = new Set();
    for (const list of personByArea.values()) {
      list.sort((a, b) => (b.importance || 0) - (a.importance || 0));
      for (const p of list.slice(0, PER_AREA_LABEL_LIMIT)) labelledIds.add(p.id);
    }

    if (_showFacility) {
      // When facility sub-polygons exist, place each facility's dot at
      // its sub-polygon centroid (the cleanest "this institution lives
      // here" marker). When sub-polygons are absent (small or
      // single-facility areas) fall back to the force-sim x,y. Either
      // way, dots are intentionally smaller than the person dots so
      // they read as "place markers" not data points.
      const facCentroid = (d) => {
        const sp = _layout.facPolygons && _layout.facPolygons.get(d.id);
        if (!sp || !sp.ring || sp.ring.length === 0) return [d.x, d.y];
        return [sp.cx, sp.cy];
      };
      _dotFacSel = root.append('g').attr('class', 'mvg-fac-dots')
        .selectAll('circle').data(facNodes).enter().append('circle')
        .attr('cx', (d) => facCentroid(d)[0])
        .attr('cy', (d) => facCentroid(d)[1])
        .attr('r', 2.6)
        .attr('fill', NODE_COLORS.facility)
        .attr('fill-opacity', 0.85)
        .attr('stroke', '#fff')
        .attr('stroke-width', 0.6)
        .style('cursor', 'pointer')
        .on('mouseenter', (ev, d) => showTip(tip, ev, nodeTipHtml(d)))
        .on('mouseleave', () => hideTip(tip))
        .on('click', (ev, d) => {
          // A facility dot is a NODE, so a plain click now reveals its
          // incident cross-area edges instead of navigating away — the
          // map is unreadable if every click leaves the page. stopPropagation
          // keeps the svg background handler from clearing the selection
          // this click just made.
          //
          // The two pre-existing destinations are preserved but demoted to
          // modifier-clicks, because a click that opens a new tab and a
          // click that reveals edges cannot share the same gesture:
          //   * registry layer on → shift-click focuses the site roster
          //     (what setFocusFacility did on a plain click);
          //   * otherwise        → shift-click opens the site's homepage.
          ev.stopPropagation();
          if (ev.shiftKey) {
            if (_showRegistry) { setFocusFacility(d.id); return; }
            const url = d.url || d.homepage_url;
            if (url) window.open(url, '_blank', 'noopener');
            return;
          }
          toggleNodeSelection(d.id);
        });
      // An archive-linked site gets a visibly larger marker: the map is
      // meant to emphasise data. On the shipped parquet 374 of 445
      // catalogued facilities hold an archive edge, so here the SMALL
      // marker is the signal — a site with no archive edge recorded yet.
      // onZoom counter-scales from this base.
      _dotFacSel
        .attr('r', (d) => (d.is_provider ? 4.2 : 2.6))
        .attr('stroke', (d) => (d.is_provider ? '#f8fafc' : '#fff'))
        .attr('stroke-width', (d) => (d.is_provider ? 1.1 : 0.6));
      _dotFacSel.each(function (d) {
        d.__baseR = d.is_provider ? 4.2 : 2.6;
      });
    } else {
      _dotFacSel = null;
    }

    if (_showPerson) {
      // Small dots for non-labelled people. Radius now scales with
      // composite importance (sqrt-damped) so junior researchers stay
      // readable at ~1.6 px while heavy-collab/well-funded researchers
      // sit at ~3.5 px before their name kicks in. Stroke-width also
      // scales so the white halo doesn't dominate the small dots.
      // EVERY researcher gets a dot, including the top-N who also carry a
      // name label: names are now shown only when there is room on screen
      // (see the label tiers), and a labelled-only researcher whose name is
      // hidden would otherwise have no mark at all. The label sits just
      // above its dot.
      const dotPeople = perNodes;
      const dotRadius = (d) => {
        const w = d.importance || 0;
        return 1.6 + Math.min(2.2, Math.sqrt(w) * 0.55);
      };
      // A person the layout could not put inside an institution drawn in
      // this region gets a HOLLOW marker: no fill, the person colour as a
      // dashed outline. The filled dot means "inside this institution's
      // circle"; a hollow one has to look different or the map still reads
      // as asserting a membership. Dashed rather than merely unfilled so the
      // distinction survives at the ~2 px sizes these dots sit at.
      const isGap = (d) => !!(d.unaffiliated || d.offAreaAffil);
      _dotPersonSel = root.append('g').attr('class', 'mvg-per-dots')
        .selectAll('circle').data(dotPeople).enter().append('circle')
        .attr('class', (d) => (isGap(d) ? 'mvg-per-dot mvg-per-dot-gap' : 'mvg-per-dot'))
        .attr('cx', (d) => d.x).attr('cy', (d) => d.y)
        .attr('r', dotRadius)
        .attr('fill', (d) => (isGap(d) ? 'none' : NODE_COLORS.person))
        .attr('fill-opacity', 0.75)
        .attr('stroke', (d) => (isGap(d) ? NODE_COLORS.person : '#fff'))
        .attr('stroke-width', (d) => (isGap(d) ? 0.9 : 0.5))
        .attr('stroke-dasharray', (d) => (isGap(d) ? '1.6 1.2' : null))
        // A hollow (fill:none) circle only takes pointer events on its
        // dashed outline by default; 'all' makes its whole disc clickable,
        // like the filled dots.
        .attr('pointer-events', 'all')
        .style('cursor', 'pointer')
        .on('mouseenter', (ev, d) => showTip(tip, ev, nodeTipHtml(d)))
        .on('mouseleave', () => hideTip(tip))
        // Click reveals this researcher's incident edges (edge-on-demand);
        // shift-click keeps the old navigation to #/people/<id>.
        .on('click', (ev, d) => onNodeClick(ev, d));
      // Tag base radius so onZoom can counter-scale per-dot. __gapDot is
      // cached on the datum for the same reason: onZoom re-derives the
      // outline and must not re-run the classification.
      _dotPersonSel.each(function (d) {
        d.__baseR = dotRadius(d);
        d.__gapDot = isGap(d);
      });

      // Name labels for the top N per area, sized in SCREEN px within
      // PERSON_LABEL_PX (floor 10.0 px, above LABEL_MIN_PX). Shown only once
      // the researcher's institution is PERSON_MIN_FACPOLY_PX across on
      // screen — see buildLabelCandidates().
      const labelPeople = perNodes.filter((p) => labelledIds.has(p.id));
      const maxImportance = Math.max(1, ...labelPeople.map((d) => d.importance || 0));
      for (const d of labelPeople) {
        d.__basePx = rampPx(PERSON_LABEL_PX, d.importance || 0, maxImportance);
        d.__italic = isGap(d);
      }
      _labelSel = labelTexts(root.append('g').attr('class', 'mvg-per-labels')
        .selectAll('text').data(labelPeople).enter().append('text'),
      (d) => d.__basePx, HALO_PX.person, 500)
        // Named people in the interstitial space are italicised for the same
        // reason their dot is hollow: a label sitting in the gap between two
        // institutions would otherwise read as belonging to whichever circle
        // it happens to land nearest.
        .attr('font-style', (d) => (d.__italic ? 'italic' : null))
        .attr('fill', '#0c4a6e')
        .attr('stroke', '#fff')
        .style('cursor', 'pointer')
        .text((d) => shortName(d.name))
        .on('mouseenter', (ev, d) => showTip(tip, ev, nodeTipHtml(d)))
        .on('mouseleave', () => hideTip(tip))
        .on('click', (ev, d) => onNodeClick(ev, d));
    } else {
      _labelSel = null;
      _dotPersonSel = null;
    }

    // Layer 3.4: REGISTRY layer container. Appended once, last, so a focus
    // change only swaps this group's children. stage.innerHTML = '' above
    // already discarded the previous SVG, so the stale selections must be
    // dropped before we repopulate.
    //
    // Paint order: SVG has no z-index, so document order decides. This group
    // is appended after the person-label group and therefore paints ABOVE
    // those labels, not below them. That is the intended reading for the
    // ribbons and site markers — they are the layer the user just switched
    // on — but it does mean a marker can occlude a person label beneath it.
    // Do not "fix" this by reordering without checking the ribbons still
    // read against the cartogram fill.
    _regSiteLinkSel = null;
    _regNodeSel = null;
    _regNodeLinkSel = null;
    _regRootG = root.append('g').attr('class', 'mvg-registry');
    if (_showRegistry) {
      if (_registry) {
        drawRegistryLayer(d3, tip);
      } else {
        // Data not in yet (first switch-on races the first paint).
        // Fetch, then draw into the group we just created — but only if
        // the layer is still on and the group is still the live one.
        const g = _regRootG;
        ensureRegistry().then(() => {
          if (_showRegistry && _regRootG === g) {
            drawRegistryLayer(d3, tip);
            onZoom(_zoomK);
            updateStatus();
          }
        }).catch((err) => {
          console.error('[mvg] registry layer failed', err);
          const s = _container.querySelector('#net-reg-note');
          if (s) s.textContent = 'Researcher layer unavailable — registry query failed.';
        });
      }
    } else {
      renderRegistryPanel(null);
    }

    // Layer 3.5: FACILITY NAME LABELS. Shown once the institution's sub-
    // polygon is big enough on screen to hold its name (FAC_MIN_POLY_PX,
    // FAC_LABEL_FIT), then culled against every other label class. Anchored
    // on the facility dot and lifted just above it, so a name no longer
    // covers the mark it names. Font sized by people + datasets.
    if (_showFacility && _layout.facPolygons && _layout.facPolygons.size) {
      // Label weight = people here + datasets produced, so a data provider
      // is labelled ahead of a similarly-staffed site that ships nothing
      // (the collision pass ranks organisations by this weight).
      const facLabWeight = (sp) =>
        (sp.n_people || 0) + W_DATASET * (sp.n_datasets || 0);
      const facLabMax = Math.max(1, ...[..._layout.facPolygons.values()]
        .map(facLabWeight));
      const displayOf = facilityDisplayNames(_layout.facPolygons);
      const facLabData = [..._layout.facPolygons.entries()].map(([id, sp]) => ({
        id, x: sp.cx, y: sp.cy, bw: sp.bw, bh: sp.bh,
        display: displayOf.get(id), name: sp.name, acronym: sp.acronym,
        area_id: sp.area_id,
        weight: facLabWeight(sp),
        // Base radius of this facility's dot (see the dot layer above), so
        // the label can sit clear of it at every zoom.
        __dotR: sp.is_provider ? 4.2 : 2.6,
        // SCREEN px, floor FAC_LABEL_PX.min = 10.5. The old range was 7–11
        // SVG units and rendered 4.9–7.0 px over most of the zoom range.
        __basePx: rampPx(FAC_LABEL_PX, facLabWeight(sp), facLabMax),
      }));
      _facLabelSel = labelTexts(root.append('g').attr('class', 'mvg-fac-labels')
        .attr('pointer-events', 'none')
        .selectAll('text').data(facLabData).enter().append('text'),
      (d) => d.__basePx, HALO_PX.fac)
        .attr('fill', '#0f172a')
        .attr('stroke', '#fef9f0')
        .text((d) => d.display);
    } else {
      _facLabelSel = null;
    }

    // Populate the left-hand TOC of research areas (clickable to zoom).
    populateToc();

    // Layer 4: polygon (research area) labels, drawn above everything
    // else. Each region has a one-line <text> and, when its name has a
    // space, a two-line one; the label pass shows at most one of them, at
    // full or small size, or neither (see buildLabelCandidates).
    const labelG = root.append('g').attr('class', 'mvg-labels')
      .attr('pointer-events', 'none');
    const areaMaxW = Math.max(1, ...areaList.map((a) => a.weight || 0));
    const areaLabData = areaList
      .filter((a) => _layout.labels.has(a.id))
      .map((a) => {
        const lab = _layout.labels.get(a.id);
        return {
          id: a.id, name: lab.name, x: lab.x, y: lab.y, lab,
          weight: a.weight || 0,
          lines: splitTwoLines(lab.name),
          // SCREEN px within AREA_LABEL_PX, sized by the data-and-people
          // weight, so the biggest name belongs to the region carrying the
          // most observatories, datasets and people.
          __basePx: rampPx(AREA_LABEL_PX, a.weight || 0, areaMaxW),
        };
      });
    const areaText = (sel) => labelTexts(sel, (d) => d.__basePx, HALO_PX.area)
      .attr('fill', '#1f2937')
      .attr('stroke', '#fff');
    _areaLabelSel = areaText(labelG.selectAll('text.mvg-area-name')
      .data(areaLabData).enter().append('text').attr('class', 'mvg-area-name'))
      .text((d) => d.name);
    _areaLabelSel.each(function (d) { d.__el1 = this; });
    _areaWrapSel = areaText(labelG.selectAll('text.mvg-area-name2')
      .data(areaLabData.filter((d) => d.lines)).enter().append('text')
      .attr('class', 'mvg-area-name2'));
    _areaWrapSel.each(function (d) {
      // Two lines centred on the anchor: with dominant-baseline central the
      // line centres sit at ∓LINE_GAP_EM/2.
      const t = d3.select(this);
      t.append('tspan').attr('x', 0).attr('dy', `${-LINE_GAP_EM / 2}em`).text(d.lines[0]);
      t.append('tspan').attr('x', 0).attr('dy', `${LINE_GAP_EM}em`).text(d.lines[1]);
      d.__el2 = this;
    });

    // Layer 5: protected-area aggregate chips (opt-in layer). Drawn last
    // so the chip sits above the region fill, and only when the layer is
    // switched on. One chip per region — never one mark per protected area.
    drawProtectedLayer(root);

    applyAreaHighlight();
    // Every label class now exists: run the first label pass synchronously
    // so the first paint is already culled.
    _markScaleApplied = 0;
    markLabelsDirty();
    onZoom();
  } catch (err) {
    console.error('[mvg] render failed', err);
    if (statusEl) {
      statusEl.textContent = err && err.message === DB_NOT_READY
        ? `The database did not start within ${DB_WAIT_MS / 60000} minutes, `
          + 'so the knowledge map cannot be drawn. Press Recompute layout to '
          + 'try again, or reload the page.'
        : `Knowledge map render failed: ${err.message}. `
          + 'Press Recompute layout to try again.';
    }
    const tocList = _container && _container.querySelector('#net-toc-list');
    if (tocList && tocList.querySelector('.mvg-toc-empty')) {
      tocList.innerHTML = '<li class="mvg-toc-empty">Not available</li>';
    }
  }
}


// Status line. The registry clause is appended only once the layer's
// data is in, and it names the tier explicitly — the map shows the core
// tier of person_registry (116 identities on the shipped parquet), of
// which only the site-linked subset ever gets a physical position here.
function updateStatus() {
  const statusEl = _container && _container.querySelector('#net-status');
  if (!statusEl || !_layout) return;
  const nOrg = _layout.areas.reduce((s, a) => s + (a.n_org || 0), 0);
  const nDs  = _layout.areas.reduce((s, a) => s + (a.n_datasets || 0), 0);
  const nPa  = _layout.areas.reduce((s, a) => s + (a.n_protected || 0), 0);
  let html = `<strong>${_layout.areas.length}</strong> research-area polygons`
    + ` sized by data and people, `
    + `<strong>${nOrg}</strong> organisations, `
    + `<strong>${nDs}</strong> data products, `
    + `<strong>${_layout.crossEdges.length}</strong> cross-area edges`;
  if (_layout.nAreasEmpty) {
    html += ` · <strong>${_layout.nAreasEmpty}</strong> vocabulary terms carry`
      + ' no organisation, dataset or person and have no region';
  }
  if (nPa) {
    html += ` · <strong>${nPa}</strong> protected areas catalogued as context,`
      + ' not counted as organisations';
  }
  if (_showRegistry && _registry) {
    const t = _registry.totals;
    // Placement split, stated as a split. n_sited people have a physical
    // position; n_domain are placed by science domain and have none;
    // n_unplaced have neither and are not on the map at all.
    html += ` · registry placement: <strong>${t.n_sited}</strong> at`
      + ` <strong>${t.n_sites}</strong> sites,`
      + ` <strong>${t.n_domain}</strong> by science domain across`
      + ` <strong>${t.n_domain_regions}</strong> regions (no site),`
      + ` <strong>${t.n_unplaced}</strong> of ${t.n_registry} not placeable`
      + ` · <strong>${t.n_site_edges}</strong> site↔site co-publication links`;
  }
  statusEl.innerHTML = html;
}


// ── Tooltip helpers ─────────────────────────────────────────────────
function ensureTooltip() {
  let t = _container.querySelector('.network-tooltip');
  if (!t) {
    t = document.createElement('div');
    t.className = 'network-tooltip';
    t.style.display = 'none';
    _container.appendChild(t);
  }
  return t;
}
function showTip(t, ev, html) {
  t.innerHTML = html;
  t.style.display = 'block';
  t.style.left = `${ev.clientX + 14}px`;
  t.style.top  = `${ev.clientY + 14}px`;
}
function hideTip(t) { t.style.display = 'none'; }

function nodeTipHtml(d) {
  if (d.kind === 'facility') {
    const sub = [d.acronym, d.country, (d.f_type || '').replace(/-/g, ' ')]
      .filter(Boolean).join(' · ');
    return `<strong>${escapeHtml(d.name)}</strong>` +
      (sub ? `<br><small>${escapeHtml(sub)}</small>` : '') +
      (d.url ? '<br><small style="color:#7dd3fc">click to open website</small>' : '');
  }
  // Person tooltip: name + role(s) + institution(s), then the
  // metrics that drove their node size. We deliberately omit
  // person_id / openalex_id / orcid from the visible chrome — those
  // are used only for the click-through link below.
  const lines = [`<strong>${escapeHtml(d.name)}</strong>`];

  const affils = Array.isArray(d.affiliations) ? d.affiliations : [];
  if (affils.length) {
    // Show up to 2 affiliations; collapse the rest into "+N more".
    const shown = affils.slice(0, 2);
    for (const a of shown) {
      const role = a.title || a.role || '';
      const fac  = a.facility || '';
      lines.push(`<small>${escapeHtml(role)}${role && fac ? '<br>' : ''}${escapeHtml(fac)}</small>`);
    }
    if (affils.length > shown.length) {
      lines.push(`<small style="color:#94a3b8">+${affils.length - shown.length} more affiliation${affils.length - shown.length === 1 ? '' : 's'}</small>`);
    }
  }

  // Say why this marker is hollow. The two cases are genuinely different
  // claims about the data and the tooltip is the only place the map can
  // distinguish them, so do not collapse them into one message.
  if (d.unaffiliated) {
    lines.push('<small style="color:#94a3b8">no institutional affiliation recorded' +
      '<br>placed in this research area only</small>');
  } else if (d.offAreaAffil) {
    lines.push('<small style="color:#94a3b8">affiliated institution is mapped to a' +
      '<br>different research area — shown here by domain</small>');
  }

  const metrics = [];
  if (d.n_pubs)   metrics.push(`${d.n_pubs} pubs`);
  if (d.n_coauth) metrics.push(`${d.n_coauth} co-authors`);
  if (d.facility_funding_usd) {
    const m = d.facility_funding_usd / 1e6;
    metrics.push(`$${m >= 100 ? Math.round(m) : m.toFixed(1)}M facility funding`);
  }
  if (metrics.length) {
    lines.push(`<small style="color:#7dd3fc">${metrics.join(' · ')}</small>`);
  }
  return lines.join('<br>');
}

// Region tooltip. States the sizing metric and the terms that produced it,
// so the reason one region is bigger than another is inspectable from the
// map instead of buried in this file. The protected-area count is shown
// whenever it is non-zero, labelled as context rather than capacity.
function areaTipHtml(a) {
  const bits = [];
  if (a.n_org) bits.push(`${a.n_org} organisation${a.n_org === 1 ? '' : 's'}`);
  if (a.n_data_providers) {
    bits.push(`${a.n_data_providers} data provider${a.n_data_providers === 1 ? '' : 's'}`);
  }
  if (a.n_datasets) bits.push(`${a.n_datasets} dataset${a.n_datasets === 1 ? '' : 's'}`);
  if (a.n_people) bits.push(`${a.n_people} people`);
  const paLine = a.n_protected
    ? `<br><small style="color:#4d7c0f">${a.n_protected} protected area${a.n_protected === 1 ? '' : 's'}`
      + ' also catalogued here — context, not organisation units; only the'
      + ' data and personnel they carry count toward region size</small>'
    : '';
  return `<strong>${escapeHtml(a.name)}</strong>`
    + (bits.length ? `<br><small>${bits.join(' · ')}</small>` : '')
    + `<br><small style="color:#0c4a6e">region size = data-and-people weight`
    + ` ${(a.weight || 0).toFixed(1)}</small>`
    + paLine
    + '<br><small>click to zoom</small>';
}

// Tooltip for a domain-placed cohort. Says in words that these people are
// NOT at a site, because the whole risk of placing them in a region is
// that the map implies a location it does not have.
function domainCohortTipHtml(d) {
  return `<strong>${escapeHtml(d.area_name)}</strong>`
    + `<br><small>${d.n_people} registry researcher${d.n_people === 1 ? '' : 's'}`
    + ` placed by <em>dominant science domain</em></small>`
    + '<br><small style="color:#b45309">No site link in the registry yet —'
    + ' site links land with the identity harvest. The region is their'
    + ' subject, not their address.</small>'
    + '<br><small>click to list them</small>';
}

// Side panel for a domain-placed cohort. Reuses the registry panel slot
// but is labelled unambiguously, and the rows carry no facility.
function renderDomainPanel(coh) {
  const panel = _container && _container.querySelector('#net-reg-panel');
  if (!panel || !coh) return;
  const CAP = 200;
  const list = coh.people.slice(0, CAP);
  const rows = list.map((p) => `<li>
      <button type="button" class="mvg-reg-row" data-cid="${escapeHtml(p.canonical_id)}">
        <span class="mvg-reg-name">${escapeHtml(p.display_name)}</span>
        <span class="mvg-reg-badge is-unknown"
              title="Placed by science domain — no site link">◌</span>
      </button></li>`).join('');
  panel.hidden = false;
  panel.innerHTML = `
    <div class="mvg-reg-head">
      <h3>${escapeHtml(coh.area_name)}</h3>
      <button type="button" id="net-reg-clear" class="btn-ghost">Clear</button>
    </div>
    <p class="mvg-reg-note mvg-reg-note-domain">${coh.n_people} researcher${coh.n_people === 1 ? '' : 's'}
      placed by <strong>dominant science domain</strong>, not by location.
      None of them holds a site link in the registry yet (site links land
      with the identity harvest), so none of them has a physical position
      on this map.</p>
    ${coh.n_people > list.length
      ? `<p class="mvg-reg-note">${list.length} of ${coh.n_people} listed here.</p>`
      : ''}
    <ol class="mvg-reg-list">${rows}</ol>`;
  panel.querySelector('#net-reg-clear')
    .addEventListener('click', () => { panel.hidden = true; panel.innerHTML = ''; });
  panel.querySelectorAll('.mvg-reg-row').forEach((btn) => {
    btn.addEventListener('click', () => {
      const p = list.find((x) => x.canonical_id === btn.dataset.cid);
      if (p) openRegistryProfile(p);
    });
  });
}

function facilityCircleTipHtml(c) {
  const sub = [c.acronym, c.country, (c.f_type || '').replace(/-/g, ' ')]
    .filter(Boolean).join(' · ');
  const peopleLine = c.n_people
    ? `<br><small style="color:#7dd3fc">${c.n_people} researcher${c.n_people === 1 ? '' : 's'} mapped here</small>`
    : '';
  // The archive link is the property the map is built to surface, so it
  // is stated first and in its own colour.
  const dataLine = c.is_provider
    ? `<br><small style="color:#0d9488"><strong>archive-linked</strong> — `
      + (c.n_datasets
          ? `${c.n_datasets} addressable dataset${c.n_datasets === 1 ? '' : 's'}`
          : 'no addressable datasets catalogued yet')
      + '</small>'
    : '';
  return `<strong>${escapeHtml(c.name || c.id)}</strong>` +
    (sub ? `<br><small>${escapeHtml(sub)}</small>` : '') +
    dataLine +
    peopleLine +
    (c.url ? '<br><small style="color:#7dd3fc">click to open website</small>' : '');
}
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// Render a researcher's name compactly: first initial + last name when
// the full name is long. Keeps map labels legible at default zoom.
function shortName(full) {
  if (!full) return '';
  const parts = String(full).trim().split(/\s+/);
  if (parts.length === 1) return parts[0];
  const last = parts[parts.length - 1];
  // If full name is short enough, keep it; else collapse to "F. Last".
  if (full.length <= 20) return full;
  return `${parts[0][0]}. ${last}`;
}

// Render a facility name compactly. Long institutional names ("Virginia
// Institute of Marine Science") would never fit inside their sub-
// polygon, so when the name is over ~22 chars and an acronym isn't
// available we drop boilerplate (Institute / University / etc.) and
// fall back to the first 18 chars.
function shortFacilityName(full) {
  if (!full) return '';
  const s = String(full).trim();
  if (s.length <= 22) return s;
  // Strip common boilerplate words to shorten without disambiguation
  // loss.
  const slim = s
    .replace(/\b(Institute|Institution|University|Department|Center|Centre|of|the|for|National|Marine|Coastal|Research|Laboratory|Lab)\b/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
  if (slim && slim.length <= 22) return slim;
  return s.slice(0, 18) + '…';
}

// Click on a researcher → take the user to their detail card in the
// People directory tab (which we ship as #/people/<person_id>). The
// directory page handles loading the per-person record.
function onPersonClick(d) {
  if (!d || !d.id) return;
  location.hash = `#/people/${encodeURIComponent(d.id)}`;
}

// Display names for institution labels.
//
// A network acronym is a useless label when it is shared: on the shipped
// parquet 61 sites carry one (NERR ×29, NEP ×19, LTER ×9, LTREB ×4,
// CPER ×2), so Coastal processes read as a wall of identical
// "NERR / NEP / LTER". A site whose acronym is shared — or that has none —
// is labelled by its PLACE: the canonical name with the trailing network
// designation removed ("Wells NERR" → "Wells", "Casco Bay Estuary
// Partnership NEP" → "Casco Bay"). A unique acronym of up to 8 characters
// is still the label, as before. The tooltip always carries the full name.
const NETWORK_SUFFIX_RE = new RegExp(
  '\\s+(National Estuary Program|Estuary Program|Estuary Partnership|'
  + 'Estuaries Partnership|NERR|NEP|LTER|LTREB|LTAR|MarineGEO|NEON Site)\\b.*$');
function facilityDisplayNames(facPolygons) {
  const nAcr = new Map();
  for (const sp of facPolygons.values()) {
    if (sp.acronym) nAcr.set(sp.acronym, (nAcr.get(sp.acronym) || 0) + 1);
  }
  const out = new Map();
  for (const [id, sp] of facPolygons.entries()) {
    const acr = sp.acronym;
    if (acr && acr.length <= 8 && nAcr.get(acr) === 1) { out.set(id, acr); continue; }
    const full = String(sp.name || '').trim();
    const place = full.replace(NETWORK_SUFFIX_RE, '').trim();
    out.set(id, shortFacilityName(place || full));
  }
  return out;
}

// Split a region name into two lines at the space nearest its middle.
// null for a one-word name (nothing to wrap).
function splitTwoLines(name) {
  const s = String(name || '').trim();
  let best = -1;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === ' ' && (best < 0 || Math.abs(i - s.length / 2) < Math.abs(best - s.length / 2))) best = i;
  }
  return best < 0 ? null : [s.slice(0, best), s.slice(best + 1)];
}


// ── Viewport: fit, zoom limits, resize ──────────────────────────────

// The transform that frames the bounding box of EVERY polygon in the
// stage with FIT_PAD_PX to spare. d3 composes screen = (x, y) + k·world.
function fitTransform() {
  const d3 = _d3Mod;
  const bb = _layout && _layout.polyBBox;
  if (!d3) return null;
  if (!bb || !(bb.x1 > bb.x0) || !(bb.y1 > bb.y0) || !(_stageW > 0) || !(_stageH > 0)) {
    return d3.zoomIdentity;
  }
  const bw = bb.x1 - bb.x0, bh = bb.y1 - bb.y0;
  const k = Math.max(1e-4, Math.min((_stageW - 2 * FIT_PAD_PX) / bw,
                                    (_stageH - 2 * FIT_PAD_PX) / bh));
  const cx = (bb.x0 + bb.x1) / 2, cy = (bb.y0 + bb.y1) / 2;
  return d3.zoomIdentity.translate(_stageW / 2 - k * cx, _stageH / 2 - k * cy).scale(k);
}

// Recompute the fit and every zoom limit for the current stage size.
// scaleExtent is RELATIVE to the fit (MIN/MAX_ZOOM_MULT), and
// translateExtent is the map's bbox padded by half its size each way, so
// the map can no longer be flung off-screen and lost.
function applyZoomExtents() {
  if (!_zoomBehavior || !_layout) return;
  _fitT = fitTransform();
  _fitK = _fitT ? _fitT.k : 1;
  const bb = _layout.polyBBox;
  const bw = bb.x1 - bb.x0, bh = bb.y1 - bb.y0;
  // The zoom zoomToArea() asks for to frame the smallest region.
  let kAreaMax = 0;
  for (const lab of _layout.labels.values()) {
    if (!(lab.bw > 0) || !(lab.bh > 0)) continue;
    kAreaMax = Math.max(kAreaMax, areaFitK(lab));
  }
  const kMax = Math.min(_fitK * MAX_ZOOM_CAP_MULT,
                        Math.max(_fitK * MAX_ZOOM_MULT, kAreaMax));
  _zoomBehavior
    .extent([[0, 0], [_stageW, _stageH]])
    .scaleExtent([_fitK * MIN_ZOOM_MULT, kMax])
    .translateExtent([[bb.x0 - bw * 0.5, bb.y0 - bh * 0.5],
                      [bb.x1 + bw * 0.5, bb.y1 + bh * 0.5]]);
}

// Back to "everything": Reset zoom, double-click, and a resize while the
// user has not moved the view. Clears the pinned area.
function resetToFit(animate) {
  if (!_zoomBehavior || !_zoomSvg || !_fitT) return;
  _userZoomed = false;
  setPinnedArea(null);
  const target = animate ? _zoomSvg.transition().duration(450) : _zoomSvg;
  target.call(_zoomBehavior.transform, _fitT);
}

// Watch the stage. A resize re-fits the map if the user has not moved it,
// otherwise keeps the world point at the centre of the stage and the zoom
// level. Labels are re-evaluated either way: before this existed a resize
// left them at their old size until the next wheel event (9.2 px facility
// labels after shrinking 1280 → 780 px, 21 px area labels after growing a
// phone viewport). Coalesced to one update per frame.
function observeStage(stage) {
  if (typeof ResizeObserver !== 'function') return;
  if (_resizeObs && _resizeObs.__stage === stage) return;
  if (_resizeObs) _resizeObs.disconnect();
  _resizeObs = new ResizeObserver(() => {
    if (_resizeRaf) return;
    _resizeRaf = requestAnimationFrame(() => { _resizeRaf = 0; onStageResize(stage); });
  });
  _resizeObs.__stage = stage;
  _resizeObs.observe(stage);
}

function onStageResize(stage) {
  const w = stage.clientWidth, h = stage.clientHeight;
  // 0×0 while another route is showing (the view is display:none).
  if (!(w > 0 && h > 0) || !_zoomSvg || !_zoomBehavior || !_layout) return;
  if (w === _stageW && h === _stageH) return;
  const t = _zoomT;
  const oldW = _stageW, oldH = _stageH;
  _stageW = w; _stageH = h;
  _zoomSvg.attr('viewBox', `0 0 ${w} ${h}`);
  applyZoomExtents();
  if (!_userZoomed || !t || !_d3Mod) {
    _zoomSvg.call(_zoomBehavior.transform, _fitT);
  } else {
    const cx = (oldW / 2 - t.x) / t.k, cy = (oldH / 2 - t.y) / t.k;
    const [k0, k1] = _zoomBehavior.scaleExtent();
    const k = Math.max(k0, Math.min(k1, t.k));
    _zoomSvg.call(_zoomBehavior.transform,
      _d3Mod.zoomIdentity.translate(w / 2 - k * cx, h / 2 - k * cy).scale(k));
  }
  onZoom();
}

// Pin (or with null, unpin) the research area the user asked for: its
// outline is drawn heavier, its TOC row is marked, and its name is always
// drawn by the label pass.
function setPinnedArea(areaId) {
  _pinnedAreaId = areaId || null;
  applyAreaHighlight();
  scheduleLabelPass();
}

function applyAreaHighlight() {
  if (_polySel) {
    _polySel
      .attr('stroke-width', (a) => (a.id === _pinnedAreaId ? AREA_STROKE_PX_PINNED : AREA_STROKE_PX))
      .attr('fill-opacity', (a) => (a.id === _pinnedAreaId ? AREA_FILL_OPACITY_PINNED : AREA_FILL_OPACITY));
    // Neighbours are drawn after it in document order and would paint over
    // half of a heavy outline; raise the pinned path to the top of its group.
    if (_pinnedAreaId) _polySel.filter((a) => a.id === _pinnedAreaId).raise();
  }
  if (_container) {
    _container.querySelectorAll('.mvg-toc-row').forEach((btn) => {
      const on = !!_pinnedAreaId && btn.dataset.area === _pinnedAreaId;
      btn.classList.toggle('is-active', on);
      if (on) btn.setAttribute('aria-current', 'true');
      else btn.removeAttribute('aria-current');
    });
  }
}


// ── Label engine ────────────────────────────────────────────────────
//
// Every label is a <text> inside the zoomed root group, anchored at a
// layout point (wx, wy). While shown it carries
//   transform="translate(wx, wy) scale(1/k)"
// so the zoom carries it to the right screen position and the counter-
// scale cancels the zoom for its glyphs: font-size, halo stroke-width and
// the `y` offset are written ONCE in screen px and never re-derived. The
// width of every label is therefore constant on screen too, measured once
// with a canvas context and cached.
//
// The pass (runLabelPass) runs at most once per animation frame while a
// zoom or pan is in flight, and once more, synchronously, when the
// gesture ends (onZoom). It decides eligibility from on-screen size (see
// "Label tiers" at the top of the file), then places labels greedily in
// priority order against a grid of already-placed boxes. Off-stage anchors
// are rejected before any box is built, so a deep zoom costs no more than
// the overview.

const LABEL_FONT_FAMILY = 'system-ui, sans-serif';
// Vertical offset of a protected-area chip below its region's label
// anchor, in screen px.
const CHIP_DY_PX = 22;

// Common presentation attributes for every label class. Labels start
// hidden; the label pass shows the ones that have room.
function labelTexts(sel, pxOf, haloPx, weight = 600) {
  return sel
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'central')
    .attr('font-family', LABEL_FONT_FAMILY)
    .attr('font-weight', weight)
    .attr('font-size', (d) => pxOf(d))
    .attr('stroke-width', haloPx)
    .attr('stroke-linejoin', 'round')
    .attr('paint-order', 'stroke')
    .style('display', 'none')
    .each(function (d) {
      this.__mvgShown = false;
      this.__mvgPx = pxOf(d);
      this.__mvgK = null;
      this.__mvgDy = 0;
    });
}

let _measureCtx = null;
const _textW100 = new Map();
// Rendered width in CSS px of `text` at `px`, cached per string at a 100 px
// reference size (width is linear in font size).
function textWidthPx(text, px, weight = 600, italic = false) {
  const key = `${italic ? 'i' : 'n'}${weight}|${text}`;
  let w = _textW100.get(key);
  if (w === undefined) {
    if (!_measureCtx) {
      try { _measureCtx = document.createElement('canvas').getContext('2d'); }
      catch (_) { _measureCtx = null; }
    }
    if (_measureCtx) {
      _measureCtx.font = `${italic ? 'italic ' : ''}${weight} 100px ${LABEL_FONT_FAMILY}`;
      w = _measureCtx.measureText(String(text)).width;
    } else {
      w = String(text).length * 60;          // ~0.6 em per glyph
    }
    _textW100.set(key, w);
  }
  return (w * px) / 100;
}

// Labels shown by the previous pass, so the next one only has to touch
// the ones that change state.
let _shownEls = new Set();

function markLabelsDirty() {
  _labelCands = null;
  if (_rootG) scheduleLabelPass();
}

function scheduleLabelPass() {
  if (!_labelRaf) _labelRaf = requestAnimationFrame(runLabelPass);
}

// Run the label pass NOW (zoom end, resize, a layer redraw). Takes no
// argument: older call sites still pass _zoomK, which is ignored — the
// pass reads the live transform.
function onZoom() {
  if (_labelRaf) { cancelAnimationFrame(_labelRaf); _labelRaf = 0; }
  runLabelPass();
}

// One record per label: its anchor, its priority and the forms it may be
// drawn in, each with a precomputed screen width and height.
function buildLabelCandidates() {
  const cands = [];
  const labels = _layout ? _layout.labels : new Map();
  const facPolys = (_layout && _layout.facPolygons) || new Map();
  const lineH = (px) => px * LINE_BOX_EM;

  if (_areaLabelSel) {
    const weights = [];
    _areaLabelSel.each((d) => weights.push(d.weight || 0));
    weights.sort((a, b) => b - a);
    const topW = weights.length ? weights[Math.min(AREA_TOP_N, weights.length) - 1] : Infinity;
    _areaLabelSel.each(function (d) {
      const el1 = d.__el1 || this, el2 = d.__el2 || null;
      const forms = [];
      for (const px of [d.__basePx, AREA_LABEL_PX_SMALL]) {
        forms.push({ el: el1, px, w: textWidthPx(d.name, px), h: lineH(px) });
        if (el2) {
          forms.push({ el: el2, px,
            w: Math.max(textWidthPx(d.lines[0], px), textWidthPx(d.lines[1], px)),
            h: px * (LINE_GAP_EM + LINE_BOX_EM) });
        }
      }
      if ((d.weight || 0) >= topW && (d.weight || 0) > 0) {
        const px = AREA_LABEL_PX_MIN;
        forms.push({ el: el1, px, w: textWidthPx(d.name, px), h: lineH(px) });
      }
      // Fallback order for the pinned area when nothing FITS its polygon:
      // narrowest readable form first.
      const pinForms = [...forms].sort((a, b) => (b.px - a.px) || (a.w - b.w));
      cands.push({ kind: 'area', id: d.id, pri: 4e6 + (d.weight || 0),
                   wx: d.x, wy: d.y, lab: d.lab, els: el2 ? [el1, el2] : [el1],
                   ring: (_layout && _layout.polygons.get(d.id)) || null,
                   facs: [], forms, pinForms });
    });
  }
  const ctxCand = (sel, kind, anchorDy) => {
    if (!sel) return;
    sel.each(function (d) {
      const px = d.__basePx || PA_LABEL_PX.min;
      const f = { el: this, px, w: textWidthPx(this.textContent, px), h: lineH(px) };
      cands.push({ kind: 'ctx', pri: 3e6 + (d.n_protected || d.n_people || 0),
                   wx: d.x, wy: anchorDy(d), lab: labels.get(d.area_id),
                   els: [this], forms: [f],
                   dy: kind === 'pa' ? CHIP_DY_PX : -(2 + f.h / 2) });
    });
  };
  ctxCand(_paLabelSel, 'pa', (d) => d.y);
  ctxCand(_regDomainLabelSel, 'dom', (d) => d.y - (d.__baseR || 0));

  if (_facLabelSel) {
    _facLabelSel.each(function (d) {
      const px = d.__basePx;
      cands.push({ kind: 'fac', pri: 2e6 + (d.weight || 0), wx: d.x, wy: d.y,
                   area_id: d.area_id,
                   bw: d.bw || 0, bh: d.bh || 0, dotR: d.__dotR || 2.6,
                   els: [this],
                   forms: [{ el: this, px, w: textWidthPx(d.display, px), h: lineH(px) }] });
    });
  }
  if (_regLabelSel && _focusFacility) {
    const sp = facPolys.get(_focusFacility);
    _regLabelSel.each(function (d) {
      const px = d.__basePx;
      cands.push({ kind: 'person', pri: 1.5e6 + (d.h_index || 0), wx: d.x, wy: d.y,
                   bw: sp ? sp.bw : 0, bh: sp ? sp.bh : 0, minPx: PERSON_MIN_FACPOLY_PX,
                   dotR: registryRadius(d), els: [this],
                   forms: [{ el: this, px, w: textWidthPx(this.textContent, px), h: lineH(px) }] });
    });
  }
  if (_labelSel) {
    _labelSel.each(function (d) {
      const px = d.__basePx;
      // A researcher inside an institution drawn here is gated on that
      // institution's sub-polygon; one in the interstitial space on the
      // region as a whole.
      const sp = !d.__italic && d.primary_facility_id ? facPolys.get(d.primary_facility_id) : null;
      const lab = labels.get(d.area_id);
      const box = sp || (lab ? { bw: lab.bw, bh: lab.bh } : { bw: 0, bh: 0 });
      cands.push({ kind: 'person', pri: 1e6 + (d.importance || 0), wx: d.x, wy: d.y,
                   bw: box.bw, bh: box.bh,
                   minPx: sp ? PERSON_MIN_FACPOLY_PX : PERSON_MIN_AREAPOLY_PX,
                   dotR: d.__baseR || 2, els: [this],
                   forms: [{ el: this, px,
                             w: textWidthPx(this.textContent, px, 500, !!d.__italic),
                             h: lineH(px) }] });
    });
  }
  // Each region keeps a list of its institutions, so its name can be
  // steered off their dots and name slots (runLabelPass).
  const areaCand = new Map();
  for (const c of cands) if (c.kind === 'area') areaCand.set(c.id, c);
  for (const c of cands) {
    if (c.kind !== 'fac') continue;
    const a = areaCand.get(c.area_id);
    if (a) a.facs.push(c);
  }
  cands.sort((a, b) => b.pri - a.pri);
  return cands;
}

// Horizontal interior span of `ring` at row y that contains x, as [lo, hi];
// null when (x, y) is outside.
function rowSpan(ring, x, y) {
  const hits = [];
  for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
    const a = ring[i], b = ring[j];
    if ((a[1] > y) !== (b[1] > y)) {
      hits.push(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]));
    }
  }
  hits.sort((p, q) => p - q);
  for (let i = 0; i + 1 < hits.length; i += 2) {
    if (hits[i] <= x && x <= hits[i + 1]) return [hits[i], hits[i + 1]];
  }
  return null;
}

// Where, on row y, can a label of world half-width hw and glyph
// half-height hh sit inside the ring? Its top, middle and bottom rows must
// each lie inside the outline — a single chord-length test at the anchor
// let names spill over a narrowing outline, or past one side when the
// anchor was off-centre in its chord. Returns the x nearest to `x` at which
// the label fits, or null.
function labelXInRing(ring, x, y, hw, hh) {
  let lo = -Infinity, hi = Infinity;
  for (const yy of [y - hh, y, y + hh]) {
    const sp = rowSpan(ring, x, yy);
    if (!sp) return null;
    if (sp[0] > lo) lo = sp[0];
    if (sp[1] < hi) hi = sp[1];
  }
  if (hi - lo < 2 * hw) return null;
  return Math.max(lo + hw, Math.min(hi - hw, x));
}

// Is an institution big enough on screen at scale k for its name?
function facLabelEligible(c, k) {
  const pw = k * c.bw, ph = k * c.bh;
  return Math.min(pw, ph) >= FAC_MIN_POLY_PX && pw >= FAC_LABEL_FIT * c.forms[0].w;
}

function showLabel(el, px, wx, wy, dy, k) {
  if (el.__mvgPx !== px) { el.setAttribute('font-size', px); el.__mvgPx = px; }
  const ry = Math.round(dy * 10) / 10;
  if (el.__mvgDy !== ry) { el.setAttribute('y', ry); el.__mvgDy = ry; }
  if (el.__mvgK !== k) {
    el.setAttribute('transform', `translate(${wx},${wy}) scale(${1 / k})`);
    el.__mvgK = k;
  }
  if (!el.__mvgShown) { el.style.display = ''; el.__mvgShown = true; }
}

function hideLabel(el) {
  if (el.__mvgShown !== false) { el.style.display = 'none'; el.__mvgShown = false; }
}

function gridKey(cx, cy) { return cx * 8192 + cy; }

function gridHits(grid, b, pad) {
  const c0 = Math.floor((b.x0 - pad) / CULL_CELL_PX), c1 = Math.floor((b.x1 + pad) / CULL_CELL_PX);
  const r0 = Math.floor((b.y0 - pad) / CULL_CELL_PX), r1 = Math.floor((b.y1 + pad) / CULL_CELL_PX);
  for (let cx = c0; cx <= c1; cx++) {
    for (let cy = r0; cy <= r1; cy++) {
      const list = grid.get(gridKey(cx, cy));
      if (!list) continue;
      for (const o of list) {
        if (b.x0 - pad < o.x1 && b.x1 + pad > o.x0
         && b.y0 - pad < o.y1 && b.y1 + pad > o.y0) return true;
      }
    }
  }
  return false;
}

function gridInsert(grid, b) {
  const c0 = Math.floor(b.x0 / CULL_CELL_PX), c1 = Math.floor(b.x1 / CULL_CELL_PX);
  const r0 = Math.floor(b.y0 / CULL_CELL_PX), r1 = Math.floor(b.y1 / CULL_CELL_PX);
  for (let cx = c0; cx <= c1; cx++) {
    for (let cy = r0; cy <= r1; cy++) {
      const key = gridKey(cx, cy);
      const list = grid.get(key);
      if (list) list.push(b); else grid.set(key, [b]);
    }
  }
}

// Dots and ribbons: constant apparent size, world growth capped at
// MARK_MAX_GROWTH. Skipped when the scale moved by under 2% since the last
// write, so a pan rewrites nothing.
function rescaleMarks(k) {
  const markScale = Math.min(MARK_MAX_GROWTH, 1 / (k > 0 ? k : 1));
  if (_markScaleApplied && Math.abs(markScale / _markScaleApplied - 1) < 0.02) return;
  _markScaleApplied = markScale;
  if (_dotPersonSel) {
    _dotPersonSel.attr('r', (d) => (d.__baseR || 2.0) * markScale);
    // The hollow "no institution here" markers are read by their outline,
    // so the outline has to keep a constant apparent width the way the
    // registry markers' does — otherwise the dashes close up when zoomed
    // out and the marker reads as a filled dot, i.e. as an affiliation.
    _dotPersonSel
      .attr('stroke-width', (d) => (d.__gapDot ? 0.9 : 0.5) * markScale)
      .attr('stroke-dasharray', (d) => (d.__gapDot
        ? `${1.6 * markScale} ${1.2 * markScale}` : null));
  }
  if (_dotFacSel) {
    _dotFacSel.attr('r', (d) => (d.__baseR || 2.6) * markScale);
  }
  if (_regNodeSel) {
    _regNodeSel.attr('r', (d) => (d.__baseR || 2.5) * markScale)
      .attr('stroke-width', 0.7 * markScale);
  }
  if (_regSiteLinkSel) {
    _regSiteLinkSel.attr('stroke-width', (e) => (e.__baseW || 1) * markScale);
  }
  if (_regNodeLinkSel) {
    _regNodeLinkSel.attr('stroke-width', (e) => (e.__baseW || 0.5) * markScale);
  }
}

function runLabelPass() {
  _labelRaf = 0;
  if (!_rootG || !_layout || !_zoomT) return;
  const t = _zoomT, k = t.k;
  const W = _stageW, H = _stageH;
  rescaleMarks(k);
  if (!_labelCands) _labelCands = buildLabelCandidates();

  const grid = new Map();
  const shown = new Set();
  // Screen radius of a dot per unit of its base radius (see rescaleMarks).
  const dotK = Math.min(MARK_MAX_GROWTH * k, 1);
  const REJECT = 400;      // px beyond the stage at which an anchor is skipped outright

  // Screen box of form f drawn at world (wx, wy), shifted dy screen px.
  const boxAt = (wx, wy, dy, f) => {
    const sx = t.x + k * wx, sy = t.y + k * wy + dy;
    return { x0: sx - f.w / 2, x1: sx + f.w / 2, y0: sy - f.h / 2, y1: sy + f.h / 2 };
  };
  // Fully on the stage and clear of everything placed so far.
  const free = (b) => !(b.x0 < 0 || b.y0 < 0 || b.x1 > W || b.y1 > H)
    && !gridHits(grid, b, LABEL_PAD_PX);
  const commit = (b, f, wx, wy, dy) => {
    gridInsert(grid, b);
    showLabel(f.el, f.px, wx, wy, dy, k);
    shown.add(f.el);
  };
  const place = (c, f, dy) => {
    const b = boxAt(c.wx, c.wy, dy, f);
    if (!free(b)) return false;
    commit(b, f, c.wx, c.wy, dy);
    return true;
  };

  // Screen boxes a region's name keeps off: the dot of each of its
  // institutions once the region is large on screen, and the name slot
  // above the dot of each institution big enough to be named. Before this,
  // a region holding one institution put its own name on that dot (the
  // pole of inaccessibility and the sub-polygon centroid coincide) and,
  // being placed first, hid the institution's name at every zoom.
  const obstaclesOf = (c) => {
    const out = [];
    const lab = c.lab;
    const large = k * Math.min(lab.bw, lab.bh) >= AREA_DOT_AVOID_PX;
    for (const fc of c.facs) {
      const named = facLabelEligible(fc, k);
      if (!named && !large) continue;
      const sx = t.x + k * fc.wx, sy = t.y + k * fc.wy;
      const r = fc.dotR * dotK + 2;
      const f = fc.forms[0];
      out.push(named
        ? { x0: sx - Math.max(r, f.w / 2), x1: sx + Math.max(r, f.w / 2),
            y0: sy - r - f.h, y1: sy + r }
        : { x0: sx - r, x1: sx + r, y0: sy - r, y1: sy + r });
    }
    return out;
  };
  const hitsAny = (b, list) => {
    for (const o of list) {
      if (b.x0 - LABEL_PAD_PX < o.x1 && b.x1 + LABEL_PAD_PX > o.x0
       && b.y0 - LABEL_PAD_PX < o.y1 && b.y1 + LABEL_PAD_PX > o.y0) return true;
    }
    return false;
  };

  // Place a region name. Positions tried, in order: the pole of
  // inaccessibility, then the pole shifted up/down by AREA_LABEL_SHIFTS of
  // the region's vertical chord; and, when the pole is off or at the edge
  // of the stage while part of the region is on it, the same around the
  // centre of the region's on-stage part and around the pole clamped into
  // it — so a region filling a third of the stage with its pole just out of
  // view is still named. With `needFit` the name must lie inside the
  // outline on its top, middle and bottom rows, slid sideways within the
  // outline if the anchor is off-centre (labelXInRing). A position
  // that keeps off the region's institutions (obstaclesOf) is preferred;
  // failing that the first that fits wins, as before.
  const placeArea = (c, forms, needFit) => {
    const lab = c.lab, ring = c.ring;
    const rx0 = t.x + k * lab.x0, rx1 = t.x + k * (lab.x0 + lab.bw);
    const ry0 = t.y + k * lab.y0, ry1 = t.y + k * (lab.y0 + lab.bh);
    const vx0 = Math.max(0, rx0), vx1 = Math.min(W, rx1);
    const vy0 = Math.max(0, ry0), vy1 = Math.min(H, ry1);
    if (vx1 <= vx0 || vy1 <= vy0) return false;          // wholly off-stage
    const anchors = [[lab.x, lab.y]];
    const psx = t.x + k * lab.x, psy = t.y + k * lab.y;
    const M = AREA_EDGE_MARGIN_PX;
    if (psx < M || psx > W - M || psy < M || psy > H - M) {
      const toW = (sx, sy) => [(sx - t.x) / k, (sy - t.y) / k];
      anchors.push(toW((vx0 + vx1) / 2, (vy0 + vy1) / 2));
      if (vx1 - vx0 > 2 * M && vy1 - vy0 > 2 * M) {
        anchors.push(toW(Math.max(vx0 + M, Math.min(vx1 - M, psx)),
                         Math.max(vy0 + M, Math.min(vy1 - M, psy))));
      }
    }
    const obst = obstaclesOf(c);
    for (const strict of obst.length ? [true, false] : [false]) {
      for (const f of forms) {
        // The chords through the pole bound what can fit nearby; a cheap
        // filter before the per-row ring test.
        if (needFit && (k * lab.hw < AREA_LABEL_FIT * f.w || k * lab.vh < f.h)) continue;
        const hw = (AREA_LABEL_FIT * f.w) / 2 / k;
        const hh = Math.max(0, f.h / 2 - 0.15 * f.px) / k;
        for (const [ax, ay0] of anchors) {
          for (const sh of AREA_LABEL_SHIFTS) {
            const ay = ay0 + sh * lab.vh;
            let x = ax;
            if (ring) {
              if (needFit) {
                x = labelXInRing(ring, ax, ay, hw, hh);
                if (x === null) continue;
              } else if (!rowSpan(ring, ax, ay)) continue;
            }
            const b = boxAt(x, ay, 0, f);
            if (!free(b)) continue;
            if (strict && hitsAny(b, obst)) continue;
            commit(b, f, x, ay, 0);
            return true;
          }
        }
      }
    }
    return false;
  };

  // Name a region that fills much of the stage at the topmost row of the
  // stage where the name lies inside its outline and clear of what is
  // already placed. Used for the region the user is inside (it covers
  // AREA_INSIDE_FRAC of the stage, so its pole is usually off-screen), and
  // as the last try for one whose on-stage part is >= AREA_SCAN_FRAC of the
  // stage when placeArea found no spot. Without it a deep zoom often showed
  // no region name at all.
  const placeAreaTop = (c) => {
    const ring = c.ring;
    const xs = [W / 2, W / 4, (3 * W) / 4, W / 8, (7 * W) / 8];
    for (const f of c.forms) {
      if (f.el !== c.els[0]) continue;                   // one line only
      const hw = (AREA_LABEL_FIT * f.w) / 2 / k;
      const hh = Math.max(0, f.h / 2 - 0.15 * f.px) / k;
      const step = Math.max(6, f.h / 2);
      for (let sy = 12 + f.h / 2; sy <= H - 12 - f.h / 2; sy += step) {
        const wy = (sy - t.y) / k;
        for (const sx of xs) {
          let x = (sx - t.x) / k;
          if (ring) {
            x = labelXInRing(ring, x, wy, hw, hh);
            if (x === null) continue;
          }
          const b = boxAt(x, wy, 0, f);
          if (!free(b)) continue;
          commit(b, f, x, wy, 0);
          return true;
        }
      }
    }
    return false;
  };

  const pinned = _pinnedAreaId
    ? _labelCands.find((c) => c.kind === 'area' && c.id === _pinnedAreaId) : null;
  const order = pinned ? [pinned, ..._labelCands.filter((c) => c !== pinned)] : _labelCands;

  for (const c of order) {
    if (c.kind === 'area') {
      const lab = c.lab;
      // Share of the stage the region's on-stage bbox covers.
      const x0 = Math.max(0, t.x + k * lab.x0), x1 = Math.min(W, t.x + k * (lab.x0 + lab.bw));
      const y0 = Math.max(0, t.y + k * lab.y0), y1 = Math.min(H, t.y + k * (lab.y0 + lab.bh));
      const onStage = x1 > x0 && y1 > y0 ? ((x1 - x0) * (y1 - y0)) / (W * H) : 0;
      // "Inside" the region: its on-stage part covers most of the stage.
      if (c !== pinned && onStage >= AREA_INSIDE_FRAC) {
        placeAreaTop(c);
        continue;
      }
      if (placeArea(c, c.forms, true)) continue;
      if (onStage >= AREA_SCAN_FRAC && placeAreaTop(c)) continue;
      if (c === pinned) placeArea(c, c.pinForms, false);
      continue;
    }
    const sx = t.x + k * c.wx, sy = t.y + k * c.wy;
    if (sx < -REJECT || sx > W + REJECT || sy < -REJECT || sy > H + REJECT) continue;
    if (c.kind === 'ctx') {
      if (!c.lab || k * Math.min(c.lab.bw, c.lab.bh) < CONTEXT_MIN_POLY_PX) continue;
      place(c, c.forms[0], c.dy);
    } else if (c.kind === 'fac') {
      const f = c.forms[0];
      if (!facLabelEligible(c, k)) continue;
      place(c, f, -(c.dotR * dotK + 2 + f.h / 2));
    } else {               // person / registry researcher
      const f = c.forms[0];
      if (k * Math.min(c.bw, c.bh) < c.minPx) continue;
      place(c, f, -(c.dotR * dotK + 2 + f.h / 2));
    }
  }
  for (const el of _shownEls) if (!shown.has(el)) hideLabel(el);
  _shownEls = shown;
}

// Programmatic zoom-to-polygon: fit the polygon's bounding box to the
// VISIBLE STAGE with AREA_FIT_PAD_PX to spare, clamped to the zoom limits
// (which are relative to the whole-map fit), and pin the area so its name
// and outline stay marked. The old version fitted against the viewBox size
// and clamped k to [0.6, 8], so every small region hit 8 — past the end of
// the old area-label band — and the area you had just clicked lost its name.
// Scale that fits a region's bbox in the stage with AREA_FIT_PAD_PX spare.
function areaFitK(lab) {
  return Math.min(Math.max(1, _stageW - 2 * AREA_FIT_PAD_PX) / lab.bw,
                  Math.max(1, _stageH - 2 * AREA_FIT_PAD_PX) / lab.bh);
}

function zoomToArea(areaId) {
  if (!_zoomBehavior || !_zoomSvg || !_layout || !_d3Mod) return;
  const lab = _layout.labels.get(areaId);
  if (!lab || !(lab.bw > 0) || !(lab.bh > 0)) return;
  const W = _stageW, H = _stageH;
  const cx = lab.x0 + lab.bw / 2, cy = lab.y0 + lab.bh / 2;
  const [k0, k1] = _zoomBehavior.scaleExtent();
  const k = Math.max(k0, Math.min(k1, areaFitK(lab)));
  _userZoomed = true;
  setPinnedArea(areaId);
  const zoomT = _d3Mod.zoomIdentity.translate(W / 2 - k * cx, H / 2 - k * cy).scale(k);
  _zoomSvg.transition().duration(650).call(_zoomBehavior.transform, zoomT);
}


// ── Public API ──────────────────────────────────────────────────────
export function initNetworkView(container) {
  _container = container;
  _container.innerHTML = `
    <div class="network-view">
      <header class="network-header">
        <div>
          <h2>Knowledge map</h2>
          <p class="network-sub">Country-like map of U.S. Long-Term
          Observatories. Each polygon is one research area, sized by a
          data-and-people weight. Hover for details; click a node to reveal
          its edges, shift-click to open homepage / ORCID.</p>
          <a href="#" class="network-help-toggle"
             data-net-help="open">How to read this map</a>
          <div class="network-help" id="net-help" hidden>
            <p><strong>Region size</strong> is a data-and-people weight —
            organisations, plus a bonus for each site whose data lives in an
            authoritative archive, plus its addressable data products, plus
            the researchers anchored there. It is <em>not</em> the raw
            catalogue count: roughly a third of the catalogued facilities are
            place-type monitoring installations (protected areas, flux
            towers, streamgage networks, experimental forests), and a raw
            count ranks coverage rather than observatory capacity. The
            protected areas stay catalogued behind the off-by-default
            <em>Protected areas</em> layer, drawn as one aggregate chip per
            region.</p>
            <p><strong>Inside a region</strong>, sub-polygons are individual
            institutions; archive-linked sites carry a larger marker.
            Researchers (sky-blue) sit inside their primary institution; a
            hollow dashed dot is a researcher with no institution drawn in
            that region.</p>
            <p><strong>Names appear as there is room for them.</strong> The
            map opens framed on every region. Region names show when the
            name fits inside its polygon on screen (on one line, two lines,
            or smaller), institution names once an institution&rsquo;s
            territory is large enough to hold its name, researcher names
            once you are zoomed into their institution. Labels never overlap:
            when two compete, the region wins over the institution and the
            institution over the researcher. A region whose name does not
            fit is still listed on the left and named in its tooltip.
            Clicking a region (or its row in the list) zooms to it and keeps
            its name and outline marked. <em>Reset zoom</em> or a
            double-click on the map shows everything again.</p>
            <p><strong>Edges are hidden until you click a node.</strong>
            Drawing all of them at once buried the regions under a thousand
            crossing lines. Click a researcher or an institution to reveal
            just that node&rsquo;s cross-area edges; click it again, click
            the background, or press <kbd>Esc</kbd> to put them away.
            Shift-click instead of clicking to open the homepage / ORCID.
            Colour is unchanged: gray = facility-facility shared
            programs, sky-blue = researchers bridging two areas
            (interdisciplinary potential). Toggling Facilities or People
            still gates which edges a click can reveal. Switch on <em>Researchers &amp;
            co-authorship</em> for the person registry: amber ribbons are
            co-publication between two catalogued sites, a solid marker is a
            researcher with a site link, and a dashed hollow ring is a
            cohort placed by science domain with <em>no</em> site. Clicking
            either opens its roster. Site links and co-authorship edges are
            populated by the OpenAlex/ORCID identity harvest and fill in as
            it lands.</p>
            <p><strong>Algorithm.</strong> KMap from Hossain et al.
            GI&nbsp;'25, with hierarchical institution sub-polygons. The
            full description, with every label threshold, is in
            <a href="#/docs/knowledge-map">Docs &rsaquo; Knowledge map</a>.</p>
          </div>
        </div>
        <div class="network-actions">
          <label class="net-toggle">
            <input type="checkbox" data-toggle="facility" checked>
            <span class="net-swatch" style="background:${NODE_COLORS.facility}"></span>
            Facilities
          </label>
          <label class="net-toggle">
            <input type="checkbox" data-toggle="person" checked>
            <span class="net-swatch" style="background:${NODE_COLORS.person}"></span>
            People
          </label>
          <label class="net-toggle">
            <input type="checkbox" data-toggle="registry">
            <span class="net-swatch" style="background:${NODE_COLORS.registry}"></span>
            Researchers &amp; co-authorship
          </label>
          <label class="net-toggle" title="18 catalogued protected areas
(16 federal, 1 state, 1 private), drawn as one aggregate chip per region —
context, not organisation units.">
            <input type="checkbox" data-toggle="protected">
            <span class="net-swatch net-swatch-pa"
                  style="background:${NODE_COLORS.protected}"></span>
            Protected areas (context)
          </label>
          <button id="net-restart" class="btn-ghost" title="Recompute layout from scratch">Recompute layout</button>
        </div>
      </header>
      <p id="net-reg-note" class="network-scope-note" hidden>
        The researcher layer draws the <strong>core tier</strong> of the LTO
        person registry — verified site personnel plus LTO-affiliated
        scholars. It is not the whole field. Placement is in two kinds and
        they mean different things: a researcher with a site link is drawn
        as a solid marker <em>at</em> that site; one without is placed by
        their dominant science domain, shown as a dashed hollow ring per
        region labelled “N no site” — a claim about their subject, not
        their address; identities with neither are not on the map. Site
        links and co-authorship edges are populated by the OpenAlex/ORCID
        identity harvest and fill in as it lands — until then rosters and
        ribbons read zero. Marker size is LTO-related <em>output volume</em>
        (an upper bound, not a paper count); click a site or a cohort ring
        to list who is in it. The status line below reports the live
        placement split.
      </p>
      <div id="net-status" class="network-status">Loading…</div>
      <div class="mvg-shell">
        <aside id="net-toc" class="mvg-toc" aria-label="Research areas">
          <details class="mvg-toc-details" open>
            <summary><h3>Research areas</h3></summary>
            <p class="mvg-toc-key" title="Each row's numbers: organisations · datasets · people">
              <span>area</span><span>orgs · datasets · people</span></p>
            <ol id="net-toc-list" class="mvg-toc-list"><li class="mvg-toc-empty">Loading…</li></ol>
          </details>
          <button id="net-toc-reset" class="btn-ghost" type="button"
                  title="Show the whole map (or double-click it)">Reset zoom</button>
        </aside>
        <div id="net-stage" class="network-stage"></div>
        <aside id="net-reg-panel" class="mvg-reg-panel"
               aria-label="Researchers at the selected site" hidden></aside>
      </div>
    </div>`;

  // Phone: the status line is clamped to two lines (styles.css); a tap
  // shows the rest.
  const statusLine = _container.querySelector('#net-status');
  if (statusLine) {
    statusLine.addEventListener('click', () => statusLine.classList.toggle('is-open'));
  }

  _container.querySelectorAll('.net-toggle input').forEach((el) => {
    el.addEventListener('change', () => {
      const k = el.dataset.toggle;
      if (k === 'registry') {
        // The registry layer owns exactly one <g>, so it never needs the
        // full re-render the other two toggles trigger — switching it
        // redraws that group and nothing else.
        _showRegistry = el.checked;
        const note = _container.querySelector('#net-reg-note');
        if (note) note.hidden = !_showRegistry;
        if (!_showRegistry) {
          _focusFacility = null;
          if (_d3Mod) drawRegistryLayer(_d3Mod, ensureTooltip());
          renderRegistryPanel(null);
          updateStatus();
          return;
        }
        ensureRegistry().then(() => {
          if (!_showRegistry || !_d3Mod) return;
          drawRegistryLayer(_d3Mod, ensureTooltip());
          onZoom(_zoomK);
          updateStatus();
        }).catch((err) => {
          console.error('[mvg] registry layer failed', err);
          if (note) {
            note.hidden = false;
            note.textContent = 'Researcher layer unavailable — the registry '
              + 'query failed. See the console for details.';
          }
        });
        return;
      }
      if (k === 'protected') {
        // Aggregate-only layer over data already in _layout, so it needs
        // neither a fetch nor a re-render — redraw its own <g> and resize.
        _showProtected = el.checked;
        if (_rootG) { drawProtectedLayer(_rootG); onZoom(_zoomK); }
        return;
      }
      if (k === 'facility') _showFacility = el.checked;
      else if (k === 'person') _showPerson = el.checked;
      // Toggle changes don't need a re-layout — just re-render.
      render().catch((err) => console.error(err));
    });
  });
  // The "how to read this map" explanation is collapsed by default: inline
  // it ran to four paragraphs and pushed the map itself below the fold.
  const helpLink = _container.querySelector('.network-help-toggle');
  const helpBox  = _container.querySelector('#net-help');
  if (helpLink && helpBox) {
    helpLink.addEventListener('click', (ev) => {
      ev.preventDefault();
      helpBox.hidden = !helpBox.hidden;
      helpLink.textContent = helpBox.hidden
        ? 'How to read this map' : 'Hide guide';
    });
  }
  _container.querySelector('#net-restart').addEventListener('click', () => {
    // Recomputing the layout moves every site anchor, so the registry
    // layer's geometry and its focus selection are both invalid.
    invalidateNetworkData();
    render().catch((err) => console.error(err));
  });
  _container.querySelector('#net-toc-reset').addEventListener('click', () => {
    // The fit-to-everything transform, not zoomIdentity: with the viewBox
    // in stage px, identity is an arbitrary 1:1 view of the layout.
    resetToFit(true);
  });
  // On a phone the TOC would take most of the screen above the map, so it
  // starts collapsed there (styles.css turns the summary into a toggle at
  // the same breakpoint). Desktop keeps it open and the summary inert.
  const tocDetails = _container.querySelector('.mvg-toc-details');
  if (tocDetails && window.matchMedia
      && window.matchMedia('(max-width: 760px)').matches) {
    tocDetails.open = false;
  }
}

// Populate the TOC sidebar with one row per active research area,
// sorted by the data-and-people weight desc. Click → zoomToArea.
function populateToc() {
  if (!_layout || !_container || !_colorOf) return;
  const list = _container.querySelector('#net-toc-list');
  if (!list) return;
  // Ranked by the same data-and-people weight that sizes the regions, so
  // the sidebar order and the map areas agree. The count column shows the
  // three terms the reader can check — organisations / datasets / people —
  // rather than a single opaque score.
  const sorted = [..._layout.areas].sort(
    (a, b) => (b.weight || 0) - (a.weight || 0));
  list.innerHTML = sorted.map((a) => `
    <li>
      <button type="button" data-area="${escapeHtml(a.id)}" class="mvg-toc-row"
              title="weight ${(a.weight || 0).toFixed(1)} — ${a.n_org || 0} organisations, ${a.n_data_providers || 0} data providers, ${a.n_datasets || 0} datasets, ${a.n_people || 0} people${a.n_protected ? `; ${a.n_protected} protected areas (context)` : ''}">
        <span class="mvg-toc-swatch" style="background:${_colorOf.get(a.id) || '#94a3b8'}"></span>
        <span class="mvg-toc-label">${escapeHtml(a.name)}</span>
        <span class="mvg-toc-count">${a.n_org || 0}·${a.n_datasets || 0}·${a.n_people || 0}</span>
      </button>
    </li>`).join('');
  list.querySelectorAll('.mvg-toc-row').forEach((btn) => {
    btn.addEventListener('click', () => {
      // On a phone the list sits BELOW the map (styles.css), so the row
      // tapped is out of sight of the stage and the zoom would happen
      // off-screen. Fold the list and bring the map into view first.
      if (window.matchMedia && window.matchMedia('(max-width: 760px)').matches) {
        const det = _container.querySelector('.mvg-toc-details');
        if (det) det.open = false;
        const stage = _container.querySelector('#net-stage');
        if (stage && stage.scrollIntoView) {
          stage.scrollIntoView({ block: 'start', behavior: 'smooth' });
        }
      }
      zoomToArea(btn.dataset.area);
    });
  });
  applyAreaHighlight();
}

export async function renderNetworkView() {
  if (!_container) return;
  try {
    await render();
  } catch (e) {
    console.error('knowledge map render failed', e);
  }
}

export function invalidateNetworkData() {
  _layout = null;
  // The registry layer's selections point into an SVG that is about to
  // be discarded, and its geometry is derived from _layout, so drop
  // both. The fetched rows themselves stay cached — they don't depend
  // on the layout and re-querying them would be wasted work.
  _regRootG = null;
  _regSiteLinkSel = null;
  _regNodeSel = null;
  _regNodeLinkSel = null;
  _regLabelSel = null;
  _regDomainLabelSel = null;
  // The protected-area chips and every label selection point into the SVG
  // that is about to be discarded, and _rootG is that SVG's root group.
  // Leaving them set would make onZoom() operate on detached nodes and
  // drawProtectedLayer() append into a dead tree.
  _rootG = null;
  _paChipSel = null;
  _paLabelSel = null;
  _areaLabelSel = null;
  _areaWrapSel = null;
  _polySel = null;
  _labelCands = null;
  _shownEls = new Set();
  // A recomputed layout has a different bbox: drop the old view and pin.
  _zoomT = null;
  _userZoomed = false;
  _pinnedAreaId = null;
  _facLabelSel = null;
  _labelSel = null;
  _dotPersonSel = null;
  _dotFacSel = null;
  _facPolySel = null;
  _focusFacility = null;
  // The revealed-edge subset lives inside the SVG that is about to be
  // discarded, and _redrawEdgeReveal closes over that SVG's <g>. Keeping
  // the closure would let a later Escape press or Clear click append into
  // a detached tree — the same failure mode the registry selections above
  // are nulled for. The selected id goes too: "Recompute layout" moves
  // every node, so re-validating a carried-over id against the new
  // _layout would be re-validating against different geometry.
  _redrawEdgeReveal = null;
  _selectedNodeId = null;
  renderRegistryPanel(null);
}
