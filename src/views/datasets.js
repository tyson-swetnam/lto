// datasets.js — LTO data-archive catalogue (#/data).
//
// Where the long-term records actually live: every archive a catalogued
// facility deposits into, with its machine access points — REST roots,
// ERDDAP/THREDDS bases, DataONE members, CKAN portals, cloud buckets —
// plus the facility↔archive edges and the per-archive data products.
// The access URL is the point of the tab, so every one is both a link
// and copy-able.
//
// Routes:
//   #/data                        → filterable catalogue grouped by archive type
//   #/data/<archive_id>           → that archive's card scrolled into view
//   #/data/<archive_id>/products  → sortable per-archive product table (D2)
//
// Data source (Wave J): data_archives + facility_archives (which
// facilities deposit where, with a primary/secondary role) +
// api_endpoints (documented machine calls) + cloud_buckets +
// data_products (addressable datasets, with citation counts where
// OpenAlex tracks the DOI).
//
// Adapted from cod-kmap's dataset catalogue view; the schema here is
// archive-centric (one card per archive, facilities as edges) where
// upstream's was dataset-centric (one card per dataset, stewards as
// edges), so the SQL is written fresh against the Wave-J tables rather
// than force-fit.

import { getConn, whenReady, unwrapRow } from '../db.js';

let _container = null;
let _cached = null;
let _type = 'all';
let _api = 'all';
let _license = 'all';
let _qFilter = '';

// archive_types vocab labels (schema/vocab/archive_types.csv). Fallback
// to the raw slug for anything the vocab gains later.
const TYPE_LABELS = {
  'repository'          : 'Data repositories',
  'data-portal'         : 'Data portals',
  'erddap'              : 'ERDDAP servers',
  'erddap-server'       : 'ERDDAP servers',
  'thredds-server'      : 'THREDDS servers',
  'observatory-network' : 'Observatory networks',
  'lab-archive'         : 'Institutional lab archives',
  'product-suite'       : 'Product suites',
  'federation'          : 'Repository federations',
  'network'             : 'Networks',
  'stac-catalog'        : 'STAC catalogs',
  'aggregator'          : 'Cross-archive aggregators',
  'knowledge-network'   : 'Knowledge networks',
  'program'             : 'Agency programs',
  'service'             : 'Web services',
};

// Machine-readable APIs get a saturated badge; the human landing page is
// deliberately muted so the API endpoints read first. Keys are
// data_archives.api_type values actually present in the catalogue.
const API_COLORS = {
  rest            : '#16a34a',
  erddap          : '#0d9488',
  thredds         : '#0369a1',
  dataone         : '#1d4ed8',
  ckan            : '#7c3aed',
  wms             : '#9333ea',
  'oai-pmh'       : '#a21caf',
  soap            : '#b45309',
  graphql         : '#c026d3',
  ftp             : '#78716c',
  github          : '#334155',
  'http-files'    : '#94a3b8',
  'https-listing' : '#94a3b8',
  'file-download' : '#94a3b8',
};

// An api_type a pipeline can query programmatically. Plain file listings
// and GitHub releases are downloadable but not queryable; NULL api_type
// means the archive documents no API at all — the distinction the
// summary line counts on.
const MACHINE_APIS = new Set([
  'rest', 'erddap', 'thredds', 'dataone', 'ckan', 'wms', 'oai-pmh',
  'soap', 'graphql', 'ftp',
]);

// cloud_buckets.provider → badge color (S3 amber like upstream's s3).
const BUCKET_COLORS = {
  s3: '#b45309', gcs: '#1d4ed8', azure: '#0369a1', https: '#94a3b8',
};

// cloud_buckets.access_mode values that need credentials or payment —
// these get the lock glyph.
const RESTRICTED_MODES = new Set(['registered-users', 'requester-pays']);

// facility_archives.role — how a facility uses the archive.
const ROLE_LABELS = {
  primary     : 'Primary',
  secondary   : 'Secondary',
  tertiary    : 'Tertiary',
  host        : 'Host',
  contributor : 'Contributor',
};
const ROLE_ORDER = { primary: 0, host: 1, secondary: 2, contributor: 3, tertiary: 4 };

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// The views re-render by replacing container.innerHTML, which throws away the
// focused element. Put focus and the caret back on the replacement so typing
// in a search box is not interrupted after every keystroke.
function restoreFocus(selector, caret) {
  const el = _container && _container.querySelector(selector);
  if (!el) return;
  el.focus();
  if (caret != null && el.setSelectionRange) {
    try { el.setSelectionRange(caret, caret); } catch { /* non-text input */ }
  }
}

function fmtInt(n) {
  if (n == null) return '—';
  return Math.round(n).toLocaleString();
}

// ── Endpoint health dots ─────────────────────────────────────────────
//
// url_health.parquet is the weekly HEAD sweep (scripts/check_url_health.py):
// one row per distinct URL with a coarse status verdict. Fetched whole and
// joined client-side — the table stays well under 500 rows, and a separate
// try/catch query means an absent or zero-row parquet costs the dots, never
// the catalogue (a SQL-level JOIN would fail the whole fetch if the
// url_health view didn't register).
//
// Dot colours: ok/redirect green; client-error amber, not red — many hosts
// 403/405 a scripted HEAD yet serve browsers fine; server-error/timeout red.
// Unchecked and template-skipped URLs get no dot at all.
let _health = null;   // Map url → {status, http_code, checked_at}; null until loaded

const HEALTH_DOT = {
  'ok'           : 'ok',
  'redirect'     : 'ok',
  'client-error' : 'warn',
  'server-error' : 'err',
  'timeout'      : 'err',
};

async function fetchHealth(conn) {
  const map = new Map();
  try {
    // checked_at is VARCHAR today; the CAST guards against a future export
    // typing it DATE (Arrow hands DATE to JS as epoch millis).
    const res = await conn.query(`
      SELECT url, status, http_code, CAST(checked_at AS VARCHAR) AS checked_at
      FROM url_health`);
    for (const row of res.toArray()) {
      const r = unwrapRow(row.toJSON());
      if (r.url) map.set(r.url, r);
    }
  } catch (e) {
    // View missing (parquet 404'd at init) — degrade to no dots.
    console.warn('[datasets] url_health unavailable, skipping health dots:', e.message);
  }
  return map;
}

function healthDot(url) {
  const h = (_health && url) ? _health.get(url) : null;
  const cls = h && HEALTH_DOT[h.status];
  if (!cls) return '';
  const bits = [
    h.http_code != null ? `HTTP ${h.http_code}` : h.status,
    h.checked_at ? `checked ${h.checked_at}` : null,
  ];
  if (h.status === 'client-error') {
    bits.push('may be HEAD-hostile — some servers block automated checks but serve browsers fine');
  }
  return `<span class="ds-health ds-health-${cls}"
    title="${esc(bits.filter(Boolean).join(' · '))}"></span>`;
}

async function fetchArchives() {
  await whenReady();
  const conn = getConn();
  if (!conn) throw new Error('DuckDB connection not ready');
  // Facilities, endpoints, buckets and product stats all rolled up into
  // LIST<STRUCT> / scalars so the whole catalogue is one round trip.
  // unwrapRow turns the Arrow vectors into plain arrays/objects.
  //
  // Casts: SUM(INTEGER) is HUGEINT in DuckDB, which duckdb-wasm hands to
  // JS as a BigInt — scripts/qa.py check_view_sql_types gates on it.
  const res = await conn.query(`
    WITH fac AS (
      SELECT fa.archive_id,
             list(struct_pack(
               facility_id := fa.facility_id,
               name        := f.canonical_name,
               acronym     := f.acronym,
               ftype       := f.facility_type,
               role        := fa.role,
               scope_url   := fa.scope_url
             ) ORDER BY fa.role, f.canonical_name) AS facilities
      FROM facility_archives fa
      JOIN facilities f ON f.facility_id = fa.facility_id
      GROUP BY fa.archive_id
    ),
    eps AS (
      SELECT archive_id,
             list(struct_pack(
               url     := path_or_url,
               method  := method,
               purpose := purpose,
               fmt     := response_format,
               docs    := schema_url,
               example := example_call
             ) ORDER BY purpose) AS endpoints
      FROM api_endpoints
      GROUP BY archive_id
    ),
    cbs AS (
      SELECT archive_id,
             list(struct_pack(
               provider := provider,
               name     := bucket_name,
               region   := region,
               mode     := access_mode,
               docs     := documentation_url,
               prefix   := sample_prefix
             ) ORDER BY provider, bucket_name) AS buckets
      FROM cloud_buckets
      GROUP BY archive_id
    ),
    prods AS (
      SELECT archive_id,
             CAST(COUNT(*) AS DOUBLE)                          AS n_products,
             CAST(COALESCE(SUM(cited_by_count), 0) AS DOUBLE)  AS total_cites,
             arg_max(title, COALESCE(cited_by_count, -1))      AS top_title,
             arg_max(COALESCE(doi, url), COALESCE(cited_by_count, -1)) AS top_link
      FROM data_products
      WHERE archive_id IS NOT NULL
      GROUP BY archive_id
    )
    SELECT a.*,
           fac.facilities   AS facilities,
           eps.endpoints    AS endpoints,
           cbs.buckets      AS buckets,
           COALESCE(prods.n_products, 0)  AS n_products,
           COALESCE(prods.total_cites, 0) AS total_cites,
           prods.top_title,
           prods.top_link
    FROM data_archives a
    LEFT JOIN fac   ON fac.archive_id   = a.archive_id
    LEFT JOIN eps   ON eps.archive_id   = a.archive_id
    LEFT JOIN cbs   ON cbs.archive_id   = a.archive_id
    LEFT JOIN prods ON prods.archive_id = a.archive_id
    ORDER BY a.name`);
  _health = await fetchHealth(conn);
  return res.toArray().map((row) => {
    const r = unwrapRow(row.toJSON());
    r.facilities = Array.isArray(r.facilities) ? r.facilities : [];
    r.endpoints = Array.isArray(r.endpoints) ? r.endpoints : [];
    r.buckets = Array.isArray(r.buckets) ? r.buckets : [];
    r.n_facilities = r.facilities.length;
    r.n_endpoints = r.endpoints.length;
    r.n_buckets = r.buckets.length;
    r.machine = MACHINE_APIS.has(r.api_type);
    return r;
  });
}

// Access badges: the archive-level API root first (colored by api_type),
// then each documented endpoint call, then cloud buckets. Every badge is
// a link plus a ⧉ copy button — the copy is the point.
function accessBadges(row) {
  const parts = [];

  if (row.api_url) {
    const kind = row.api_type || 'api';
    const color = API_COLORS[kind] || '#64748b';
    const title = [
      `${kind.toUpperCase()} root`,
      row.api_doc_url ? `docs: ${row.api_doc_url}` : null,
      row.api_url,
    ].filter(Boolean).join(' — ');
    parts.push(`
      <span class="ds-ep${row.machine ? ' ds-ep-machine' : ''}" style="--ep:${color}">
        ${healthDot(row.api_url)}<a class="ds-ep-link" href="${esc(row.api_url)}" target="_blank" rel="noopener"
           title="${esc(title)}">${esc(kind)}</a>
        <button class="ds-ep-copy" data-url="${esc(row.api_url)}"
                title="Copy ${esc(row.api_url)}" aria-label="Copy API root URL">⧉</button>
      </span>`);
  }

  for (const ep of row.endpoints) {
    // Badge text is the short response format ('json', 'csv', 'netcdf');
    // the purpose and example call live in the tooltip, which is where a
    // reader decides whether this endpoint is the one they need.
    const fmt = String(ep.fmt || '')
      .replace(/^application\/(x-)?/, '').replace(/^text\//, '')
      .replace('tab-separated-values', 'tsv')
      .replace('octet-stream', 'binary') || 'call';
    const color = API_COLORS[row.api_type] || '#64748b';
    const title = [
      ep.purpose,
      `${ep.method || 'GET'} — ${ep.fmt || 'format unrecorded'}`,
      ep.example ? `example: ${ep.example}` : null,
      ep.url,
    ].filter(Boolean).join(' — ');
    parts.push(`
      <span class="ds-ep ds-ep-machine" style="--ep:${color}">
        ${healthDot(ep.url)}<a class="ds-ep-link" href="${esc(ep.url)}" target="_blank" rel="noopener"
           title="${esc(title)}">${esc(fmt)}</a>
        <button class="ds-ep-copy" data-url="${esc(ep.url)}"
                title="Copy ${esc(ep.url)}" aria-label="Copy endpoint URL">⧉</button>
      </span>`);
  }

  for (const b of row.buckets) {
    const color = BUCKET_COLORS[b.provider] || '#78716c';
    const locked = RESTRICTED_MODES.has(b.mode);
    const href = b.docs || (b.provider === 's3' ? `https://${b.name}.s3.amazonaws.com` : null);
    const title = [
      `${b.provider} bucket ${b.name}`,
      b.region ? `region ${b.region}` : null,
      `access: ${b.mode || 'unrecorded'}`,
      b.prefix ? `sample prefix: ${b.prefix}` : null,
    ].filter(Boolean).join(' — ');
    const label = `${esc(b.provider)}:${esc(b.name)}${locked ? ' 🔒' : ''}`;
    // Health is keyed on documentation_url — the field the sweep checks;
    // a constructed s3 landing URL never appears in url_health.
    parts.push(`
      <span class="ds-ep ds-ep-machine" style="--ep:${color}">
        ${healthDot(b.docs)}${href
    ? `<a class="ds-ep-link" href="${esc(href)}" target="_blank" rel="noopener" title="${esc(title)}">${label}</a>`
    : `<span class="ds-ep-link" title="${esc(title)}">${label}</span>`}
        <button class="ds-ep-copy" data-url="${esc(b.prefix || b.name)}"
                title="Copy bucket ${b.prefix ? 'prefix' : 'name'}" aria-label="Copy bucket">⧉</button>
      </span>`);
  }

  if (!parts.length) {
    return `<p class="ds-empty">No machine access recorded — landing page only.</p>`;
  }

  const bits = [];
  if (row.api_url) bits.push(row.machine ? 'queryable API' : 'file access');
  if (row.n_endpoints) {
    bits.push(`${row.n_endpoints} documented call${row.n_endpoints === 1 ? '' : 's'}`);
  }
  if (row.n_buckets) {
    const open = row.buckets.filter((b) => !RESTRICTED_MODES.has(b.mode)).length;
    bits.push(`${row.n_buckets} cloud bucket${row.n_buckets === 1 ? '' : 's'}${
      open < row.n_buckets ? ` (${row.n_buckets - open} restricted)` : ''}`);
  }
  return `
    <div class="ds-eps">${parts.join('')}</div>
    <p class="ds-ep-note">${esc(bits.join(' · '))}</p>`;
}

// Facility edges. Cap the chips at six — NWIS has 60+ depositor
// facilities and a card-long chip wall buries every other archive; the
// hidden remainder is countable and listed in the title attribute.
const FACILITY_CHIP_CAP = 6;

function facilityBlock(row) {
  const facs = row.facilities || [];
  if (!facs.length) {
    return `
      <p class="ds-producers ds-producers-none"
         title="facility_archives has no row for this archive">
        <span class="ds-label">Used by</span>
        <span class="ds-unresolved">no catalogued facility linked yet</span>
      </p>`;
  }
  const sorted = [...facs].sort((a, b) =>
    (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9)
    || String(a.name).localeCompare(String(b.name)));
  const shown = sorted.slice(0, FACILITY_CHIP_CAP);
  const rest = sorted.slice(FACILITY_CHIP_CAP);
  const chips = shown.map((p) => {
    const label = p.acronym && p.acronym !== p.name ? p.acronym : p.name;
    const role = ROLE_LABELS[p.role] || p.role || 'Depositor';
    const title = [
      p.name,
      `${role.toLowerCase()} archive for this facility`,
      p.scope_url ? `scope: ${p.scope_url}` : null,
    ].filter(Boolean).join('\n');
    return `
      <span class="ds-prod ds-prod-${p.role === 'primary' ? 'high' : 'medium'}"
            title="${esc(title)}">
        <span class="ds-prod-role">${esc(role)}</span>
        <span class="ds-prod-name">${esc(label)}</span>
      </span>`;
  }).join('');
  const more = rest.length
    ? `<span class="ds-prod ds-prod-more" title="${esc(rest.map((p) => p.name).join('\n'))}">+${rest.length} more</span>`
    : '';
  return `
    <p class="ds-producers">
      <span class="ds-label">Used by</span>${chips}${more}
    </p>`;
}

function productLine(row) {
  if (!row.n_products) return '';
  const bits = [`<strong>${fmtInt(row.n_products)}</strong> catalogued data product${row.n_products === 1 ? '' : 's'}`];
  if (row.total_cites > 0) bits.push(`${fmtInt(row.total_cites)} tracked citations`);
  let top = '';
  if (row.top_title) {
    const href = row.top_link
      ? (String(row.top_link).startsWith('http') ? row.top_link : `https://doi.org/${row.top_link}`)
      : null;
    top = href
      ? ` · most cited: <a href="${esc(href)}" target="_blank" rel="noopener">${esc(row.top_title)}</a>`
      : ` · e.g. ${esc(row.top_title)}`;
  }
  // The count is a door, not a dead end — the products sub-route
  // (renderProducts below) shows the full sortable table. Guarded by the
  // n_products early-return above, so a zero-product archive gets no link.
  const all = ` · <a class="ds-products-link"
    href="#/data/${encodeURIComponent(row.archive_id)}/products">view all ${
  fmtInt(row.n_products)} product${row.n_products === 1 ? '' : 's'}</a>`;
  return `<p class="ds-vars">${bits.join(' · ')}${top}${all}</p>`;
}

function cardHtml(row) {
  const footer = [];
  if (row.base_url) {
    footer.push(`<a href="${esc(row.base_url)}" target="_blank" rel="noopener">Archive home</a>${healthDot(row.base_url)}`);
  }
  if (row.api_doc_url) {
    footer.push(`<a href="${esc(row.api_doc_url)}" target="_blank" rel="noopener">API docs</a>`);
  }
  if (row.doi_prefix) {
    footer.push(`<span title="DOIs minted by this archive start with this prefix">DOI prefix ${esc(row.doi_prefix)}</span>`);
  }
  return `
    <article class="ds-card" id="ds-${esc(row.archive_id)}" data-id="${esc(row.archive_id)}">
      <header class="ds-card-head">
        <h3>${esc(row.name)}</h3>
        <span class="ds-cat">${esc(TYPE_LABELS[row.archive_type] || row.archive_type)}</span>
      </header>
      ${row.organization ? `<p class="ds-provider">${esc(row.organization)}</p>` : ''}
      ${facilityBlock(row)}
      ${accessBadges(row)}
      ${productLine(row)}
      ${row.license_slug ? `<p class="ds-license" title="License vocabulary slug — see schema/vocab/data_licenses.csv">${esc(row.license_slug)}</p>` : ''}
      ${row.notes ? `<p class="ds-note">${esc(row.notes)}</p>` : ''}
      ${footer.length ? `<footer class="ds-links">${footer.join(' · ')}</footer>` : ''}
    </article>`;
}

function applyFilter(rows) {
  let out = rows;
  if (_type !== 'all') out = out.filter((r) => r.archive_type === _type);
  if (_api !== 'all') {
    if (_api === 'machine') out = out.filter((r) => r.machine || r.n_endpoints > 0 || r.n_buckets > 0);
    else if (_api === 'none') out = out.filter((r) => !r.api_type && !r.n_endpoints && !r.n_buckets);
    else out = out.filter((r) => r.api_type === _api);
  }
  if (_license !== 'all') out = out.filter((r) => (r.license_slug || '—') === _license);
  const q = _qFilter.trim().toLowerCase();
  if (q) {
    out = out.filter((r) => [
      r.name, r.organization, r.archive_type, r.api_type, r.license_slug,
      r.notes, r.top_title,
      ...(r.facilities || []).map((p) => `${p.name} ${p.acronym || ''}`),
      ...(r.endpoints || []).map((e) => `${e.purpose || ''} ${e.url}`),
      ...(r.buckets || []).map((b) => `${b.provider} ${b.name}`),
    ].join(' ').toLowerCase().includes(q));
  }
  return out;
}

const OTHER_GROUP = 'Other archive types';

function groupedHtml(rows) {
  // Group by archive type so the 29 repositories read as one family; a
  // type with a single archive doesn't earn a heading of its own — those
  // pool at the end.
  const counts = new Map();
  for (const r of rows) {
    counts.set(r.archive_type, (counts.get(r.archive_type) || 0) + 1);
  }
  const groups = new Map();
  for (const r of rows) {
    const label = TYPE_LABELS[r.archive_type] || r.archive_type;
    const key = counts.get(r.archive_type) > 1 ? label : OTHER_GROUP;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  return [...groups.entries()]
    .sort((a, b) => {
      if (a[0] === OTHER_GROUP) return 1;
      if (b[0] === OTHER_GROUP) return -1;
      return b[1].length - a[1].length || a[0].localeCompare(b[0]);
    })
    .map(([label, items]) => {
      const nFac = new Set(items.flatMap((r) => (r.facilities || []).map((p) => p.facility_id))).size;
      const nProd = items.reduce((n, r) => n + r.n_products, 0);
      return `
      <section class="ds-group">
        <h2>${esc(label)}
          <span class="ds-count">${items.length} archive${items.length === 1 ? '' : 's'}</span>
          <span class="ds-count">${fmtInt(nFac)} facilit${nFac === 1 ? 'y' : 'ies'}</span>
          ${nProd ? `<span class="ds-count">${fmtInt(nProd)} products</span>` : ''}
        </h2>
        <div class="ds-grid">${items
    .sort((a, b) => String(a.name).localeCompare(String(b.name)))
    .map(cardHtml).join('')}</div>
      </section>`;
    }).join('');
}

async function renderArchives(targetId) {
  if (!_container) return;
  const status = _container.querySelector('.ds-status');
  if (status) status.textContent = 'Loading…';

  if (!_cached) {
    try {
      _cached = await fetchArchives();
    } catch (e) {
      if (status) status.textContent = `Failed to load: ${e.message}`;
      console.error(e);
      return;
    }
  }

  if (!_cached.length) {
    _container.innerHTML = `
      <div class="ds-page">
        <header class="ds-header"><h1>Data archives</h1></header>
        <p class="no-data">
          Archive catalogue not loaded yet. Run
          <code>python scripts/load_lto_archives.py</code>, then
          <code>python scripts/export_parquet.py</code>.
        </p>
      </div>`;
    return;
  }

  const rows = applyFilter(_cached);
  const nFac = new Set(_cached.flatMap((r) => (r.facilities || []).map((p) => p.facility_id))).size;
  const nProds = _cached.reduce((n, r) => n + r.n_products, 0);
  const nEps = _cached.reduce((n, r) => n + r.n_endpoints, 0);
  const nBuckets = _cached.reduce((n, r) => n + r.n_buckets, 0);
  const nMachine = _cached.filter((r) => r.machine || r.n_endpoints > 0).length;
  const nNoApi = _cached.filter((r) => !r.api_type && !r.n_endpoints && !r.n_buckets).length;
  const openBuckets = _cached.flatMap((r) => r.buckets || [])
    .filter((b) => !RESTRICTED_MODES.has(b.mode)).length;

  const types = [...new Set(_cached.map((r) => r.archive_type))].sort();
  const apis = [...new Set(_cached.map((r) => r.api_type).filter(Boolean))].sort();
  const licenses = [...new Set(_cached.map((r) => r.license_slug || '—'))].sort();

  _container.innerHTML = `
    <div class="ds-page">
      <header class="ds-header">
        <h1>Data archives</h1>
        <ul class="ds-facts">
          <li><strong>${fmtInt(_cached.length)}</strong> archives hold the
            long-term records of <strong>${fmtInt(nFac)}</strong> catalogued
            facilities (<strong>${fmtInt(nProds)}</strong> addressable data
            products)</li>
          <li><strong>${fmtInt(nMachine)}</strong> expose a queryable API —
            REST, ERDDAP, THREDDS, DataONE, CKAN, OAI-PMH —
            with <strong>${fmtInt(nEps)}</strong> documented calls;
            <strong>${fmtInt(nNoApi)}</strong> offer only a landing page</li>
          <li><strong>${fmtInt(nBuckets)}</strong> public-cloud buckets
            (<strong>${fmtInt(openBuckets)}</strong> anonymously readable —
            the rest need registration or requester-pays 🔒)</li>
        </ul>
        <p class="ds-summary">
          Click a badge to open the endpoint, or ⧉ to copy its URL. Hover a
          facility chip for its role; hover a call badge for the request
          and an example.
        </p>
        <div class="ds-controls">
          <label>Type:
            <select id="ds-type">
              <option value="all">All (${_cached.length})</option>
              ${types.map((t) => `<option value="${esc(t)}"${_type === t ? ' selected' : ''}>${
    esc(TYPE_LABELS[t] || t)} (${_cached.filter((r) => r.archive_type === t).length})</option>`).join('')}
            </select>
          </label>
          <label>API:
            <select id="ds-api">
              <option value="all">Any access</option>
              <option value="machine"${_api === 'machine' ? ' selected' : ''}>Machine access (${nMachine})</option>
              <option value="none"${_api === 'none' ? ' selected' : ''}>Landing page only (${nNoApi})</option>
              ${apis.map((a) => `<option value="${esc(a)}"${_api === a ? ' selected' : ''}>${
    esc(a)} (${_cached.filter((r) => r.api_type === a).length})</option>`).join('')}
            </select>
          </label>
          <label>License:
            <select id="ds-license">
              <option value="all">All</option>
              ${licenses.map((l) => `<option value="${esc(l)}"${_license === l ? ' selected' : ''}>${
    esc(l)} (${_cached.filter((r) => (r.license_slug || '—') === l).length})</option>`).join('')}
            </select>
          </label>
          <input id="ds-q" type="search"
                 placeholder="Search archive, organization, facility, endpoint, bucket…"
                 value="${esc(_qFilter)}">
        </div>
        <p class="ds-count-line">Showing <strong>${fmtInt(rows.length)}</strong>
          of <strong>${fmtInt(_cached.length)}</strong> archives.</p>
      </header>
      ${rows.length ? groupedHtml(rows) : `
        <p class="no-data">No archive matches these filters.</p>`}
      <p class="ds-status">Done.</p>
    </div>`;

  _container.querySelector('#ds-type').addEventListener('change', (ev) => {
    _type = ev.target.value;
    renderArchives(null);
  });
  _container.querySelector('#ds-api').addEventListener('change', (ev) => {
    _api = ev.target.value;
    renderArchives(null);
  });
  _container.querySelector('#ds-license').addEventListener('change', (ev) => {
    _license = ev.target.value;
    renderArchives(null);
  });
  _container.querySelector('#ds-q').addEventListener('input', (ev) => {
    _qFilter = ev.target.value;
    const caret = ev.target.selectionStart;
    // The re-render destroys this input, so focus and caret must be
    // restored on its replacement (same fix as the People search box).
    renderArchives(null).then(() => restoreFocus('#ds-q', caret));
  });

  for (const btn of _container.querySelectorAll('.ds-ep-copy')) {
    btn.addEventListener('click', async (ev) => {
      ev.preventDefault();
      const url = btn.dataset.url;
      try {
        await navigator.clipboard.writeText(url);
      } catch {
        // clipboard API needs a secure context; file:// and plain http
        // on a LAN address don't get one, so fall back to a selection.
        const ta = document.createElement('textarea');
        ta.value = url;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch { /* nothing left to try */ }
        document.body.removeChild(ta);
      }
      const prev = btn.textContent;
      btn.textContent = '✓';
      setTimeout(() => { btn.textContent = prev; }, 1200);
    });
  }

  if (targetId) {
    const el = _container.querySelector(`#ds-${CSS.escape(targetId)}`);
    if (el) {
      el.classList.add('ds-card-active');
      requestAnimationFrame(() => el.scrollIntoView({
        behavior: 'smooth', block: 'start',
      }));
    }
  }
}

// ── Products sub-view (#/data/<archive_id>/products) ─────────────────
//
// One archive, every addressable dataset it holds, as a sortable /
// filterable table. Fetched on demand — the catalogue query above rolls
// products up to counts only, so the first visit to an archive costs one
// extra round trip; after that the rows are cached for the session.

const PROD_PAGE_SIZE = 200; // below this, no pager — the whole table renders

// Sort/filter state, module-level like the catalogue's, but scoped to
// one archive at a time: switching archives resets it (a format filter
// tuned for NEON is meaningless on the EDI table).
const _prodCache = new Map();   // archive_id → plain product rows
let _prodArchive = null;        // archive the state below belongs to
let _prodSortKey = 'cited_by_count';
let _prodSortDir = 'desc';
let _prodFormat = 'all';
let _prodLicense = 'all';
let _prodQ = '';
let _prodPage = 0;

const PROD_COLS = [
  { key: 'title',          label: 'Title' },
  { key: 'format_slug',    label: 'Format' },
  { key: 'license_slug',   label: 'License' },
  { key: 'temporal_start', label: 'Coverage' },
  { key: 'cited_by_count', label: 'Cited by', num: true },
  { key: 'source',         label: 'Source' },
  { key: 'confidence',     label: 'Confidence' },
];

// Confidence sorts by rank, not alphabetically — 'high' < 'low' <
// 'medium' as strings would put medium last.
const CONF_RANK = { high: 0, medium: 1, low: 2 };

async function fetchProducts(archiveId) {
  if (_prodCache.has(archiveId)) return _prodCache.get(archiveId);
  await whenReady();
  const conn = getConn();
  if (!conn) throw new Error('DuckDB connection not ready');
  // Prepared statement: archive_id comes off the URL hash, so it never
  // gets interpolated into the SQL text. DATE columns are cast to
  // VARCHAR at the SQL boundary — Arrow hands DATE to JS as epoch
  // millis and the table only wants the ISO day. cited_by_count is
  // INTEGER and never aggregated, so no HUGEINT reaches the browser.
  const prepared = await conn.prepare(`
    SELECT product_id, title, doi, url,
           format_slug, license_slug,
           CAST(temporal_start AS VARCHAR) AS temporal_start,
           CAST(temporal_end   AS VARCHAR) AS temporal_end,
           cited_by_count, source, confidence, variables_text
    FROM data_products
    WHERE archive_id = ?`);
  const res = await prepared.query(archiveId);
  const rows = res.toArray().map((row) => unwrapRow(row.toJSON()));
  _prodCache.set(archiveId, rows);
  return rows;
}

function applyProductFilter(rows) {
  let out = rows;
  if (_prodFormat !== 'all') out = out.filter((r) => (r.format_slug || '—') === _prodFormat);
  if (_prodLicense !== 'all') out = out.filter((r) => (r.license_slug || '—') === _prodLicense);
  const q = _prodQ.trim().toLowerCase();
  if (q) {
    // Variables are searchable on purpose: "which NEON products carry
    // NEE?" is the question this table exists to answer.
    out = out.filter((r) =>
      `${r.title || ''} ${r.variables_text || ''}`.toLowerCase().includes(q));
  }
  return out;
}

function sortProducts(rows) {
  const key = _prodSortKey;
  const dir = _prodSortDir === 'asc' ? 1 : -1;
  const val = (r) => (key === 'confidence' ? (CONF_RANK[r[key]] ?? null) : r[key]);
  return [...rows].sort((a, b) => {
    const av = val(a);
    const bv = val(b);
    // NULLs sort last in either direction — an untracked DOI must never
    // outrank a cited product just because the sort flipped.
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const c = (typeof av === 'number' && typeof bv === 'number')
      ? av - bv
      : String(av).localeCompare(String(bv));
    return c * dir || String(a.title).localeCompare(String(b.title));
  });
}

function productRowHtml(r) {
  // Title links the DOI when there is one (the citable, permanent
  // address), else the landing URL. The catalogue currently has no row
  // with neither, but a bare-text fallback keeps a future one visible.
  const href = r.doi ? `https://doi.org/${r.doi}` : (r.url || null);
  const title = href
    ? `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(r.title)}</a>`
    : esc(r.title);
  const span = (r.temporal_start || r.temporal_end)
    ? `${esc(r.temporal_start || '…')} – ${esc(r.temporal_end || 'present')}`
    : '—';
  // 'n/a', never 0: NULL means OpenAlex does not track the DOI (or there
  // is no DOI), which is unknown — a rendered 0 would read as "uncited".
  const cites = r.cited_by_count == null
    ? '<span class="ds-products-na" title="No citation count — DOI untracked by OpenAlex (unknown, not zero)">n/a</span>'
    : fmtInt(r.cited_by_count);
  const conf = r.confidence
    ? `<span class="ds-conf ds-conf-${esc(r.confidence)}">${esc(r.confidence)}</span>`
    : '—';
  return `<tr>
    <td class="ds-products-title"${r.variables_text ? ` title="${esc(r.variables_text)}"` : ''}>${title}</td>
    <td>${esc(r.format_slug || '—')}</td>
    <td>${esc(r.license_slug || '—')}</td>
    <td class="ds-products-span">${span}</td>
    <td class="num">${cites}</td>
    <td class="ds-products-src">${esc(r.source || '—')}</td>
    <td>${conf}</td>
  </tr>`;
}

function productPagerHtml(nRows) {
  // Below PROD_PAGE_SIZE the whole table renders and no pager appears;
  // only an archive that outgrows it (none yet — NEON tops out at 146)
  // gets the simple prev/next.
  if (nRows <= PROD_PAGE_SIZE) return '';
  const nPages = Math.ceil(nRows / PROD_PAGE_SIZE);
  return `<div class="ds-products-pager">
    <button data-page="${_prodPage - 1}"${_prodPage === 0 ? ' disabled' : ''}>‹ Prev</button>
    <span class="ds-products-pageno">page ${_prodPage + 1} of ${nPages}</span>
    <button data-page="${_prodPage + 1}"${_prodPage >= nPages - 1 ? ' disabled' : ''}>Next ›</button>
  </div>`;
}

async function renderProducts(archiveId) {
  if (!_container) return;
  const status = _container.querySelector('.ds-status');
  if (status) status.textContent = 'Loading…';

  // The header needs the archive's name/org (and a deep link must work
  // cold), so make sure the catalogue rows are in before looking it up.
  if (!_cached) {
    try {
      _cached = await fetchArchives();
    } catch (e) {
      if (status) status.textContent = `Failed to load: ${e.message}`;
      console.error(e);
      return;
    }
  }
  const arch = _cached.find((r) => r.archive_id === archiveId);
  if (!arch) {
    _container.innerHTML = `
      <div class="ds-page">
        <p class="ds-products-back"><a href="#/data">← All archives</a></p>
        <p class="no-data">No archive <code>${esc(archiveId)}</code> in the
          catalogue — the link may predate an archive_id rename.</p>
      </div>`;
    return;
  }

  if (_prodArchive !== archiveId) {
    _prodArchive = archiveId;
    _prodSortKey = 'cited_by_count';
    _prodSortDir = 'desc';
    _prodFormat = 'all';
    _prodLicense = 'all';
    _prodQ = '';
    _prodPage = 0;
  }

  let rows;
  try {
    rows = await fetchProducts(archiveId);
  } catch (e) {
    if (status) status.textContent = `Failed to load products: ${e.message}`;
    console.error(e);
    return;
  }

  const filtered = sortProducts(applyProductFilter(rows));
  // Clamp the page — a filter change can strand _prodPage past the end.
  const maxPage = Math.max(0, Math.ceil(filtered.length / PROD_PAGE_SIZE) - 1);
  if (_prodPage > maxPage) _prodPage = maxPage;
  const shown = filtered.length > PROD_PAGE_SIZE
    ? filtered.slice(_prodPage * PROD_PAGE_SIZE, (_prodPage + 1) * PROD_PAGE_SIZE)
    : filtered;

  const fmts = [...new Set(rows.map((r) => r.format_slug || '—'))].sort();
  const lics = [...new Set(rows.map((r) => r.license_slug || '—'))].sort();

  const ths = PROD_COLS.map((c) => {
    const arrow = _prodSortKey === c.key
      ? `<span class="ds-products-arrow">${_prodSortDir === 'asc' ? ' ▲' : ' ▼'}</span>`
      : '';
    return `<th data-key="${c.key}"${c.num ? ' class="num"' : ''}
      title="Sort by ${esc(c.label.toLowerCase())}">${c.label}${arrow}</th>`;
  }).join('');

  _container.innerHTML = `
    <div class="ds-page">
      <p class="ds-products-back">
        <a href="#/data/${encodeURIComponent(archiveId)}">← All archives</a>
      </p>
      <header class="ds-header">
        <h1>${esc(arch.name)} — data products</h1>
        ${arch.organization ? `<p class="ds-provider">${esc(arch.organization)}</p>` : ''}
        <p class="ds-summary">
          Every addressable dataset this archive holds for the catalogued
          facilities. Click a title to open its DOI or landing page; click
          a column header to sort; hover a title for its variables.
          Citation counts come from OpenAlex where the DOI is tracked —
          <em>n/a</em> means untracked, not uncited.
        </p>
        <div class="ds-controls">
          <label>Format:
            <select id="dsp-format">
              <option value="all">All (${rows.length})</option>
              ${fmts.map((f) => `<option value="${esc(f)}"${_prodFormat === f ? ' selected' : ''}>${
    esc(f)} (${rows.filter((r) => (r.format_slug || '—') === f).length})</option>`).join('')}
            </select>
          </label>
          <label>License:
            <select id="dsp-license">
              <option value="all">All</option>
              ${lics.map((l) => `<option value="${esc(l)}"${_prodLicense === l ? ' selected' : ''}>${
    esc(l)} (${rows.filter((r) => (r.license_slug || '—') === l).length})</option>`).join('')}
            </select>
          </label>
          <input id="dsp-q" type="search"
                 placeholder="Search title or variables…"
                 value="${esc(_prodQ)}">
        </div>
        <p class="ds-count-line">Showing <strong>${fmtInt(shown.length)}</strong>
          of <strong>${fmtInt(rows.length)}</strong> products.</p>
      </header>
      ${productPagerHtml(filtered.length)}
      <div class="ds-products-scroll">
        <table class="dash-table ds-products-table">
          <thead><tr>${ths}</tr></thead>
          <tbody>${shown.length
    ? shown.map(productRowHtml).join('')
    : `<tr><td colspan="${PROD_COLS.length}" class="no-data">No product matches these filters.</td></tr>`}</tbody>
        </table>
      </div>
      <p class="ds-status">Done.</p>
    </div>`;

  _container.querySelector('#dsp-format').addEventListener('change', (ev) => {
    _prodFormat = ev.target.value;
    _prodPage = 0;
    renderProducts(archiveId);
  });
  _container.querySelector('#dsp-license').addEventListener('change', (ev) => {
    _prodLicense = ev.target.value;
    _prodPage = 0;
    renderProducts(archiveId);
  });
  _container.querySelector('#dsp-q').addEventListener('input', (ev) => {
    _prodQ = ev.target.value;
    _prodPage = 0;
    const caret = ev.target.selectionStart;
    // Same focus-restore dance as the catalogue search box above.
    renderProducts(archiveId).then(() => restoreFocus('#dsp-q', caret));
  });
  for (const th of _container.querySelectorAll('.ds-products-table th[data-key]')) {
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      if (_prodSortKey === key) {
        _prodSortDir = _prodSortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _prodSortKey = key;
        // Numbers start high-to-low, text starts A-to-Z.
        _prodSortDir = key === 'cited_by_count' ? 'desc' : 'asc';
      }
      _prodPage = 0;
      renderProducts(archiveId);
    });
  }
  for (const btn of _container.querySelectorAll('.ds-products-pager button[data-page]')) {
    btn.addEventListener('click', () => {
      _prodPage = Number(btn.dataset.page);
      renderProducts(archiveId);
    });
  }
}

export function initDatasetsView(container) {
  _container = container;
  _container.innerHTML = `
    <div class="ds-page">
      <p class="ds-status" style="padding:24px;color:#64748b">
        Archive catalogue loading…
      </p>
    </div>`;
}

export function renderDatasetsView(target) {
  if (!_container) return;
  // `target` is the decoded tail of '#/data/...' (main.js passes it
  // whole): a bare archive_id focuses that card in the catalogue;
  // '<archive_id>/products' opens the per-archive product table instead.
  const m = target && target.match(/^(.+)\/products$/);
  (m ? renderProducts(m[1]) : renderArchives(target)).catch((e) => {
    console.error('[datasets] render failed', e);
    const s = _container.querySelector('.ds-status');
    if (s) s.textContent = `Render failed: ${e.message}`;
  });
}
