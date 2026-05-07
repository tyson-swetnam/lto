// list.js — Browse view: card-based rich-data facility browser.
//
// Mirrors the People tab pattern: parent code passes a filtered set of
// `features` (GeoJSON Features, basic props from facilities.parquet),
// we extract their facility_ids and run a single SQL query against
// DuckDB-Wasm to enrich each card with archives, data products,
// personnel, publications, and funding aggregates.
//
// Card sections (collapsible visually via CSS, all visible by default):
//   • Header: name, acronym, primary sphere chip, secondary sphere chips
//   • Metrics row: established year, record-length, archives count,
//     products count, personnel count, publications count, funding total
//   • Networks: pill-list of network memberships (LTER, NEON, EFR, …)
//   • Data archives: top-3 archives + scope_url + sample_doi
//   • Personnel: top-3 with role + ORCID link
//   • Funding: top-3 funders + amounts
//   • Links: facility URL, data portal URL

import { getConn, query, unwrapRow, whenReady } from '../db.js';
import { TYPE_COLORS } from '../map.js';
import { DATA_BASE } from '../config.js';

let _container = null;
let _features = [];
let _sortKey = 'composite';
let _searchTerm = '';

const PAGE_SIZE = 60;
let _renderLimit = PAGE_SIZE;

const SORT_OPTIONS = [
  { key: 'composite',    label: 'Most-developed first' },
  { key: 'name',         label: 'Name (A→Z)' },
  { key: 'established',  label: 'Oldest first' },
  { key: 'record',       label: 'Longest record' },
  { key: 'pubs',         label: 'Most publications' },
  { key: 'archives',     label: 'Most data archives' },
  { key: 'funding',      label: 'Highest funding $' },
];

const SPHERE_LABELS = {
  'atmosphere':       'Atmosphere',
  'cryosphere':       'Cryosphere',
  'terrestrial':      'Terrestrial',
  'agriculture':      'Agriculture',
  'ocean-estuarine':  'Ocean / Estuarine',
  'freshwater':       'Freshwater',
};

const SPHERE_COLORS = {
  'atmosphere':       '#5DADE2',
  'cryosphere':       '#AED6F1',
  'terrestrial':      '#52BE80',
  'agriculture':      '#F4D03F',
  'ocean-estuarine':  '#1F618D',
  'freshwater':       '#48C9B0',
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function fmtInt(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '0';
  return Number(n).toLocaleString();
}

function fmtUsd(n) {
  if (!n) return '—';
  const v = Number(n);
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}k`;
  return `$${v}`;
}

// Parent passes GeoJSON features keyed on `id`; the SQL view's
// canonical column is also `id` (from v_facility_map).
function featureIds(features) {
  const ids = [];
  for (const f of features) {
    const p = f.properties || f;
    if (p.id) ids.push(p.id);
  }
  return ids;
}

// Module-level cache of the full pre-computed browse-card array. We
// fetch the static JSON once and filter in memory by id; subsequent
// renders never hit the network again. Falls through to DuckDB only if
// the cache file is missing.
let _allCardsPromise = null;
function loadAllCardsOnce() {
  if (_allCardsPromise) return _allCardsPromise;
  _allCardsPromise = fetch(`${DATA_BASE}cache/browse_cards.json`,
    { cache: 'force-cache' })
    .then((r) => r.ok ? r.json() : Promise.reject(new Error(`cache ${r.status}`)))
    .catch((err) => {
      // Reset so a future call can retry; don't let one failed fetch
      // permanently disable the fast path.
      _allCardsPromise = null;
      throw err;
    });
  return _allCardsPromise;
}

async function fetchEnrichedFacilities(ids) {
  if (!ids.length) return [];

  // Fast path: load the full pre-computed cards JSON once, then filter
  // by the visible-id set in memory. The cache is the SAME data this
  // function's DuckDB query produces, just materialised offline by
  // scripts/export_view_caches.py. Mobile-friendly: one HTTP request,
  // gzip ~150KB, parses in tens of ms.
  try {
    const all = await loadAllCardsOnce();
    const want = new Set(ids);
    return all.filter((c) => want.has(c.id));
  } catch (_) { /* fall through to DuckDB */ }

  // Parent code may call renderList before DuckDB-Wasm finished
  // initialising (see main.js renderAll → renderList during the very
  // first paint). Wait for the connection so we don't throw.
  await whenReady();
  const conn = getConn();
  if (!conn) throw new Error('DuckDB connection not ready');

  // Pass IDs as a placeholder array. DuckDB-Wasm's prepared-statement
  // path balks on long IN-lists, so we inline the values via the
  // `read_csv_auto` trick — turn the array into a one-column CSV blob.
  // For ≤2000 ids we just use IN with a literal string built from
  // sanitised hex IDs (facility_id = sha1[:16]). Defend against any
  // non-hex characters by allow-listing.
  const cleanIds = ids.filter((s) => /^[0-9a-f]+$/i.test(String(s).trim()));
  if (!cleanIds.length) return [];
  const inList = cleanIds.map((s) => `'${s}'`).join(',');

  const sql = `
    WITH base AS (
      SELECT f.facility_id        AS id,
             f.canonical_name     AS name,
             f.acronym,
             f.facility_type      AS type,
             f.country,
             f.region,
             f.hq_lat             AS lat,
             f.hq_lng             AS lng,
             f.url,
             f.parent_org,
             f.established,
             f.record_length_years,
             f.long_term_threshold_met,
             f.data_portal_url,
             (SELECT sphere_slug FROM facility_spheres
              WHERE facility_id = f.facility_id AND role = 'primary'
              LIMIT 1)            AS primary_sphere,
             (SELECT list(sphere_slug) FROM facility_spheres
              WHERE facility_id = f.facility_id AND role = 'secondary')
                                  AS secondary_spheres
      FROM facilities f
      WHERE f.facility_id IN (${inList})
    ),
    nets AS (
      SELECT nm.facility_id,
             list(struct_pack(slug := n.network_id, label := n.label, url := n.url))
                                  AS networks
      FROM network_membership nm
      JOIN networks n ON n.network_id = nm.network_id
      GROUP BY nm.facility_id
    ),
    archives AS (
      SELECT fa.facility_id,
             count(DISTINCT fa.archive_id) AS n_archives,
             list(struct_pack(
               archive_id := fa.archive_id,
               name       := da.name,
               base_url   := da.base_url,
               scope_url  := fa.scope_url,
               sample_doi := fa.sample_doi
             ) ORDER BY da.name) AS archive_list
      FROM facility_archives fa
      LEFT JOIN data_archives da ON da.archive_id = fa.archive_id
      GROUP BY fa.facility_id
    ),
    products AS (
      SELECT facility_id, count(*) AS n_products
      FROM data_products GROUP BY facility_id
    ),
    personnel AS (
      SELECT fp.facility_id,
             count(DISTINCT fp.person_id) AS n_personnel,
             list(struct_pack(
               person_id := p.person_id,
               name      := p.name,
               role      := fp.role,
               title     := fp.title,
               orcid     := p.orcid,
               openalex  := p.openalex_id,
               homepage  := p.homepage_url,
               is_key    := fp.is_key_personnel
             ) ORDER BY fp.is_key_personnel DESC, fp.role) AS personnel_list
      FROM facility_personnel fp
      JOIN people p ON p.person_id = fp.person_id
      GROUP BY fp.facility_id
    ),
    pubs AS (
      SELECT fp.facility_id,
             count(DISTINCT a.publication_id) AS n_pubs
      FROM authorship a
      JOIN facility_personnel fp ON fp.person_id = a.person_id
      GROUP BY fp.facility_id
    ),
    funding AS (
      SELECT fe.facility_id,
             count(*) AS n_funding,
             sum(coalesce(fe.amount_usd, 0)) AS total_funding,
             list(struct_pack(
               funder := fr.name,
               program := fe.program,
               amount := fe.amount_usd,
               fy := fe.fiscal_year
             ) ORDER BY coalesce(fe.amount_usd, 0) DESC) AS funding_list
      FROM funding_events fe
      JOIN funders fr ON fr.funder_id = fe.funder_id
      GROUP BY fe.facility_id
    )
    SELECT b.*,
           coalesce(n.networks, [])                  AS networks,
           coalesce(a.n_archives, 0)                 AS n_archives,
           coalesce(a.archive_list, [])              AS archive_list,
           coalesce(pr.n_products, 0)                AS n_products,
           coalesce(pe.n_personnel, 0)               AS n_personnel,
           coalesce(pe.personnel_list, [])           AS personnel_list,
           coalesce(pu.n_pubs, 0)                    AS n_pubs,
           coalesce(fu.n_funding, 0)                 AS n_funding,
           coalesce(fu.total_funding, 0)             AS total_funding,
           coalesce(fu.funding_list, [])             AS funding_list
    FROM base b
    LEFT JOIN nets      n  ON n.facility_id  = b.id
    LEFT JOIN archives  a  ON a.facility_id  = b.id
    LEFT JOIN products  pr ON pr.facility_id = b.id
    LEFT JOIN personnel pe ON pe.facility_id = b.id
    LEFT JOIN pubs      pu ON pu.facility_id = b.id
    LEFT JOIN funding   fu ON fu.facility_id = b.id
  `;

  const r = await conn.query(sql);
  return r.toArray().map((row) => unwrapRow(row.toJSON()));
}

function compositeScore(f) {
  // weighted sum of "developedness" — favours facilities with a richer
  // record of personnel, publications, and data products
  return (
    (f.n_archives    || 0) * 3 +
    (f.n_products    || 0) * 2 +
    (f.n_personnel   || 0) * 2 +
    (f.n_pubs        || 0) * 1 +
    Math.log10((Number(f.total_funding) || 0) + 1) * 5 +
    (f.long_term_threshold_met ? 2 : 0)
  );
}

function sortFacilities(rows, key) {
  const arr = rows.slice();
  switch (key) {
    case 'name':
      arr.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
      break;
    case 'established':
      arr.sort((a, b) =>
        (a.established || 9999) - (b.established || 9999)
        || (a.name || '').localeCompare(b.name || ''));
      break;
    case 'record':
      arr.sort((a, b) => (b.record_length_years || 0) - (a.record_length_years || 0));
      break;
    case 'pubs':
      arr.sort((a, b) => (b.n_pubs || 0) - (a.n_pubs || 0));
      break;
    case 'archives':
      arr.sort((a, b) => (b.n_archives || 0) - (a.n_archives || 0));
      break;
    case 'funding':
      arr.sort((a, b) => Number(b.total_funding || 0) - Number(a.total_funding || 0));
      break;
    case 'composite':
    default:
      arr.sort((a, b) => compositeScore(b) - compositeScore(a));
  }
  return arr;
}

function applySearch(rows, term) {
  if (!term) return rows;
  const t = term.toLowerCase();
  return rows.filter((f) => {
    const hay = [
      f.name, f.acronym, f.parent_org, f.region, f.country,
      f.primary_sphere, f.type,
      ...((f.networks || []).map((n) => `${n.slug} ${n.label}`)),
      ...((f.personnel_list || []).map((p) => p.name)),
    ].join(' ').toLowerCase();
    return hay.includes(t);
  });
}

function sphereChip(slug) {
  if (!slug) return '';
  const color = SPHERE_COLORS[slug] || '#94a3b8';
  return `<span class="brw-sphere-chip" style="background:${color}">${esc(SPHERE_LABELS[slug] || slug)}</span>`;
}

function metricCell(value, label) {
  return `<span class="brw-metric"><strong>${value}</strong><br>${label}</span>`;
}

// Long-record tier badge. Picks the highest qualifying tier from
// {10, 20, 30, 40, 50, 75, 100, 125, 150, 175, 200} and renders a
// colour-coded chip. Years come from record_length_years if set,
// else 2026 - established, else no badge.
const RECORD_TIERS = [200, 175, 150, 125, 100, 75, 50, 40, 30, 20, 10];
function recordTierBadge(f) {
  const yrs = Number.isFinite(f.record_length_years)
    ? f.record_length_years
    : (Number.isFinite(f.established) ? 2026 - f.established : null);
  if (yrs == null || yrs < 10) return '';
  const tier = RECORD_TIERS.find((t) => yrs >= t);
  return `<span class="brw-lt-badge brw-lt-${tier}" `
       + `title="≥${tier}-year record (${yrs} years; Peters 2013 threshold)">`
       + `≥${tier}y</span>`;
}

function cardHtml(f) {
  const typeColor = TYPE_COLORS?.[f.type] || '#64748b';
  const networks = (f.networks || []).slice(0, 8);
  const moreNetworks = (f.networks || []).length - networks.length;

  const archives = (f.archive_list || []).slice(0, 3);
  const moreArchives = (f.archive_list || []).length - archives.length;

  const personnel = (f.personnel_list || []).slice(0, 3);
  const morePersonnel = (f.personnel_list || []).length - personnel.length;

  const funding = (f.funding_list || []).filter((x) => x && x.amount).slice(0, 3);

  // Header line
  const acronymBadge = f.acronym
    ? `<span class="brw-acronym">${esc(f.acronym)}</span>` : '';
  const sphereChips = [
    sphereChip(f.primary_sphere),
    ...(f.secondary_spheres || []).map((s) => sphereChip(s).replace('brw-sphere-chip', 'brw-sphere-chip brw-sphere-secondary')),
  ].join('');

  const recordBadge = recordTierBadge(f);

  // Metrics row
  const established = f.established ? `${f.established}` : '—';
  const recordYears = f.record_length_years ? `${f.record_length_years}y` : '—';
  const metricsRow = `
    <div class="brw-metrics">
      ${metricCell(esc(established), 'established')}
      ${metricCell(esc(recordYears), 'record')}
      ${metricCell(fmtInt(f.n_archives), 'archives')}
      ${metricCell(fmtInt(f.n_products), 'datasets')}
      ${metricCell(fmtInt(f.n_personnel), 'personnel')}
      ${metricCell(fmtInt(f.n_pubs), 'pubs')}
      ${metricCell(fmtUsd(f.total_funding), 'funding')}
    </div>`;

  // Networks
  const networksHtml = networks.length
    ? `<div class="brw-section">
         <h4>Networks</h4>
         <ul class="brw-pills">
           ${networks.map((n) => `<li class="brw-pill" title="${esc(n.label || '')}">${esc((n.slug || '').toUpperCase())}</li>`).join('')}
           ${moreNetworks > 0 ? `<li class="brw-more">+${moreNetworks}</li>` : ''}
         </ul>
       </div>`
    : '';

  // Archives
  const archivesHtml = archives.length
    ? `<div class="brw-section">
         <h4>Data archives</h4>
         <ul class="brw-archives">
           ${archives.map((a) => {
             const label = a.name || a.archive_id;
             const href = a.scope_url || a.base_url;
             const link = href ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(label)}</a>` : esc(label);
             const doi = a.sample_doi
               ? ` · <a href="https://doi.org/${esc(a.sample_doi)}" target="_blank" rel="noopener">${esc(a.sample_doi)}</a>`
               : '';
             return `<li>${link}${doi}</li>`;
           }).join('')}
           ${moreArchives > 0 ? `<li class="brw-more">+${moreArchives} more</li>` : ''}
         </ul>
       </div>`
    : '';

  // Personnel
  const personnelHtml = personnel.length
    ? `<div class="brw-section">
         <h4>Key personnel</h4>
         <ul class="brw-people">
           ${personnel.map((p) => {
             const orcid = p.orcid
               ? ` <a href="https://orcid.org/${esc(p.orcid)}" target="_blank" rel="noopener" title="ORCID">⚙</a>` : '';
             const home = p.homepage
               ? `<a href="${esc(p.homepage)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name);
             return `<li>
               <strong>${esc(p.role || '')}</strong> ${home}${orcid}
               ${p.title ? `<br><small>${esc(p.title)}</small>` : ''}
             </li>`;
           }).join('')}
           ${morePersonnel > 0 ? `<li class="brw-more">+${morePersonnel} more</li>` : ''}
         </ul>
       </div>`
    : '';

  // Funding
  const fundingHtml = funding.length
    ? `<div class="brw-section">
         <h4>Funding (recent)</h4>
         <ul class="brw-funding">
           ${funding.map((x) => `<li>
             <strong>${fmtUsd(x.amount)}</strong>
             · ${esc(x.funder || '')}
             ${x.program ? ` · <em>${esc(x.program)}</em>` : ''}
             ${x.fy ? ` <span class="brw-fy">FY${esc(x.fy)}</span>` : ''}
           </li>`).join('')}
         </ul>
       </div>`
    : '';

  // Links
  const links = [];
  if (f.url) links.push(`<a href="${esc(f.url)}" target="_blank" rel="noopener">site</a>`);
  if (f.data_portal_url) links.push(`<a href="${esc(f.data_portal_url)}" target="_blank" rel="noopener">data portal</a>`);
  if (f.lat && f.lng) links.push(`<a href="#/?lat=${esc(f.lat)}&lng=${esc(f.lng)}&zoom=10">show on map</a>`);
  const linksHtml = links.length
    ? `<div class="brw-links">${links.join(' · ')}</div>` : '';

  return `
    <article class="brw-card" data-id="${esc(f.id)}" data-type="${esc(f.type || '')}"
             style="--brw-type-color: ${typeColor}">
      <header class="brw-card-head">
        <h3>${esc(f.name)}</h3>
        ${acronymBadge}
        <span class="brw-spheres">${sphereChips}${recordBadge}</span>
      </header>
      <div class="brw-meta">
        ${f.parent_org ? `<small><strong>Parent:</strong> ${esc(f.parent_org)}</small>` : ''}
        ${f.region ? `<small> · ${esc(f.region)}</small>` : ''}
        ${f.country ? `<small> · ${esc(f.country)}</small>` : ''}
        ${f.type ? `<small class="brw-type" style="color:${typeColor}"> · ${esc(f.type)}</small>` : ''}
      </div>
      ${metricsRow}
      ${networksHtml}
      ${archivesHtml}
      ${personnelHtml}
      ${fundingHtml}
      ${linksHtml}
    </article>`;
}

function header(visible, total, hidden) {
  const sortOpts = SORT_OPTIONS.map(
    (o) => `<option value="${o.key}"${o.key === _sortKey ? ' selected' : ''}>${esc(o.label)}</option>`,
  ).join('');
  const hiddenNote = hidden > 0
    ? `<span class="brw-hidden">${hidden.toLocaleString()} hidden by search</span>`
    : '';
  return `
    <div class="brw-toolbar">
      <span class="brw-count">
        Showing <strong>${visible.toLocaleString()}</strong> of <strong>${total.toLocaleString()}</strong> facilities
      </span>
      ${hiddenNote}
      <input type="search" id="brw-search" placeholder="Search by name, acronym, network, person…"
             value="${esc(_searchTerm)}" />
      <label class="brw-sort">
        Sort by:
        <select id="brw-sort">${sortOpts}</select>
      </label>
    </div>`;
}

function renderInternal(rows) {
  if (!_container) return;
  const filtered = applySearch(rows, _searchTerm);
  const sorted = sortFacilities(filtered, _sortKey);
  const visible = sorted.slice(0, _renderLimit);
  const hidden = rows.length - filtered.length;

  const cardsHtml = visible.map(cardHtml).join('');
  const moreHtml = sorted.length > _renderLimit
    ? `<div class="brw-more-row"><button id="brw-more">Show ${Math.min(PAGE_SIZE, sorted.length - _renderLimit)} more</button></div>`
    : '';
  const emptyHtml = !visible.length
    ? `<div class="brw-empty">No facilities match. Try clearing filters or the search box.</div>`
    : '';

  _container.innerHTML = `
    ${header(filtered.length, rows.length, hidden)}
    <div class="brw-grid">${cardsHtml}${emptyHtml}</div>
    ${moreHtml}
  `;

  const search = _container.querySelector('#brw-search');
  if (search) {
    search.addEventListener('input', (e) => {
      _searchTerm = e.target.value;
      _renderLimit = PAGE_SIZE;
      renderInternal(rows);
      // Re-focus + restore caret position
      const s = _container.querySelector('#brw-search');
      if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); }
    });
  }
  const sortSel = _container.querySelector('#brw-sort');
  if (sortSel) {
    sortSel.addEventListener('change', (e) => {
      _sortKey = e.target.value;
      _renderLimit = PAGE_SIZE;
      renderInternal(rows);
    });
  }
  const moreBtn = _container.querySelector('#brw-more');
  if (moreBtn) {
    moreBtn.addEventListener('click', () => {
      _renderLimit += PAGE_SIZE;
      renderInternal(rows);
    });
  }
}

let _enriched = [];
let _enrichInflight = null;

export function renderList(features) {
  if (!_container) return;
  _features = features;

  const ids = featureIds(features);
  if (!ids.length) {
    _container.innerHTML = `
      ${header(0, 0, 0)}
      <div class="brw-empty">No facilities to show. Adjust filters in the sidebar.</div>`;
    return;
  }

  // Avoid running the enrichment query for every keystroke / filter change
  // when the visible-set hasn't actually changed. Cache by sorted-id key.
  const cacheKey = ids.slice().sort().join('|');
  if (_enriched.length && _enriched._cacheKey === cacheKey) {
    renderInternal(_enriched);
    return;
  }

  _container.innerHTML = `
    ${header(ids.length, ids.length, 0)}
    <div class="brw-loading">Loading rich facility data…</div>`;

  if (_enrichInflight) _enrichInflight = null; // discard prior promise's resolution
  const promise = fetchEnrichedFacilities(ids).then((rows) => {
    if (_enrichInflight !== promise) return; // a newer call started; bail
    rows._cacheKey = cacheKey;
    _enriched = rows;
    renderInternal(rows);
  }).catch((err) => {
    console.error('[browse] enrichment failed:', err);
    _container.innerHTML = `
      ${header(ids.length, ids.length, 0)}
      <div class="brw-empty">Failed to load: ${esc(err.message || String(err))}</div>`;
  });
  _enrichInflight = promise;
}

export function initListView(container) {
  _container = container;
  _container.innerHTML = '<div class="brw-loading">Initialising…</div>';
}
