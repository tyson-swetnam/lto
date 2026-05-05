// stats.js — Per-research-area knowledge-map dashboard.
//
// Replaces the old "three bar charts" stats view with a scrollable,
// per-area dashboard. Sticky table-of-contents on the left lists the
// 33 active research areas (post parent-collapse); clicking an area
// jumps to its section. Each section shows:
//
//   - Headline: area label + facility/people/funding totals
//   - Top-N facilities by total funding (FY2015-FY2024)
//   - Top-N researchers by composite z-score (pubs + citations + co-authors)
//   - Top funders for the area
//   - Coverage breakdown by country + by region overlay kind
//   - Gap callout when coverage is unusually thin in a dimension
//
// All metrics are precomputed by scripts/compute_area_metrics.py and
// served as parquet to the front end (read via DuckDB-Wasm). The
// renderStats(features) signature is preserved for main.js
// compatibility but the features arg is ignored — the dashboard pulls
// straight from DuckDB so it always reflects the full dataset, not
// the current map filters.

import { getConn, whenReady, unwrapRow } from '../db.js';
import { TYPE_COLORS } from '../map.js';

let _container = null;
let _renderedOnce = false;

const TOP_N_FACILITIES = 10;
const TOP_N_RESEARCHERS = 10;
const TOP_N_FUNDERS = 6;

// Match the 33-color palette used in the knowledge-map view.
const AREA_PALETTE = [
  '#7c3aed', '#0d9488', '#d97706', '#dc2626', '#2563eb',
  '#059669', '#a16207', '#9333ea', '#0891b2', '#65a30d',
  '#e11d48', '#0284c7', '#ca8a04', '#7e22ce', '#16a34a',
  '#b45309', '#1d4ed8', '#15803d', '#a21caf', '#be123c',
  '#0369a1', '#4d7c0f', '#be185d', '#1e40af', '#166534',
  '#86198f', '#1e3a8a', '#854d0e', '#5b21b6', '#0c4a6e',
  '#365314', '#3f6212', '#172554',
];

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function fmtUsd(n) {
  if (!n && n !== 0) return '—';
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3)  return `$${(n / 1e3).toFixed(0)}K`;
  return `$${Math.round(n)}`;
}
function fmtInt(n) {
  if (!n && n !== 0) return '—';
  return Math.round(n).toLocaleString();
}
function fmtZ(n) {
  if (!n && n !== 0) return '0.0';
  return n.toFixed(1);
}

// Convert any DuckDB-Wasm BigInt → Number wherever it's safe AND unwrap
// Arrow Vector list/struct values to plain JS arrays/objects. See
// src/db.js#unwrapRow for the rationale.
function numify(o) {
  return unwrapRow(o);
}

async function fetchAll() {
  await whenReady();
  const conn = getConn();
  if (!conn) throw new Error('DuckDB connection not ready');

  const queries = {
    areas: `
      SELECT area_id, label, n_facilities AS weight
      FROM   research_areas_active
      WHERE  collapsed_into IS NULL
      ORDER  BY n_facilities DESC, area_id`,

    // For per-area people counts.
    people_per_area: `
      SELECT primary_area_id AS area_id, COUNT(*) AS n_people
      FROM   person_primary_groups
      WHERE  primary_area_id IS NOT NULL
      GROUP  BY primary_area_id`,

    // Top facilities by total_usd_nominal per area (TOP_N each).
    top_facilities: `
      SELECT area_id, facility_id, facility_name, facility_acronym,
             country, n_funding_events, total_usd_nominal,
             n_distinct_funders, funder_top1_name, funder_top1_usd,
             min_fy, max_fy
      FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                 PARTITION BY area_id
                 ORDER BY total_usd_nominal DESC
               ) AS rk
        FROM facility_area_funding
      )
      WHERE rk <= ${TOP_N_FACILITIES}`,

    // Top researchers by composite_z per area (TOP_N each).
    top_researchers: `
      SELECT area_id, person_id, person_name,
             n_publications, total_citations, h_index, n_co_authors,
             composite_z
      FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                 PARTITION BY area_id
                 ORDER BY composite_z DESC, n_publications DESC
               ) AS rk
        FROM person_area_metrics
      )
      WHERE rk <= ${TOP_N_RESEARCHERS}`,

    // Top funders by total_usd per area.
    top_funders: `
      SELECT area_id, funder_id, funder_name, funder_type,
             n_facilities, n_events, total_usd
      FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                 PARTITION BY area_id
                 ORDER BY total_usd DESC
               ) AS rk
        FROM funder_area_funding
      )
      WHERE rk <= ${TOP_N_FUNDERS}`,

    // Coverage matrix: per area × dimension.
    coverage: `
      SELECT area_id, dim, bucket, n_facilities
      FROM   area_coverage_matrix
      WHERE  bucket IS NOT NULL`,

    // Per-area facility-funding totals so the dashboard can show
    // 'total $$ flowed into this area' even when individual top-10
    // rows roll up into something larger.
    area_funding_totals: `
      SELECT area_id,
             COUNT(DISTINCT facility_id)       AS n_funded_facilities,
             SUM(total_usd_nominal)            AS total_usd
      FROM   facility_area_funding
      GROUP  BY area_id`,
  };
  const out = {};
  for (const [k, sql] of Object.entries(queries)) {
    const r = await conn.query(sql);
    out[k] = r.toArray().map((row) => numify(row.toJSON()));
  }
  return out;
}


// ── Per-area subviews ───────────────────────────────────────────────
function totalsCard(area, peopleN, fundedN, totalUsd, color) {
  return `<div class="area-totals">
    <span class="t-pill" style="background:${color}1a;border-color:${color};color:${color}">
      <strong>${fmtInt(area.weight)}</strong> facilities
    </span>
    <span class="t-pill"><strong>${fmtInt(peopleN)}</strong> researchers</span>
    <span class="t-pill"><strong>${fmtInt(fundedN || 0)}</strong>
      facilities funded · ${fmtUsd(totalUsd)} total</span>
  </div>`;
}

function topFacilitiesTable(rows) {
  if (!rows.length) {
    return `<p class="no-data">No funding events recorded for this area's
      facilities yet.</p>`;
  }
  const header = `<thead><tr>
    <th>Facility</th><th>Country</th><th class="num">Events</th>
    <th class="num">Total $</th><th>Top funder</th>
    <th class="num">Funder $</th><th class="num">Years</th>
  </tr></thead>`;
  const body = rows.map((r) => `<tr>
    <td><strong>${esc(r.facility_acronym || '')}</strong>
        ${esc(r.facility_name || '')}</td>
    <td>${esc(r.country || '')}</td>
    <td class="num">${fmtInt(r.n_funding_events)}</td>
    <td class="num">${fmtUsd(r.total_usd_nominal)}</td>
    <td>${esc(r.funder_top1_name || '—')}</td>
    <td class="num">${fmtUsd(r.funder_top1_usd)}</td>
    <td class="num">${r.min_fy ? `FY${r.min_fy}–${r.max_fy}` : '—'}</td>
  </tr>`).join('');
  return `<table class="dash-table">${header}<tbody>${body}</tbody></table>`;
}

function topResearchersTable(rows) {
  if (!rows.length) {
    return `<p class="no-data">No publications mapped to this area yet
      (likely because the OpenAlex topic crosswalk doesn't cover it).</p>`;
  }
  const header = `<thead><tr>
    <th>Researcher</th>
    <th class="num">Pubs</th>
    <th class="num">Citations</th>
    <th class="num">h-index</th>
    <th class="num">Co-authors</th>
    <th class="num">Composite</th>
  </tr></thead>`;
  const body = rows.map((r) => `<tr>
    <td>${esc(r.person_name)}</td>
    <td class="num">${fmtInt(r.n_publications)}</td>
    <td class="num">${fmtInt(r.total_citations)}</td>
    <td class="num">${fmtInt(r.h_index)}</td>
    <td class="num">${fmtInt(r.n_co_authors)}</td>
    <td class="num"><strong>${fmtZ(r.composite_z)}</strong></td>
  </tr>`).join('');
  return `<table class="dash-table">${header}<tbody>${body}</tbody></table>`;
}

function topFundersTable(rows) {
  if (!rows.length) {
    return `<p class="no-data">No funder data for this area yet.</p>`;
  }
  const header = `<thead><tr>
    <th>Funder</th><th>Type</th>
    <th class="num">Facilities</th>
    <th class="num">Events</th>
    <th class="num">Total $</th>
  </tr></thead>`;
  const body = rows.map((r) => `<tr>
    <td>${esc(r.funder_name)}</td>
    <td><small>${esc(r.funder_type || '—')}</small></td>
    <td class="num">${fmtInt(r.n_facilities)}</td>
    <td class="num">${fmtInt(r.n_events)}</td>
    <td class="num">${fmtUsd(r.total_usd)}</td>
  </tr>`).join('');
  return `<table class="dash-table">${header}<tbody>${body}</tbody></table>`;
}

function coverageBars(coverageRows, dim, label, totalFacilities) {
  const rows = coverageRows.filter((r) => r.dim === dim)
    .sort((a, b) => (b.n_facilities || 0) - (a.n_facilities || 0));
  if (!rows.length) {
    return `<div class="cov-block">
      <h5>${esc(label)}</h5>
      <p class="no-data" style="font-size:.78rem">No data.</p>
    </div>`;
  }
  const max = Math.max(...rows.map((r) => r.n_facilities || 0));
  const items = rows.slice(0, 10).map((r) => {
    const pct = max ? Math.round(100 * r.n_facilities / max) : 0;
    return `<li class="cov-row">
      <span class="cov-label">${esc(r.bucket || '—')}</span>
      <span class="cov-bar" style="width:${pct}%"></span>
      <span class="cov-count">${fmtInt(r.n_facilities)}</span>
    </li>`;
  }).join('');
  return `<div class="cov-block">
    <h5>${esc(label)}</h5>
    <ul class="cov-list">${items}</ul>
  </div>`;
}

function gapCallouts(area, coverageRows, totalFacilities, peopleN) {
  const flags = [];
  if (totalFacilities < 5) {
    flags.push(`Only <strong>${totalFacilities}</strong> facilities tagged
      to this area — coverage gap candidate for a future observatory.`);
  }
  // Geographic concentration — single-country dominance
  const countries = coverageRows.filter((r) => r.dim === 'country');
  const sumC = countries.reduce((a, r) => a + (r.n_facilities || 0), 0);
  const topC = countries[0];
  if (topC && sumC > 0 && (topC.n_facilities / sumC) > 0.85
      && totalFacilities >= 5) {
    flags.push(`Heavy <strong>${esc(topC.bucket)}</strong> concentration
      (${Math.round(100 * topC.n_facilities / sumC)}% of facilities) —
      international representation under-served.`);
  }
  // Person:facility ratio
  if (peopleN && totalFacilities > 0) {
    const r = peopleN / totalFacilities;
    if (r < 0.4) {
      flags.push(`Low researcher density (${peopleN} researchers vs
        ${totalFacilities} facilities). Personnel records may be
        incomplete in this area.`);
    }
  }
  // No facility-type breakdown
  if (totalFacilities >= 5
      && !coverageRows.some((r) => r.dim === 'facility_type')) {
    flags.push('No facility-type breakdown available — investigate schema gap.');
  }
  if (!flags.length) return '';
  return `<aside class="gap-callout">
    <header>Coverage notes</header>
    <ul>${flags.map((f) => `<li>${f}</li>`).join('')}</ul>
  </aside>`;
}


// ── TOC + sections ─────────────────────────────────────────────────
function buildToc(areas, color) {
  const rows = areas.map((a, i) => `
    <li>
      <a href="#area-${esc(a.area_id)}">
        <span class="toc-swatch" style="background:${color(i)}"></span>
        <span class="toc-label">${esc(a.label)}</span>
        <span class="toc-count">${fmtInt(a.weight)}</span>
      </a>
    </li>`).join('');
  return `<aside class="dash-toc">
    <h3>Research areas</h3>
    <ol class="dash-toc-list">${rows}</ol>
    <p class="toc-foot">Click a polygon name to jump.</p>
  </aside>`;
}

function buildSection(area, idx, ix, color) {
  const peopleN = ix.peopleByArea.get(area.area_id) || 0;
  const tot = ix.fundingTotals.get(area.area_id) || {};
  const facs = ix.facilitiesByArea.get(area.area_id) || [];
  const ress = ix.researchersByArea.get(area.area_id) || [];
  const funds = ix.fundersByArea.get(area.area_id) || [];
  const cov = ix.coverageByArea.get(area.area_id) || [];

  return `<section id="area-${esc(area.area_id)}" class="area-card"
            style="--area-color:${color}">
    <header class="area-card-header">
      <div class="area-bar" style="background:${color}"></div>
      <div class="area-title">
        <h2>${esc(area.label)}</h2>
        <code class="area-slug">${esc(area.area_id)}</code>
      </div>
      ${totalsCard(area, peopleN, tot.n_funded_facilities, tot.total_usd, color)}
    </header>
    <div class="area-grid">
      <div class="dash-card">
        <h4>Top facilities by total funding (FY2015-FY2024)</h4>
        ${topFacilitiesTable(facs)}
      </div>
      <div class="dash-card">
        <h4>Top researchers (publications + citations + co-authors)</h4>
        <p class="dash-sub">Composite z-score within this area; raw
          metrics in the columns. Researcher → publication mapping
          comes from OpenAlex topic crosswalk.</p>
        ${topResearchersTable(ress)}
      </div>
      <div class="dash-card">
        <h4>Top funders</h4>
        ${topFundersTable(funds)}
      </div>
      <div class="dash-card dash-card-coverage">
        <h4>Coverage breakdown</h4>
        <div class="cov-grid">
          ${coverageBars(cov, 'country', 'By country', area.weight)}
          ${coverageBars(cov, 'region_kind', 'By region overlay', area.weight)}
          ${coverageBars(cov, 'facility_type', 'By facility type', area.weight)}
        </div>
        ${gapCallouts(area, cov, area.weight, peopleN)}
      </div>
    </div>
  </section>`;
}


// ── Entry point ────────────────────────────────────────────────────
async function renderDashboard() {
  if (!_container) return;
  const status = _container.querySelector('.dash-status');
  if (status) status.textContent = 'Loading per-area metrics…';

  let data;
  try {
    data = await fetchAll();
  } catch (e) {
    if (status) status.textContent = `Failed to load: ${e.message}`;
    console.error(e);
    return;
  }

  // Build lookups so each section render is O(1).
  const peopleByArea = new Map(
    data.people_per_area.map((r) => [r.area_id, r.n_people]));
  const fundingTotals = new Map(
    data.area_funding_totals.map((r) => [r.area_id, r]));
  const facilitiesByArea = new Map();
  for (const r of data.top_facilities) {
    (facilitiesByArea.get(r.area_id) || facilitiesByArea.set(r.area_id, []).get(r.area_id))
      .push(r);
  }
  const researchersByArea = new Map();
  for (const r of data.top_researchers) {
    (researchersByArea.get(r.area_id) || researchersByArea.set(r.area_id, []).get(r.area_id))
      .push(r);
  }
  const fundersByArea = new Map();
  for (const r of data.top_funders) {
    (fundersByArea.get(r.area_id) || fundersByArea.set(r.area_id, []).get(r.area_id))
      .push(r);
  }
  const coverageByArea = new Map();
  for (const r of data.coverage) {
    (coverageByArea.get(r.area_id) || coverageByArea.set(r.area_id, []).get(r.area_id))
      .push(r);
  }
  const ix = {
    peopleByArea, fundingTotals, facilitiesByArea, researchersByArea,
    fundersByArea, coverageByArea,
  };
  const colorFor = (i) => AREA_PALETTE[i % AREA_PALETTE.length];

  const sections = data.areas.map((a, i) => buildSection(a, i, ix, colorFor(i))).join('');
  const totalFacilities = data.areas.reduce((s, a) => s + (a.weight || 0), 0);
  const totalPeople = data.people_per_area.reduce((s, r) => s + (r.n_people || 0), 0);
  const totalFunding = [...fundingTotals.values()]
    .reduce((s, r) => s + (r.total_usd || 0), 0);

  _container.innerHTML = `
    <div class="dash-page">
      <header class="dash-header">
        <h1>Coastal observatory knowledge map — research-area dashboards</h1>
        <p class="dash-summary">
          <strong>${fmtInt(data.areas.length)}</strong> active research areas,
          <strong>${fmtInt(totalFacilities)}</strong> facilities (each tagged
          to its primary area),
          <strong>${fmtInt(totalPeople)}</strong> researchers,
          <strong>${fmtUsd(totalFunding)}</strong> in tracked grant funding
          across FY2015-FY2024.
        </p>
        <p class="dash-help">
          Each section below profiles one research area: who runs the work,
          where it happens, who funds it, and where the coverage gaps are.
          Use the table-of-contents on the left to jump between areas.
          Researcher composite scores are within-area z-scores summing
          publications, total citations, and unique co-author count, so
          the top names in <em>kelp-forests</em> are comparable to the top
          names in <em>climate-and-sea-level</em> on a same-scale basis.
        </p>
      </header>
      <div class="dash-layout">
        ${buildToc(data.areas, colorFor)}
        <div class="dash-sections">${sections}</div>
      </div>
      <p class="dash-status" style="text-align:center;color:#64748b">Done.</p>
    </div>`;
  _renderedOnce = true;
}


// ── Public API ─────────────────────────────────────────────────────
export function initStatsView(container) {
  _container = container;
  _container.innerHTML = `
    <div class="dash-page">
      <p class="dash-status" style="padding:24px;color:#64748b">
        Stats dashboard initialising — open this tab to load…
      </p>
    </div>`;
}

// renderStats(features) — features is ignored; we always render the
// full per-area dashboard from DuckDB. Keeps main.js compatible.
export function renderStats(_features) {
  if (!_container) return;
  // Don't refetch on every map filter change; only on first visit.
  if (_renderedOnce) return;
  renderDashboard().catch((e) => {
    console.error('[stats] dashboard render failed', e);
    if (_container) {
      const s = _container.querySelector('.dash-status');
      if (s) s.textContent = `Render failed: ${e.message}`;
    }
  });
}
