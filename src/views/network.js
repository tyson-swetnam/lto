// network.js — Knowledge map (MVG, Map Visualization with Group restriction).
//
// Replaces the previous force-directed knowledge graph with a country-like
// map where each polygon is one research area (parent-collapsed when small),
// polygon area is proportional to the number of facilities in that area,
// and facilities + people sit inside their polygon. Cross-area edges
// reveal interdisciplinary collaboration.
//
// Implements the KMap algorithm from Hossain, Moradi, Mondal & Kobourov,
// "Map Visualizations for Graphs with Group Restrictions" (Graphics
// Interface 2025, DOI 10.1145/3769872.3769900). Three steps:
//
//   1. Supergraph: one supernode per active research area, weight = facility
//      count, edges = cross-area facility-personnel + co-author counts.
//      Embed with d3-force using square collision so each area gets a
//      non-overlapping square sized by sqrt(weight).
//
//   2. Subgraph layout: for each area, run a small d3-force layout on its
//      facility + person nodes, then scale to fit inside its square.
//
//   3. Voronoi-merged polygons: compute Voronoi over all node positions
//      plus a ring of perimeter "anchor" points; for each area, union the
//      cells of its members via polygon-clipping. Smooth boundaries via
//      one Chaikin pass to soften the polygon outlines.
//
// Phase 3 (PCL refinement, custom force terms) and Phase 5 (canvas
// rendering + Web Worker) are documented in docs/map_visualization_plan.md
// and will land as follow-up commits.

import { getConn, whenReady, unwrapRow } from '../db.js';

// ── Module state ────────────────────────────────────────────────────
let _container = null;
let _layout = null;
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
// Last zoom level seen — used by the label-visibility logic. Default
// to 1 so the initial paint shows labels at constant size.
let _zoomK = 1;
// Reference to the labels/dots selections so onZoom can resize them
// without a full re-render.
let _labelSel = null;
let _areaLabelSel = null;
let _facLabelSel = null;
let _dotPersonSel = null;
let _dotFacSel = null;
// Selection for the facility sub-polygons themselves, captured so
// hover/zoom logic can address them later (e.g. dim non-hovered
// polygons in the same area to reveal a single institution).
let _facPolySel = null;

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
};
const NODE_RADIUS = { facility: 4, person: 3 };

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
const SUPERNODE_SCALE  = 24;     // side = scale * sqrt(weight)
const SUPERNODE_MIN    = 28;     // minimum side so 1-facility areas remain visible
const DECOR_GRID       = 5;      // 5×5 = 25 decoration anchors per area square
const DECOR_JITTER     = 0.18;   // ±18% random jitter so cell boundaries aren't gridlike


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
async function fetchData() {
  await whenReady();
  const conn = getConn();
  if (!conn) throw new Error('DuckDB connection not ready');

  const queries = {
    // ACTIVE areas only — collapsed_into IS NULL means this area is its
    // own polygon. Collapsed areas are absorbed into their parent in the
    // facility/person primary tables already.
    areas: `
      SELECT area_id AS id, label AS name, n_facilities AS weight
      FROM   research_areas_active
      WHERE  collapsed_into IS NULL
      ORDER  BY area_id`,

    // One row per facility with its primary area + display fields.
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
      WHERE  g.primary_area_id IS NOT NULL`,

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
        SELECT person_id,
               SUM(n_publications)     AS n_pubs,
               SUM(n_co_authors)       AS n_coauth,
               SUM(total_citations)    AS total_citations
        FROM person_area_metrics
        GROUP BY person_id
      ),
      per_fund AS (
        SELECT fp.person_id,
               SUM(faf.total_usd_nominal) AS facility_funding_usd
        FROM facility_personnel fp
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
  for (const a of out.areas) a.weight = Number(a.weight) || 0;
  for (const e of out.fac_pers) e.w = Number(e.w) || 1;
  for (const e of out.coauthors) e.w = Number(e.w) || 1;

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
  // Seed positions on a ring proportional to weight so the simulation
  // converges quickly and large groups end up roughly central.
  const sorted = [...sg.nodes].sort((a, b) => b.weight - a.weight);
  const maxR = Math.min(w, h) * 0.36;
  sorted.forEach((n, i) => {
    const t = i / Math.max(sorted.length - 1, 1);
    const r = t * maxR * 0.85 + 0.05 * maxR;
    const a = i * (2 * Math.PI / Math.max(sorted.length, 6)) + 0.1 * i;
    n.x = cx + r * Math.cos(a);
    n.y = cy + r * Math.sin(a);
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

  // Resolve any remaining overlap with a deterministic relax pass.
  for (let r = 0; r < 60; r++) {
    let moved = false;
    for (let i = 0; i < sg.nodes.length; i++) {
      for (let j = i + 1; j < sg.nodes.length; j++) {
        const a = sg.nodes[i], b = sg.nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const minD = (a.side + b.side) * 0.5 + SUPER_PADDING;
        const dist = Math.hypot(dx, dy) || 1e-6;
        if (dist < minD) {
          const push = (minD - dist) / 2;
          const nx = dx / dist, ny = dy / dist;
          a.x -= nx * push; a.y -= ny * push;
          b.x += nx * push; b.y += ny * push;
          moved = true;
        }
      }
    }
    if (!moved) break;
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
                   f_type: f.f_type, area_id: areaId }));
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
        weight: 1 + (peopleAt.get(f.id) || 0),
        kind: 'facility',
      }))
    : [{ id: `__phantom_${square.id}`, name: '', kind: 'facility',
         area_id: square.id, weight: 1 }];

  const totalWeight = bubbles.reduce((s, b) => s + Math.sqrt(b.weight), 0);
  const innerR = (square.side / 2) * 0.84;  // 16% inset from square edge
  // Per-bubble radius. Min 5 px so single-person facilities are visible;
  // max ~innerR so a giant institution can't dwarf the whole area.
  const RFAC = 0.62 * innerR / Math.max(totalWeight, 1);
  for (const b of bubbles) {
    b.r = Math.min(innerR * 0.65, Math.max(5, RFAC * Math.sqrt(b.weight) * 1.5));
    // Seed at a random point inside the inner circle.
    const a = Math.random() * 2 * Math.PI;
    const r = Math.random() * (innerR - b.r);
    b.x = cx + r * Math.cos(a);
    b.y = cy + r * Math.sin(a);
  }
  const bubSim = d3.forceSimulation(bubbles)
    .alphaDecay(0.05)
    .force('center', d3.forceCenter(cx, cy).strength(0.08))
    .force('charge', d3.forceManyBody().strength(-12))
    .force('collide',
      d3.forceCollide().radius((d) => d.r + 1.6).strength(1).iterations(2))
    .stop();
  for (let i = 0; i < 220; i++) bubSim.tick();

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
  const peoPerFac = new Map();
  for (const p of peo) {
    const fid = p.primary_facility_id;
    const b = (fid && facCircles.get(fid)) || facCircles.get(bubbles[0].id);
    if (!b) continue;
    const k = peoPerFac.get(b) || 0;
    peoPerFac.set(b, k + 1);
    const n = (peopleAt.get(fid) || 1);
    // Deterministic spiral up to bubble's inner 88%.
    const t = (k + 0.5) / Math.max(n, 1);
    const r = b.r * 0.88 * Math.sqrt(t);
    const a = (k + 1) * PHI;
    p.x = b.x + r * Math.cos(a);
    p.y = b.y + r * Math.sin(a);
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

  // Polygon centroids for label placement.
  const labels = new Map();
  for (const a of data.areas) {
    const ring = polyOut.polygons.get(a.id);
    if (!ring) continue;
    let cx = 0, cy = 0, n = 0;
    for (let i = 0; i < ring.length - 1; i++) { cx += ring[i][0]; cy += ring[i][1]; n++; }
    if (n) labels.set(a.id, { x: cx / n, y: cy / n, name: a.name, weight: a.weight });
  }

  return {
    polygons: polyOut.polygons,
    bbox: polyOut.bbox,
    nodes: allNodes,
    crossEdges,
    labels,
    areas: data.areas,
    facCircles,
    facPolygons,
  };
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
      const data = await fetchData();
      statusEl.textContent = 'Computing knowledge map (this takes 5-10 s)…';
      _layout = await buildLayout(data, w, h);
    }
    statusEl.innerHTML = `<strong>${_layout.areas.length}</strong> research-area polygons, <strong>${_layout.nodes.length}</strong> nodes, <strong>${_layout.crossEdges.length}</strong> cross-area edges`;

    stage.innerHTML = '';
    // viewBox is computed to focus on the WEIGHTED CORE of the map —
    // not the bounding box of every polygon. The previous "tightest
    // bbox of all rings" logic let one or two single-facility outlier
    // polygons (which the force sim sometimes flings to the periphery)
    // stretch the box, so the central dense cluster — coastal-processes,
    // marine-ecosystems, biogeochemistry — ended up off-center and tiny
    // while the user saw mostly empty parchment with an outlier in the
    // top corner.
    //
    // Instead, we:
    //   1. Compute the weighted centroid of all area polygons, weighted
    //      by polygon weight (= n_facilities).
    //   2. Rank polygons by distance from that centroid.
    //   3. Walk the ranked list inward → outward, accumulating bbox AND
    //      cumulative weight. Stop once cumulative weight covers
    //      VIEWBOX_WEIGHT_FRAC of the total.
    //
    // Outlier polygons remain rendered (you can pan/zoom-out to see
    // them), they just don't dictate the default frame. Tuned so the
    // 4-5 biggest cartograms always land on screen at first paint.
    const VIEWBOX_WEIGHT_FRAC = 0.80;
    let bx, by, bw, bh;
    {
      // Polygon centroids + weights.
      const cents = [];
      for (const a of _layout.areas) {
        const ring = _layout.polygons.get(a.id);
        if (!ring || ring.length === 0) continue;
        let cx = 0, cy = 0;
        for (const [x, y] of ring) { cx += x; cy += y; }
        cx /= ring.length; cy /= ring.length;
        cents.push({ a, ring, cx, cy, w: a.weight || 1 });
      }
      const totalW = cents.reduce((s, c) => s + c.w, 0) || 1;

      // Weighted centroid (importance-weighted "center of mass").
      let sx = 0, sy = 0;
      for (const c of cents) { sx += c.cx * c.w; sy += c.cy * c.w; }
      const wcx = sx / totalW, wcy = sy / totalW;

      // Sort by distance from weighted centroid; bigger polygons
      // additionally win ties (and pull the inclusion threshold
      // toward themselves) by penalising their distance with a
      // sqrt-weight bonus.
      cents.sort((p, q) => {
        const dp = Math.hypot(p.cx - wcx, p.cy - wcy) / Math.sqrt(p.w);
        const dq = Math.hypot(q.cx - wcx, q.cy - wcy) / Math.sqrt(q.w);
        return dp - dq;
      });

      // Accumulate bbox until we cover VIEWBOX_WEIGHT_FRAC of weight.
      let mnX = Infinity, mnY = Infinity, mxX = -Infinity, mxY = -Infinity;
      let cumW = 0;
      for (const { ring, w } of cents) {
        for (const [x, y] of ring) {
          if (x < mnX) mnX = x; if (y < mnY) mnY = y;
          if (x > mxX) mxX = x; if (y > mxY) mxY = y;
        }
        cumW += w;
        if (cumW / totalW >= VIEWBOX_WEIGHT_FRAC) break;
      }

      // Fall-through guard if for any reason no polygons were captured.
      if (mnX === Infinity) {
        for (const ring of _layout.polygons.values()) {
          for (const [x, y] of ring) {
            if (x < mnX) mnX = x; if (y < mnY) mnY = y;
            if (x > mxX) mxX = x; if (y > mxY) mxY = y;
          }
        }
      }

      // 8% padding so polygons aren't flush against the edge.
      const padW = (mxX - mnX) * 0.08;
      const padH = (mxY - mnY) * 0.08;
      bx = mnX - padW; by = mnY - padH;
      bw = (mxX - mnX) + 2 * padW;
      bh = (mxY - mnY) + 2 * padH;
    }
    const svg = d3.select(stage).append('svg')
      .attr('viewBox', `${bx} ${by} ${bw} ${bh}`)
      .attr('preserveAspectRatio', 'xMidYMid meet')
      .attr('class', 'mvg-svg');
    const root = svg.append('g').attr('class', 'mvg-root');

    // d3.zoom — captured so the TOC + polygon clicks can call it.
    const zoom = d3.zoom().scaleExtent([0.4, 12]).on('zoom', (ev) => {
      root.attr('transform', ev.transform);
      onZoom(ev.transform.k);
    });
    svg.call(zoom);
    _zoomBehavior = zoom;
    _zoomSvg = svg;

    const tip = ensureTooltip();

    // Layer 1: polygons
    const areaList = _layout.areas;
    const colorOf = new Map(areaList.map((a, i) => [a.id, AREA_PALETTE[i % AREA_PALETTE.length]]));
    _colorOf = colorOf;
    const polyG = root.append('g').attr('class', 'mvg-polys');
    polyG.selectAll('path').data(areaList).enter().append('path')
      .attr('d', (a) => {
        const ring = _layout.polygons.get(a.id);
        return ring ? `M${ring.map((p) => p.join(',')).join('L')}Z` : '';
      })
      .attr('fill', (a) => colorOf.get(a.id))
      .attr('fill-opacity', 0.18)
      .attr('stroke', (a) => colorOf.get(a.id))
      .attr('stroke-opacity', 0.9)
      .attr('stroke-width', 1.4)
      .style('cursor', 'pointer')
      .on('mouseenter', function (ev, a) {
        d3.select(this).attr('fill-opacity', 0.32);
        const lab = _layout.labels.get(a.id);
        if (lab) showTip(tip, ev, `<strong>${escapeHtml(a.name)}</strong><br><small>${a.weight} facilities — click to zoom</small>`);
      })
      .on('mouseleave', function () {
        d3.select(this).attr('fill-opacity', 0.18);
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
          if (d.url) window.open(d.url, '_blank', 'noopener');
        });
    } else {
      _facPolySel = null;
    }

    // Layer 2: cross-area edges. THREE visibility buckets so edges
    // don't dangle into invisible nodes:
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
    const buckets = { ff: [], pf: [], pp: [] };
    for (const e of _layout.crossEdges) {
      const k = edgeKind(e);
      if (buckets[k]) buckets[k].push(e);
    }
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
    const drawEdges = (cls, arr, stroke, opacity, baseW, kind) => {
      if (!arr.length) return;
      const g = root.append('g').attr('class', cls).attr('fill', 'none');

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
    if (_showFacility) drawEdges('mvg-edges-ff', buckets.ff, '#94a3b8', 0.18, 0.35, 'ff');
    if (_showFacility && _showPerson) drawEdges('mvg-edges-pf', buckets.pf, '#7dd3fc', 0.30, 0.45, 'pf');
    if (_showPerson) drawEdges('mvg-edges-pp', buckets.pp, '#0ea5e9', 0.55, 0.6, 'pp');

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
        let cx = 0, cy = 0;
        for (const [x, y] of sp.ring) { cx += x; cy += y; }
        return [cx / sp.ring.length, cy / sp.ring.length];
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
          const url = d.url || d.homepage_url;
          if (url) window.open(url, '_blank', 'noopener');
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
      const dotPeople = perNodes.filter((p) => !labelledIds.has(p.id));
      const dotRadius = (d) => {
        const w = d.importance || 0;
        return 1.6 + Math.min(2.2, Math.sqrt(w) * 0.55);
      };
      _dotPersonSel = root.append('g').attr('class', 'mvg-per-dots')
        .selectAll('circle').data(dotPeople).enter().append('circle')
        .attr('cx', (d) => d.x).attr('cy', (d) => d.y)
        .attr('r', dotRadius)
        .attr('fill', NODE_COLORS.person)
        .attr('fill-opacity', 0.75)
        .attr('stroke', '#fff')
        .attr('stroke-width', 0.5)
        .style('cursor', 'pointer')
        .on('mouseenter', (ev, d) => showTip(tip, ev, nodeTipHtml(d)))
        .on('mouseleave', () => hideTip(tip))
        .on('click', (ev, d) => onPersonClick(d));
      // Tag base radius so onZoom can counter-scale per-dot.
      _dotPersonSel.each(function (d) { d.__baseR = dotRadius(d); });

      // Name labels for the top N per area. We store the BASE font
      // size on the datum so onZoom() can rescale relative to it.
      const labelPeople = perNodes.filter((p) => labelledIds.has(p.id));
      const personBaseFont = (d) => {
        // Tighter range (8–12 px) so label sizes don't visually
        // compete with area names. Differentiation between top and
        // mid-tier researchers comes from sqrt-importance scaling.
        const w = d.importance || 0;
        return Math.max(8, Math.min(12, 8 + Math.sqrt(w) * 0.7));
      };
      _labelSel = root.append('g').attr('class', 'mvg-per-labels')
        .attr('text-anchor', 'middle')
        .attr('font-family', 'system-ui, sans-serif')
        .selectAll('text').data(labelPeople).enter().append('text')
        .attr('x', (d) => d.x).attr('y', (d) => d.y)
        .attr('font-size', personBaseFont)
        .attr('font-weight', 500)
        .attr('fill', '#0c4a6e')
        .attr('stroke', '#fff')
        .attr('stroke-width', 2.4)
        .attr('stroke-linejoin', 'round')
        .attr('paint-order', 'stroke')
        .style('cursor', 'pointer')
        .text((d) => shortName(d.name))
        .on('mouseenter', (ev, d) => showTip(tip, ev, nodeTipHtml(d)))
        .on('mouseleave', () => hideTip(tip))
        .on('click', (ev, d) => onPersonClick(d));
      // Tag each label with its base font so onZoom can rescale.
      _labelSel.each(function (d) { d.__baseFont = personBaseFont(d); });
    } else {
      _labelSel = null;
      _dotPersonSel = null;
    }

    // Layer 3.5: FACILITY NAME LABELS. Same progressive-reveal +
    // collision-culling logic as person labels — at the default zoom
    // only the largest institutions' names are visible, and as the
    // user zooms in more facility names appear because their world-
    // space bbox shrinks. Placed at sub-polygon centroid, font sized
    // by sqrt(n_people). Hidden entirely below k = 0.7 (would
    // overcrowd the default frame).
    if (_showFacility && _layout.facPolygons && _layout.facPolygons.size) {
      const facLabData = [..._layout.facPolygons.entries()].map(([id, sp]) => {
        const ring = sp.ring || [];
        let cx = 0, cy = 0;
        for (const [x, y] of ring) { cx += x; cy += y; }
        if (ring.length) { cx /= ring.length; cy /= ring.length; }
        const display = sp.acronym && sp.acronym.length <= 8
          ? sp.acronym
          : shortFacilityName(sp.name);
        return {
          id, x: cx, y: cy,
          display, name: sp.name, acronym: sp.acronym,
          country: sp.country, f_type: sp.f_type, url: sp.url,
          n_people: sp.n_people || 0, area_id: sp.area_id,
          // Tighter range than people (7–11 px). Acronyms are short
          // so they sit comfortably inside small sub-polygons; full
          // names get collision-culled until the user zooms in enough
          // that they fit.
          baseFont: Math.max(7, Math.min(11, 7 + Math.sqrt(sp.n_people || 0) * 0.7)),
        };
      });
      _facLabelSel = root.append('g').attr('class', 'mvg-fac-labels')
        .attr('text-anchor', 'middle')
        .attr('font-family', 'system-ui, sans-serif')
        .attr('pointer-events', 'none')
        .selectAll('text').data(facLabData).enter().append('text')
        .attr('x', (d) => d.x).attr('y', (d) => d.y)
        .attr('font-size', (d) => d.baseFont)
        .attr('font-weight', 600)
        .attr('fill', '#0f172a')
        .attr('stroke', '#fef9f0')
        .attr('stroke-width', 1.8)
        .attr('stroke-linejoin', 'round')
        .attr('paint-order', 'stroke')
        .text((d) => d.display);
      _facLabelSel.each(function (d) { d.__baseFont = d.baseFont; });
    } else {
      _facLabelSel = null;
    }

    // Initial label-visibility/scaling pass so the very-first paint
    // matches whatever zoom level we're starting at.
    onZoom(_zoomK);
    // Populate the left-hand TOC of research areas (clickable to zoom).
    populateToc();

    // Layer 4: polygon (research area) labels. Captured into _areaLabelSel
    // so onZoom() can counter-scale them just like the person labels —
    // otherwise the area names balloon at high zoom.
    const labelG = root.append('g').attr('class', 'mvg-labels')
      .attr('text-anchor', 'middle')
      .attr('font-family', 'system-ui, sans-serif')
      .attr('pointer-events', 'none');
    const areaLabData = areaList
      .filter((a) => _layout.labels.has(a.id))
      .map((a) => {
        const lab = _layout.labels.get(a.id);
        return {
          id: a.id, name: lab.name, x: lab.x, y: lab.y,
          // Tighter range (10–16 px) than before. The previous (11–22)
          // scaled ALL labels up by 1/k when the user zoomed out at
          // initial fit (k≈0.5), producing the giant 40+ px labels
          // that overpowered the polygons. Combined with the onZoom()
          // change that caps the counter-scale at 1.0, labels now
          // stay legible without dominating the canvas.
          baseFont: Math.max(10, Math.min(16, 8 + Math.sqrt(a.weight) * 1.2)),
        };
      });
    _areaLabelSel = labelG.selectAll('text').data(areaLabData).enter().append('text')
      .attr('x', (d) => d.x).attr('y', (d) => d.y)
      .attr('font-size', (d) => d.baseFont)
      .attr('font-weight', 600)
      .attr('fill', '#1f2937')
      .attr('stroke', '#fff')
      .attr('stroke-width', 2.2)
      .attr('stroke-linejoin', 'round')
      .attr('paint-order', 'stroke')
      .text((d) => d.name);
    _areaLabelSel.each(function (d) { d.__baseFont = d.baseFont; });
  } catch (err) {
    console.error('[mvg] render failed', err);
    if (statusEl) statusEl.textContent = `Knowledge map render failed: ${err.message}`;
  }
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

function facilityCircleTipHtml(c) {
  const sub = [c.acronym, c.country, (c.f_type || '').replace(/-/g, ' ')]
    .filter(Boolean).join(' · ');
  const peopleLine = c.n_people
    ? `<br><small style="color:#7dd3fc">${c.n_people} researcher${c.n_people === 1 ? '' : 's'} mapped here</small>`
    : '';
  return `<strong>${escapeHtml(c.name || c.id)}</strong>` +
    (sub ? `<br><small>${escapeHtml(sub)}</small>` : '') +
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

// Show / hide / rescale researcher labels in response to zoom level.
//
// FIXED PIXEL SIZE: labels use base_font_px / zoom_k as their SVG
// font-size, so they stay constant size on the screen at every zoom
// level. Hidden entirely below k = 0.5 (would be unreadable noise).
//
// COLLISION CULLING: after sizing, walk all visible labels in
// importance order (largest base font first → top researcher per
// area), measure each one's bounding box in WORLD coordinates, and
// hide any label whose box overlaps an already-shown one. As the user
// zooms in, more labels survive the cull because boxes shrink in
// world coords while polygons stay the same size.
function onZoom(k) {
  _zoomK = k || 1;
  // Cap the counter-scale at 1.0 — labels should NEVER grow above
  // their base size when the user zooms out. The previous unbounded
  // 1/k formula made a 22 px label balloon to 44 px at the initial
  // fit zoom (k≈0.5), drowning the canvas. Below k=1 we leave fonts
  // at base size; above k=1 we shrink them so they stay readable
  // (constant screen size) as the user zooms in.
  const labelScale = Math.min(1, 1 / Math.max(_zoomK, 0.5));
  // Dot scale: similar logic — at k>=1 dots stay at base radius;
  // when zoomed in they shrink so they don't bloat into giant blobs.
  const dotScale = Math.min(1, 1 / Math.max(_zoomK, 0.5));
  if (_dotPersonSel) {
    _dotPersonSel.attr('r', (d) => (d.__baseR || 2.0) * dotScale);
  }
  if (_dotFacSel) {
    _dotFacSel.attr('r', 2.6 * dotScale);
  }
  if (_areaLabelSel) {
    _areaLabelSel
      .attr('font-size', (d) => (d.__baseFont || 14) * labelScale)
      .attr('stroke-width', 2.2 * labelScale);
  }
  // FACILITY labels — same progressive-reveal pattern as people.
  // Hidden below k=0.7 (their target home is "you've zoomed in enough
  // to see institutions"). Above that threshold they get the same
  // counter-scale + collision-cull treatment as person labels.
  if (_facLabelSel) {
    if (_zoomK < 0.7) {
      _facLabelSel.style('display', 'none');
    } else {
      _facLabelSel
        .style('display', null)
        .attr('font-size', (d) => (d.__baseFont || 8) * labelScale)
        .attr('stroke-width', 1.8 * labelScale);
      cullSelection(_facLabelSel);
    }
  }

  if (!_labelSel) return;
  if (_zoomK < 0.5) {
    _labelSel.style('display', 'none');
    return;
  }
  _labelSel
    .style('display', null)
    .attr('font-size', (d) => (d.__baseFont || 10) * labelScale)
    .attr('stroke-width', 2.0 * labelScale);
  cullSelection(_labelSel);
}

// Hide labels whose world-space bounding boxes overlap higher-priority
// labels. Higher priority = larger base font. Generalised to take ANY
// selection so person labels and facility labels share the same logic
// while remaining INDEPENDENT (each cull pass operates on its own
// bucket — facility labels overlapping person labels is fine because
// they read as different colours / weights).
function cullSelection(sel) {
  if (!sel) return;
  const nodes = sel.nodes();
  const order = nodes.map((_, i) => i)
    .sort((a, b) => (nodes[b].__data__.__baseFont || 0)
                  - (nodes[a].__data__.__baseFont || 0));
  const placed = [];
  for (const i of order) {
    const el = nodes[i];
    el.style.display = '';
    let bb;
    try { bb = el.getBBox(); }
    catch (_) { continue; }
    const r = { x: bb.x - 2, y: bb.y - 2,
                w: bb.width + 4, h: bb.height + 4 };
    let hit = false;
    for (const p of placed) {
      if (r.x < p.x + p.w && r.x + r.w > p.x
       && r.y < p.y + p.h && r.y + r.h > p.y) { hit = true; break; }
    }
    if (hit) el.style.display = 'none';
    else placed.push(r);
  }
}

// Programmatic zoom-to-polygon. Computes the polygon's bounding box,
// then animates a d3.zoom transform that fits it (with margin) into
// the SVG viewport.
function zoomToArea(areaId) {
  if (!_zoomBehavior || !_zoomSvg || !_layout) return;
  const ring = _layout.polygons.get(areaId);
  if (!ring) return;
  let mnX = Infinity, mnY = Infinity, mxX = -Infinity, mxY = -Infinity;
  for (const [x, y] of ring) {
    if (x < mnX) mnX = x; if (y < mnY) mnY = y;
    if (x > mxX) mxX = x; if (y > mxY) mxY = y;
  }
  const cx = (mnX + mxX) / 2, cy = (mnY + mxY) / 2;
  const polyW = mxX - mnX, polyH = mxY - mnY;
  // SVG viewBox dimensions (read from attribute).
  const vb = (_zoomSvg.attr('viewBox') || '').split(/\s+/).map(Number);
  if (vb.length !== 4) return;
  const [vbx, vby, vbw, vbh] = vb;
  const margin = 1.2;  // 20% breathing room
  const scaleX = vbw / (polyW * margin);
  const scaleY = vbh / (polyH * margin);
  const k = Math.max(0.6, Math.min(8, Math.min(scaleX, scaleY)));
  // d3.zoom transform composes as: screen = T + k * world.
  // We want world point (cx, cy) to map to viewBox center (vbx + vbw/2,
  // vby + vbh/2). So tx = vbx + vbw/2 - k * cx, similarly for ty.
  const tx = (vbx + vbw / 2) - k * cx;
  const ty = (vby + vbh / 2) - k * cy;
  if (!_d3Mod || !_d3Mod.zoomIdentity) return;
  // Build the d3 transform: identity → translate → scale composes
  // such that screen = T + k * world. We computed tx/ty above for k.
  const zoomT = _d3Mod.zoomIdentity.translate(tx, ty).scale(k);
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
          <p class="network-sub">Country-like map of cod-kmap. Each outer
          polygon is one research area (parent-collapsed when &lt; 3 facilities);
          polygon area is proportional to facility count. Inside each area,
          dashed sub-circles are individual institutions sized by their
          personnel count; researchers (sky-blue dots, sized by funding +
          collaborators + publications) sit inside their primary institution.
          Toggling Facilities or People also toggles their cross-area edges:
          gray lines = facility-facility shared programs, sky-blue lines =
          researchers bridging two areas (interdisciplinary potential).
          Hover for details, click to open homepage / ORCID. Algorithm:
          KMap from Hossain et al. GI&nbsp;'25 with hierarchical institution
          sub-polygons.</p>
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
          <button id="net-restart" class="btn-ghost" title="Recompute layout from scratch">Recompute layout</button>
        </div>
      </header>
      <div id="net-status" class="network-status">Loading…</div>
      <div class="mvg-shell">
        <aside id="net-toc" class="mvg-toc" aria-label="Research areas">
          <h3>Research areas</h3>
          <ol id="net-toc-list" class="mvg-toc-list"><li class="mvg-toc-empty">Loading…</li></ol>
          <button id="net-toc-reset" class="btn-ghost" type="button">Reset zoom</button>
        </aside>
        <div id="net-stage" class="network-stage"></div>
      </div>
    </div>`;

  _container.querySelectorAll('.net-toggle input').forEach((el) => {
    el.addEventListener('change', () => {
      const k = el.dataset.toggle;
      if (k === 'facility') _showFacility = el.checked;
      else if (k === 'person') _showPerson = el.checked;
      // Toggle changes don't need a re-layout — just re-render.
      render().catch((err) => console.error(err));
    });
  });
  _container.querySelector('#net-restart').addEventListener('click', () => {
    _layout = null;
    render().catch((err) => console.error(err));
  });
  _container.querySelector('#net-toc-reset').addEventListener('click', () => {
    if (_zoomBehavior && _zoomSvg && _d3Mod && _d3Mod.zoomIdentity) {
      _zoomSvg.transition().duration(450)
        .call(_zoomBehavior.transform, _d3Mod.zoomIdentity);
    }
  });
}

// Populate the TOC sidebar with one row per active research area,
// sorted by facility count desc. Click → zoomToArea.
function populateToc() {
  if (!_layout || !_container || !_colorOf) return;
  const list = _container.querySelector('#net-toc-list');
  if (!list) return;
  const sorted = [..._layout.areas].sort(
    (a, b) => (b.weight || 0) - (a.weight || 0));
  list.innerHTML = sorted.map((a) => `
    <li>
      <button type="button" data-area="${escapeHtml(a.id)}" class="mvg-toc-row">
        <span class="mvg-toc-swatch" style="background:${_colorOf.get(a.id) || '#94a3b8'}"></span>
        <span class="mvg-toc-label">${escapeHtml(a.name)}</span>
        <span class="mvg-toc-count">${a.weight || 0}</span>
      </button>
    </li>`).join('');
  list.querySelectorAll('.mvg-toc-row').forEach((btn) => {
    btn.addEventListener('click', () => {
      zoomToArea(btn.dataset.area);
    });
  });
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
}
