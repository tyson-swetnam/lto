// list.js — Browse view: sortable/filterable table of facilities

let sortCol = 'name';
let sortDir = 1; // 1 = asc, -1 = desc
let _container = null;

const COLS = [
  { key: 'name',       label: 'Name' },
  { key: 'acronym',    label: 'Acronym' },
  { key: 'type',       label: 'Type' },
  { key: 'country',    label: 'Country' },
  { key: 'parent_org', label: 'Parent Org' },
  { key: 'url',        label: 'URL' },
];

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function normalizeFeature(f) {
  // GeoJSON features wrap props; DuckDB rows are flat
  return f.properties ?? f;
}

function sortFeatures(features) {
  return [...features].sort((a, b) => {
    const pa = normalizeFeature(a);
    const pb = normalizeFeature(b);
    const va = String(pa[sortCol] ?? '').toLowerCase();
    const vb = String(pb[sortCol] ?? '').toLowerCase();
    if (va < vb) return -sortDir;
    if (va > vb) return sortDir;
    return 0;
  });
}

function buildTable(features) {
  const sorted = sortFeatures(features);
  const thead = COLS.map((c) => {
    const arrow = c.key === sortCol ? (sortDir === 1 ? ' ▲' : ' ▼') : '';
    return `<th data-col="${esc(c.key)}" class="${c.key === sortCol ? 'sort-active' : ''}">${esc(c.label)}${arrow}</th>`;
  }).join('');

  const tbody = sorted.map((f) => {
    const p = normalizeFeature(f);
    const url = p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url.replace(/^https?:\/\//, '').replace(/\/$/, ''))}</a>` : '';
    return `<tr data-url="${esc(p.url || '')}">
      <td class="col-name">${esc(p.name ?? p.canonical_name ?? '')}</td>
      <td class="col-acronym"><code>${esc(p.acronym ?? '')}</code></td>
      <td class="col-type">${esc(p.type ?? p.facility_type ?? '')}</td>
      <td class="col-country">${esc(p.country ?? '')}</td>
      <td class="col-parent">${esc(p.parent_org ?? '')}</td>
      <td class="col-url">${url}</td>
    </tr>`;
  }).join('');

  return `<div class="table-scroll"><table class="browse-table">
    <thead><tr>${thead}</tr></thead>
    <tbody>${tbody}</tbody>
  </table></div>`;
}

export function renderList(features) {
  if (!_container) return;
  const count = features.length;
  _container.innerHTML = `<div class="browse-header">
    <span class="browse-count">${count.toLocaleString()} facilit${count === 1 ? 'y' : 'ies'}</span>
    <span class="browse-hint">Click a column header to sort · Click a row to open URL</span>
  </div>
  <div class="browse-scroll">${buildTable(features)}</div>`;

  // Attach sort handlers
  _container.querySelectorAll('th[data-col]').forEach((th) => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (col === sortCol) {
        sortDir = -sortDir;
      } else {
        sortCol = col;
        sortDir = 1;
      }
      renderList(features);
    });
  });

  // Row click -> open URL
  _container.querySelectorAll('tr[data-url]').forEach((tr) => {
    const url = tr.dataset.url;
    if (url) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', (e) => {
        if (e.target.tagName === 'A') return; // let link handle itself
        window.open(url, '_blank', 'noopener');
      });
    }
  });
}

export function initListView(container) {
  _container = container;
  _container.innerHTML = '<p style="padding:16px;color:var(--c-muted)">Loading…</p>';
}
