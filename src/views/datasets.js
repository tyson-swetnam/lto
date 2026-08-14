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
//   #/data               → filterable catalogue grouped by archive type
//   #/data/<archive_id>  → that archive's card scrolled into view
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
        <a class="ds-ep-link" href="${esc(row.api_url)}" target="_blank" rel="noopener"
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
        <a class="ds-ep-link" href="${esc(ep.url)}" target="_blank" rel="noopener"
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
    parts.push(`
      <span class="ds-ep ds-ep-machine" style="--ep:${color}">
        ${href
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
  return `<p class="ds-vars">${bits.join(' · ')}${top}</p>`;
}

function cardHtml(row) {
  const footer = [];
  if (row.base_url) {
    footer.push(`<a href="${esc(row.base_url)}" target="_blank" rel="noopener">Archive home</a>`);
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

export function initDatasetsView(container) {
  _container = container;
  _container.innerHTML = `
    <div class="ds-page">
      <p class="ds-status" style="padding:24px;color:#64748b">
        Archive catalogue loading…
      </p>
    </div>`;
}

export function renderDatasetsView(targetId) {
  if (!_container) return;
  renderArchives(targetId).catch((e) => {
    console.error('[datasets] render failed', e);
    const s = _container.querySelector('.ds-status');
    if (s) s.textContent = `Render failed: ${e.message}`;
  });
}
