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

    // ── Person-registry panel (ported from cod-kmap, two-cohort) ─────
    registry_tiers: `SELECT tier,
             COUNT(*)                             AS identities,
             COUNT(orcid)                         AS with_orcid,
             ROUND(AVG(h_index), 1)               AS avg_h_index,
             COUNT(DISTINCT affiliation_country)  AS countries
      FROM   person_registry
      GROUP  BY tier`,

    // Cohort composition. Flags are not mutually exclusive, so
    // n_site + n_scholar can overshoot n_total by n_multi.
    registry_cohorts: `SELECT
             CAST(SUM(CASE WHEN is_site_personnel THEN 1 ELSE 0 END) AS DOUBLE) AS n_site,
             CAST(SUM(CASE WHEN is_scholar        THEN 1 ELSE 0 END) AS DOUBLE) AS n_scholar,
             CAST(SUM(CASE WHEN CAST(is_site_personnel AS INT)
                         + CAST(is_scholar AS INT) > 1
                      THEN 1 ELSE 0 END) AS DOUBLE)             AS n_multi,
             CAST(COUNT(*) AS DOUBLE)                           AS n_total
      FROM   person_registry`,

    // The people the pre-registry schema could not represent: one human
    // holding both cohort roles at once.
    registry_multi: `SELECT display_name AS researcher,
             CONCAT_WS(' + ',
               CASE WHEN is_site_personnel THEN 'Site personnel' END,
               CASE WHEN is_scholar        THEN 'Scholar'        END) AS cohorts,
             affiliation,
             affiliation_country AS country,
             h_index
      FROM   person_registry
      WHERE  is_site_personnel AND is_scholar
      ORDER  BY h_index DESC NULLS LAST, researcher`,

    registry_identifiers: `SELECT 'ORCID' AS identifier, COUNT(orcid) AS populated, COUNT(*) AS n_rows FROM person_registry
      UNION ALL SELECT 'OpenAlex author id', COUNT(openalex_id), COUNT(*) FROM person_registry
      UNION ALL SELECT 'ROR affiliation',    COUNT(affiliation_ror), COUNT(*) FROM person_registry
      UNION ALL SELECT 'Homepage URL',       COUNT(homepage_url), COUNT(*) FROM person_registry
      UNION ALL SELECT 'Google Scholar id',  COUNT(google_scholar_id), COUNT(*) FROM person_registry`,

    registry_countries: `SELECT COALESCE(affiliation_country, '(none)') AS country,
             COUNT(*)                                          AS researchers,
             CAST(SUM(CASE WHEN is_site_personnel THEN 1 ELSE 0 END) AS DOUBLE) AS site_personnel
      FROM   person_registry
      GROUP  BY country
      ORDER  BY researchers DESC, country`,

    registry_degree: `-- The co-authorship graph is built over identities that predate the
      -- OpenAlex topic harvest (recoverable from provenance: an identity
      -- with no 'openalex-topic-harvest' assertion was in scope for the
      -- graph build). That distinction is what lets this chart separate a
      -- measured zero from a node whose degree was never computed.
      WITH eligible AS (
        SELECT DISTINCT canonical_id
        FROM   person_identity_source
        WHERE  canonical_id NOT IN (
                 SELECT canonical_id FROM person_identity_source
                 WHERE  method = 'openalex-topic-harvest')
      ),
      deg AS (
        SELECT pr.canonical_id,
               pr.is_site_personnel,
               el.canonical_id IS NOT NULL AS measured,
               COUNT(e.canonical_id_a)     AS degree
        FROM   person_registry pr
        LEFT   JOIN eligible el ON el.canonical_id = pr.canonical_id
        LEFT   JOIN registry_collaborations e
               ON  e.canonical_id_a = pr.canonical_id
               OR  e.canonical_id_b = pr.canonical_id
        GROUP  BY pr.canonical_id, pr.is_site_personnel, measured
      )
      SELECT CASE WHEN NOT measured THEN 'not computed'
                  WHEN degree = 0   THEN '0 (measured)'
                  WHEN degree <= 5  THEN '1-5'
                  WHEN degree <= 20 THEN '6-20'
                  WHEN degree <= 50 THEN '21-50'
                  ELSE '51+' END                        AS band,
             COUNT(*)                                   AS researchers,
             CAST(SUM(CASE WHEN is_site_personnel THEN 1 ELSE 0 END) AS DOUBLE) AS site_members
      FROM   deg
      GROUP  BY band
      ORDER  BY CASE band WHEN 'not computed' THEN 9 WHEN '0 (measured)' THEN 0
                          WHEN '1-5' THEN 1 WHEN '6-20' THEN 2
                          WHEN '21-50' THEN 3 ELSE 4 END`,

    // Denominators for the degree chart's caveat line.
    registry_graph_scope: `WITH eligible AS (
        SELECT DISTINCT canonical_id
        FROM   person_identity_source
        WHERE  canonical_id NOT IN (
                 SELECT canonical_id FROM person_identity_source
                 WHERE  method = 'openalex-topic-harvest')
      ),
      in_graph AS (
        SELECT canonical_id_a AS canonical_id FROM registry_collaborations
        UNION
        SELECT canonical_id_b FROM registry_collaborations
      )
      SELECT (SELECT COUNT(*) FROM person_registry)                    AS n_rows,
             (SELECT COUNT(*) FROM eligible el
              WHERE el.canonical_id IN (SELECT canonical_id FROM person_registry))
                                                                       AS n_eligible,
             (SELECT COUNT(*) FROM in_graph)                           AS n_with_edges,
             (SELECT COUNT(*) FROM registry_collaborations)            AS n_edges`,

    registry_edge_census: `WITH labelled AS (
        SELECT CASE WHEN a.is_site_personnel THEN 'Site personnel'
                    ELSE 'Scholar' END AS role_a,
               CASE WHEN b.is_site_personnel THEN 'Site personnel'
                    ELSE 'Scholar' END AS role_b,
               e.co_pub_count
        FROM   registry_collaborations e
        JOIN   person_registry a ON a.canonical_id = e.canonical_id_a
        JOIN   person_registry b ON b.canonical_id = e.canonical_id_b
      )
      SELECT LEAST(role_a, role_b) || ' ↔ ' || GREATEST(role_a, role_b) AS edge_type,
             COUNT(*)          AS edges,
             CAST(SUM(co_pub_count) AS DOUBLE) AS co_pubs,
             MAX(co_pub_count) AS strongest
      FROM   labelled
      GROUP  BY edge_type
      ORDER  BY edges DESC`,

    registry_top_edges: `SELECT a.display_name AS person_a,
             CASE WHEN a.is_site_personnel THEN 'Site' ELSE 'Scholar' END AS cohort_a,
             b.display_name AS person_b,
             CASE WHEN b.is_site_personnel THEN 'Site' ELSE 'Scholar' END AS cohort_b,
             e.co_pub_count AS co_pubs,
             e.first_year, e.last_year
      FROM   registry_collaborations e
      JOIN   person_registry a ON a.canonical_id = e.canonical_id_a
      JOIN   person_registry b ON b.canonical_id = e.canonical_id_b
      ORDER  BY e.co_pub_count DESC
      LIMIT  10`,

    registry_sites: `SELECT f.canonical_name                AS site,
             f.acronym,
             f.country,
             COUNT(DISTINCT rf.canonical_id) AS researchers,
             ROUND(AVG(pr.h_index), 1)       AS avg_h_index
      FROM   registry_facilities rf
      JOIN   facilities      f  ON f.facility_id   = rf.facility_id
      JOIN   person_registry pr ON pr.canonical_id = rf.canonical_id
      GROUP  BY f.canonical_name, f.acronym, f.country
      ORDER  BY researchers DESC, site`,

    // ROR coverage on the facility side, split so places — flux towers,
    // gauging stations, wilderness areas — are not counted as a coverage
    // failure. Keep this type list in step with PLACE_TYPES in
    // scripts/link_registry_facilities.py.
    registry_ror_coverage: `SELECT CASE
                  WHEN f.facility_type IN (
                    'protected-area-federal', 'protected-area-state',
                    'protected-area-private', 'experimental-forest-range',
                    'ltar-site', 'flux-tower', 'glacier-monitoring',
                    'atmospheric-baseline', 'streamgage-network', 'vessel')
                  THEN 'place (a ROR will never apply)'
                  WHEN f.ror IS NOT NULL THEN 'organisation, ROR resolved'
                  ELSE 'organisation, ROR not yet attempted' END AS ror_status,
             COUNT(*)                                            AS facilities
      FROM   facilities f
      GROUP  BY ror_status
      ORDER  BY facilities DESC`,
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


// ── Person-registry panel (ported from cod-kmap, two-cohort) ────────
function barList(rows, labelKey, valueKey, opts = {}) {
  if (!rows.length) return `<p class="no-data">No rows.</p>`;
  const max = Math.max(...rows.map((r) => Number(r[valueKey]) || 0), 1);
  const items = rows.map((r) => {
    const v = Number(r[valueKey]) || 0;
    const pct = Math.round(100 * v / max);
    const muted = opts.mutedWhen && opts.mutedWhen(r);
    return `<li class="cov-row"${muted ? ' style="opacity:.62"' : ''}>
      <span class="cov-label">${esc(r[labelKey] ?? '—')}</span>
      <span class="cov-bar" style="width:${pct}%${
  muted ? ';background:#94a3b8' : ''}"></span>
      <span class="cov-count">${fmtInt(v)}${
  opts.suffix ? esc(opts.suffix(r)) : ''}</span>
    </li>`;
  }).join('');
  return `<ul class="cov-list">${items}</ul>`;
}

// Cohort composition. The flags overlap, so the two cohort counts can sum
// past the total; the card states the overlap rather than hiding it.
function registryCohortCard(cohorts, tiers, multi) {
  const c = cohorts[0] || {};
  const shipped = tiers.reduce((s, t) => s + (Number(t.identities) || 0), 0);
  const tierNames = tiers.map((t) => t.tier).sort();
  const onlyCore = tierNames.length === 1 && tierNames[0] === 'core';

  const multiRows = multi.slice(0, 12).map((r) => `<tr>
    <td>${esc(r.researcher)}</td>
    <td><small>${esc(r.cohorts)}</small></td>
    <td><small>${esc(r.affiliation || '—')}</small></td>
    <td class="num">${fmtInt(r.h_index)}</td>
  </tr>`).join('');

  return `<div class="dash-card">
    <h4>Cohort composition</h4>
    <p class="dash-sub">
      ${onlyCore
    ? `This page is served the registry's <code>core</code> tier:
           <strong>${fmtInt(shipped)}</strong> identities. The archive
           tier (the field-wide OpenAlex harvest) stays in the local
           catalogue — everything below describes the shipped subset.`
    : `Tiers in scope: ${esc(tierNames.join(', '))} —
           <strong>${fmtInt(shipped)}</strong> identities.`}
    </p>
    ${barList([
    { k: 'Site personnel', v: c.n_site },
    { k: 'Scholar harvest', v: c.n_scholar },
  ], 'k', 'v')}
    <p class="dash-sub" style="margin-top:8px">
      The two flags are independent, not a partition:
      <strong>${fmtInt(c.n_multi)}</strong> people carry both, so the bars
      can sum past the ${fmtInt(c.n_total)} rows in scope. Rows merge only
      on ORCID or OpenAlex-id equality — never on name.
    </p>
    ${multi.length ? `<table class="dash-table">
      <thead><tr><th>Researcher</th><th>Cohorts</th><th>Affiliation</th>
        <th class="num">h-index</th></tr></thead>
      <tbody>${multiRows}</tbody></table>` : ''}
  </div>`;
}

function registryIdentifierCard(rows) {
  const items = rows.map((r) => ({
    identifier: r.identifier,
    populated: r.populated,
    pct: r.n_rows ? (100 * Number(r.populated) / Number(r.n_rows)) : 0,
    n_rows: r.n_rows,
  })).sort((a, b) => b.populated - a.populated);
  const denom = items.length ? Number(items[0].n_rows) : 0;
  return `<div class="dash-card">
    <h4>Persistent-identifier coverage</h4>
    <p class="dash-sub">
      Of the <strong>${fmtInt(denom)}</strong> rows in scope. Every
      registry row carries at least one of ORCID / OpenAlex id by
      construction — people lacking both stay in <code>people</code>
      until the enrichment scripts resolve one.
    </p>
    ${barList(items, 'identifier', 'populated',
    { suffix: (r) => `  ${r.pct.toFixed(1)}%` })}
    <p class="dash-sub" style="margin-top:8px">
      Google Scholar ids are effectively absent: OpenAlex does not
      populate <code>ids.scholar</code> for most authors, so that column
      needs a different source or hand curation.
    </p>
  </div>`;
}

function registryCountryCard(rows) {
  const total = rows.reduce((s, r) => s + (Number(r.researchers) || 0), 0);
  const named = rows.filter((r) => r.country !== '(none)');
  const top = rows.slice(0, 12);
  return `<div class="dash-card">
    <h4>Country distribution</h4>
    <p class="dash-sub">
      ${fmtInt(named.length)} countries across ${fmtInt(total)} identities
      in scope.
    </p>
    ${barList(top, 'country', 'researchers',
    { mutedWhen: (r) => r.country === '(none)' })}
    <p class="dash-sub" style="margin-top:8px">
      Affiliation country comes from the researcher's OpenAlex
      institution, so a row reads <code>(none)</code> when no
      ROR-bearing institution was attached — not when the person has no
      country.
    </p>
  </div>`;
}

// Degree distribution. The 'not computed' band is the whole point of
// this chart: it must never read as "these people publish alone".
function registryDegreeCard(bands, scope) {
  const s = scope[0] || {};
  const uncomputed = bands.find((b) => b.band === 'not computed');
  const measuredZero = bands.find((b) => b.band === '0 (measured)');
  const measured = bands.filter((b) => b.band !== 'not computed');
  const measuredTotal = measured.reduce((a, b) => a + (Number(b.researchers) || 0), 0);
  return `<div class="dash-card">
    <h4>Co-authorship degree distribution</h4>
    <p class="dash-sub">
      The graph holds <strong>${fmtInt(s.n_edges)}</strong> edges over
      <strong>${fmtInt(s.n_with_edges)}</strong> nodes, built over the
      <strong>${fmtInt(s.n_eligible)}</strong> identities that predate
      the OpenAlex topic harvest — ${fmtInt(measuredTotal)} of the
      ${fmtInt(s.n_rows)} rows in scope have a degree at all.
    </p>
    ${barList(bands, 'band', 'researchers', {
    mutedWhen: (r) => r.band === 'not computed',
    suffix: (r) => Number(r.site_members) > 0
      ? `  (${fmtInt(r.site_members)} site)` : '',
  })}
    <aside class="gap-callout">
      <header>Read this band correctly</header>
      <ul>
        <li><strong>${fmtInt(uncomputed ? uncomputed.researchers : 0)}</strong>
          researchers sit in <em>not computed</em> (grey). No edge was
          calculated for them — a measurement boundary, <strong>not</strong>
          evidence that they have no collaborators.</li>
        <li><strong>${fmtInt(measuredZero ? measuredZero.researchers : 0)}</strong>
          researchers were in scope and came back with zero edges. Those
          are real zeroes within this graph's coverage.</li>
      </ul>
    </aside>
  </div>`;
}

function registryEdgeCensusCard(census, topEdges) {
  const rows = census.map((r) => `<tr>
    <td>${esc(r.edge_type)}</td>
    <td class="num">${fmtInt(r.edges)}</td>
    <td class="num">${fmtInt(r.co_pubs)}</td>
    <td class="num">${fmtInt(r.strongest)}</td>
  </tr>`).join('');
  const edgeRows = topEdges.map((r) => `<tr>
    <td>${esc(r.person_a)} <small>(${esc(r.cohort_a)})</small></td>
    <td>${esc(r.person_b)} <small>(${esc(r.cohort_b)})</small></td>
    <td class="num">${fmtInt(r.co_pubs)}</td>
    <td class="num"><small>${r.first_year ? `${r.first_year}–${r.last_year}` : '—'}</small></td>
  </tr>`).join('');
  return `<div class="dash-card">
    <h4>Cross-cohort edge census</h4>
    <p class="dash-sub">
      Each edge classified by the cohort pair at its ends. The old
      <code>collaborations</code> table was keyed on
      <code>people(person_id)</code> and structurally could not hold an
      edge to a harvested-only researcher; this one can.
      ${census.length ? '' : `<em>No edges yet — they land with the M5
      works harvest (compute_registry_collaborations.py).</em>`}
    </p>
    ${census.length ? `<table class="dash-table">
      <thead><tr><th>Edge type</th><th class="num">Edges</th>
        <th class="num">Co-pubs</th><th class="num">Strongest</th></tr></thead>
      <tbody>${rows}</tbody></table>` : ''}
    ${topEdges.length ? `
    <h5 style="margin:14px 0 4px;font-size:.78rem;color:#475569">Strongest edges</h5>
    <table class="dash-table">
      <thead><tr><th>Researcher</th><th>Researcher</th>
        <th class="num">Co-pubs</th><th class="num">Span</th></tr></thead>
      <tbody>${edgeRows}</tbody></table>` : ''}
  </div>`;
}

function registrySiteCard(sites, rorCoverage) {
  const nResearchers = sites.reduce((s, r) => s + (Number(r.researchers) || 0), 0);
  const resolved = rorCoverage.find((r) => /resolved/.test(r.ror_status || ''));
  const pending = rorCoverage.find((r) => /not yet/.test(r.ror_status || ''));
  const places = rorCoverage.find((r) => /place/.test(r.ror_status || ''));
  const rows = sites.slice(0, 12).map((r) => `<tr>
    <td><strong>${esc(r.acronym || '')}</strong> ${esc(r.site || '')}</td>
    <td>${esc(r.country || '')}</td>
    <td class="num">${fmtInt(r.researchers)}</td>
    <td class="num">${fmtZ(Number(r.avg_h_index))}</td>
  </tr>`).join('');
  return `<div class="dash-card">
    <h4>Researchers resolved to sites</h4>
    <p class="dash-sub">
      <strong>${fmtInt(nResearchers)}</strong> researcher↔site links across
      <strong>${fmtInt(sites.length)}</strong> sites, joined on ROR
      equality alone — no name matching. Every count is a floor:
      <strong>${fmtInt(resolved ? resolved.facilities : 0)}</strong>
      organisations have a resolved ROR against
      ${fmtInt(pending ? pending.facilities : 0)} not yet attempted
      (the backfill is harvest step H10), and the researcher side is
      limited to the tier in scope.
    </p>
    ${barList(rorCoverage, 'ror_status', 'facilities',
    { mutedWhen: (r) => /place/.test(r.ror_status || '') })}
    <p class="dash-sub" style="margin-top:8px">
      The ${fmtInt(places ? places.facilities : 0)} place-type facilities
      (grey) — flux towers, gauging stations, wilderness areas — are
      excluded by design, not missing: a place is not an organisation and
      will never hold a ROR; its operator might.
    </p>
    ${sites.length ? `<table class="dash-table">
      <thead><tr><th>Site</th><th>Country</th>
        <th class="num">Researchers</th><th class="num">Avg h-index</th></tr></thead>
      <tbody>${rows}</tbody></table>` : ''}
  </div>`;
}

function buildRegistryPanel(d) {
  const s = d.registry_graph_scope[0] || {};
  return `<section id="registry-panel" class="area-card">
    <header class="area-card-header">
      <div class="area-bar" style="background:#0f766e"></div>
      <div class="area-title">
        <h2>The people layer</h2>
        <code class="area-slug">person_registry</code>
      </div>
      <div class="area-totals">
        <span class="t-pill" style="background:#0f766e1a;border-color:#0f766e;color:#0f766e">
          <strong>${fmtInt(s.n_rows)}</strong> identities in scope
        </span>
        <span class="t-pill"><strong>${fmtInt(s.n_edges)}</strong>
          co-publication edges</span>
        <span class="t-pill"><strong>${fmtInt(s.n_with_edges)}</strong>
          nodes with an edge</span>
      </div>
    </header>
    <p class="dash-help">
      One row per human, keyed on a persistent identifier
      (<code>canonical_id</code>), unifying facility site personnel with
      the field-wide researcher harvest. Two rows merge only on ORCID or
      OpenAlex-id equality; names never merge. Bibliometric columns come
      from OpenAlex, so <strong>LTO-topic output volume is an upper
      bound</strong>, not a paper count — OpenAlex lists a work under
      every topic it carries, and summing across the LTO topic set counts
      multi-topic papers more than once.
    </p>
    <div class="area-grid">
      ${registryCohortCard(d.registry_cohorts, d.registry_tiers, d.registry_multi)}
      ${registryIdentifierCard(d.registry_identifiers)}
      ${registryCountryCard(d.registry_countries)}
      ${registryDegreeCard(d.registry_degree, d.registry_graph_scope)}
      ${registryEdgeCensusCard(d.registry_edge_census, d.registry_top_edges)}
      ${registrySiteCard(d.registry_sites, d.registry_ror_coverage)}
    </div>
  </section>`;
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
    <h3>People</h3>
    <ol class="dash-toc-list">
      <li>
        <a href="#registry-panel">
          <span class="toc-swatch" style="background:#0f766e"></span>
          <span class="toc-label">The people layer</span>
        </a>
      </li>
    </ol>
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

  const registryPanel = buildRegistryPanel(data);
  const sections = data.areas.map((a, i) => buildSection(a, i, ix, colorFor(i))).join('');
  const totalFacilities = data.areas.reduce((s, a) => s + (a.weight || 0), 0);
  const totalPeople = data.people_per_area.reduce((s, r) => s + (r.n_people || 0), 0);
  const totalFunding = [...fundingTotals.values()]
    .reduce((s, r) => s + (r.total_usd || 0), 0);

  _container.innerHTML = `
    <div class="dash-page">
      <header class="dash-header">
        <h1>U.S. long-term observatories — research-area dashboards</h1>
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
        <div class="dash-sections">${registryPanel}${sections}</div>
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
