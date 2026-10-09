// projects.js — science groups, their sites and projects (#/projects).
//
// The page answers "who is working where": every network or program in
// the catalogue (NEON, LTER, LTAR, AmeriFlux, ARID …) is a group, and
// under it sit the member sites the current scope lens lets through,
// each with its named locations. ARID's group also carries its projects
// — bodies of work rather than places, most with no map point at all —
// with sub-projects nested under their parent.
//
// Routes:
//   #/projects              → every group with a site in scope
//   #/projects/<id>         → that project's card, or that network's
//                             group, scrolled into view
//
// Scope: the same four lenses as the map (SCOPES in src/filters.js),
// chosen on this page and remembered for it alone. Sites are tested
// with each lens's `test`, the definition the GeoJSON fallback uses.
//
// Data, cache first like Browse and People (scripts/export_view_caches.py):
//   public/cache/project_cards.json   projects + teams + linked facilities
//   public/cache/site_groups.json     one row per facility: its networks
//                                     and its named locations
// and DuckDB only if a fetch fails. PROJECTS_SQL and SITES_SQL below must
// stay identical in row shape to their copies in that script. Network
// names come from the vocab CSV the filter sidebar already uses.

import { getConn, whenReady, unwrapRow } from '../db.js';
import { DATA_BASE } from '../config.js';
import { fetchCSV } from '../csv.js';
import { SCOPES, DEFAULT_SCOPE } from '../filters.js';

let _container = null;
let _projects = null;
let _sites = null;
let _networks = null;       // slug → { label, name, level, url }
let _q = '';
let _scope = DEFAULT_SCOPE;

const ARID_NETWORK = 'arid-unm';
const NO_NETWORK = '_none';
// A group with more sites than this starts collapsed.
const OPEN_LIMIT = 15;

const PROJECTS_SQL = `
  WITH team AS (
    SELECT pp.project_id,
           list(struct_pack(
             person_id := p.person_id,
             name      := p.name,
             role      := pp.role,
             title     := pp.title
           ) ORDER BY CASE pp.role
                        WHEN 'lead-PI'   THEN 0
                        WHEN 'PI'        THEN 1
                        WHEN 'co-PI'     THEN 2
                        WHEN 'leader'    THEN 3
                        WHEN 'co-leader' THEN 4
                        WHEN 'manager'   THEN 6
                        ELSE 5
                      END, p.name_family, p.name) AS team
    FROM project_personnel pp
    JOIN people p ON p.person_id = pp.person_id
    GROUP BY pp.project_id
  ),
  sites AS (
    SELECT pf.project_id,
           list(struct_pack(
             facility_id := f.facility_id,
             name        := f.canonical_name,
             acronym     := f.acronym,
             relation    := pf.relation
           ) ORDER BY f.canonical_name) AS facilities
    FROM project_facilities pf
    JOIN facilities f ON f.facility_id = pf.facility_id
    GROUP BY pf.project_id
  )
  SELECT pr.project_id                    AS id,
         pr.name,
         pr.acronym,
         pr.parent_project_id             AS parent_id,
         par.name                         AS parent_name,
         pr.description,
         pr.url,
         pr.external_url,
         pr.funding_text,
         pr.extent_label,
         pr.lat,
         pr.lng,
         pr.location_precision,
         pr.source_url,
         CAST(pr.retrieved_at AS VARCHAR) AS retrieved_at,
         pr.confidence,
         pr.notes,
         lf.facility_id                   AS lead_facility_id,
         lf.acronym                       AS lead_acronym,
         lf.canonical_name                AS lead_name,
         t.team,
         s.facilities
  FROM projects pr
  LEFT JOIN projects par  ON par.project_id = pr.parent_project_id
  LEFT JOIN facilities lf ON lf.facility_id = pr.lead_facility_id
  LEFT JOIN team t        ON t.project_id   = pr.project_id
  LEFT JOIN sites s       ON s.project_id   = pr.project_id
  ORDER BY pr.name`;

const SITES_SQL = `
  WITH nets AS (
    SELECT facility_id, list(network_id ORDER BY network_id) AS networks
    FROM network_membership
    GROUP BY facility_id
  ),
  locs AS (
    SELECT facility_id,
           list(struct_pack(
             label := label,
             role  := role,
             lat   := lat,
             lng   := lng
           ) ORDER BY role, label) AS locations
    FROM locations
    GROUP BY facility_id
  ),
  prim AS (
    SELECT facility_id, min(sphere_slug) AS primary_sphere
    FROM facility_spheres
    WHERE role = 'primary'
    GROUP BY facility_id
  ),
  arid AS (
    SELECT DISTINCT facility_id FROM facility_spheres WHERE sphere_slug = 'arid'
  )
  SELECT f.facility_id                 AS id,
         f.canonical_name              AS name,
         f.acronym,
         f.facility_type               AS type,
         f.state,
         f.country,
         f.hq_lat                      AS lat,
         f.hq_lng                      AS lng,
         f.url,
         p.primary_sphere,
         (a.facility_id IS NOT NULL)   AS has_arid_sphere,
         n.networks,
         l.locations
  FROM facilities f
  LEFT JOIN nets n ON n.facility_id = f.facility_id
  LEFT JOIN locs l ON l.facility_id = f.facility_id
  LEFT JOIN prim p ON p.facility_id = f.facility_id
  LEFT JOIN arid a ON a.facility_id = f.facility_id
  ORDER BY f.canonical_name`;

const ROLE_LABELS = {
  'lead-PI': 'Lead PI',
  PI: 'PI',
  'co-PI': 'Co-PI',
  leader: 'Leader',
  'co-leader': 'Co-leader or mentor',
  manager: 'Program manager',
  team: 'Team',
};

const PRECISION_LABELS = {
  site: 'mapped at the site',
  county: 'mapped at the county centroid',
  city: 'mapped at the city centroid',
  statewide: 'statewide — no map point',
  regional: 'regional — no map point',
  none: 'no location given',
};

const LEVEL_LABELS = {
  'us-national': 'National',
  'us-regional': 'Regional',
  'canada-national': 'National (Canada)',
  international: 'International',
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/** Fetch a JSON cache, or run `sql` against DuckDB if the cache is absent. */
function cacheOrQuery(file, sql) {
  return (async () => {
    try {
      const res = await fetch(`${DATA_BASE}cache/${file}`, { cache: 'force-cache' });
      if (res.ok) return await res.json();
    } catch (_) { /* fall through to DuckDB */ }
    await whenReady();
    const conn = getConn();
    if (!conn) throw new Error('DuckDB connection not ready');
    const res = await conn.query(sql);
    return res.toArray().map((row) => unwrapRow(row.toJSON()));
  })();
}

/** Project cards, cache first. Shared with main.js for the map rings. */
let _cardsPromise = null;
export function loadProjectCards() {
  if (_cardsPromise) return _cardsPromise;
  _cardsPromise = cacheOrQuery('project_cards.json', PROJECTS_SQL).catch((err) => {
    _cardsPromise = null;      // let a later visit retry
    throw err;
  });
  return _cardsPromise;
}

async function loadNetworks() {
  const rows = await fetchCSV(`${DATA_BASE}vocab/networks.csv`);
  const out = new Map();
  for (const r of rows) {
    const label = (r.label || r.slug || '').trim();
    const alias = String(r.aliases || '').split('|')[0].trim();
    out.set(r.slug, {
      label,
      name: alias && alias.toLowerCase() !== label.toLowerCase() ? alias : '',
      level: r.level || '',
      url: r.url || '',
    });
  }
  return out;
}

// ── Projects (ARID) ──────────────────────────────────────────────────
function teamHtml(team) {
  if (!Array.isArray(team) || !team.length) return '';
  // Group by role, keeping the SQL's role order.
  const groups = [];
  for (const m of team) {
    let g = groups.find((x) => x.role === m.role);
    if (!g) groups.push(g = { role: m.role, members: [] });
    g.members.push(m);
  }
  return `<dl class="prj-team">${groups.map((g) => `
    <dt>${esc(ROLE_LABELS[g.role] || g.role)}</dt>
    <dd>${g.members.map((m) =>
    `<a class="prj-person" href="#/people/${encodeURIComponent(m.person_id)}"${
      m.title ? ` title="${esc(m.title)}"` : ''}>${esc(m.name)}</a>`).join('')}</dd>`).join('')}
  </dl>`;
}

function cardHtml(p, children) {
  const where = [p.extent_label, PRECISION_LABELS[p.location_precision]]
    .filter(Boolean).map(esc).join(' · ');
  const facilities = Array.isArray(p.facilities) && p.facilities.length
    ? `<p class="prj-row"><span class="prj-key">Facilities</span> ${p.facilities.map((f) =>
      `${esc(f.acronym || f.name)} <span class="prj-rel">(${esc(f.relation)})</span>`).join(', ')}</p>`
    : '';
  const links = [
    p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.lead_acronym || 'Source')} project page</a>` : '',
    p.external_url ? `<a href="${esc(p.external_url)}" target="_blank" rel="noopener">Project website</a>` : '',
  ].filter(Boolean).join(' · ');
  return `<article class="prj-card${children.length ? ' prj-card-parent' : ''}" id="prj-${esc(p.id)}">
    <header class="prj-card-head">
      <h3>${esc(p.name)}</h3>
      ${p.acronym ? `<span class="prj-acr">${esc(p.acronym)}</span>` : ''}
    </header>
    ${p.description ? `<p class="prj-desc">${esc(p.description)}</p>` : ''}
    ${where ? `<p class="prj-row"><span class="prj-key">Where</span> ${where}</p>` : ''}
    ${p.funding_text ? `<p class="prj-row"><span class="prj-key">Funding</span> ${esc(p.funding_text)}</p>` : ''}
    ${facilities}
    ${teamHtml(p.team)}
    ${p.notes ? `<p class="prj-note">${esc(p.notes)}</p>` : ''}
    <p class="prj-links">${links}${p.retrieved_at
    ? ` <span class="prj-retrieved">read ${esc(p.retrieved_at)}</span>` : ''}</p>
    ${children.length ? `<div class="prj-children">${children.join('')}</div>` : ''}
  </article>`;
}

function projectMatches(p, q) {
  if (!q) return true;
  const hay = [p.name, p.acronym, p.description, p.extent_label, p.funding_text,
    ...(p.team || []).map((m) => m.name),
    ...(p.facilities || []).map((f) => `${f.name} ${f.acronym || ''}`)]
    .join(' ').toLowerCase();
  return hay.includes(q);
}

/** Top-level project cards (children nested) that match the search. */
function projectCards(q) {
  const byParent = new Map();
  for (const p of _projects || []) {
    const key = p.parent_id || '';
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(p);
  }
  // A project shows when it, or anything beneath it, matches.
  const build = (p) => {
    const kids = (byParent.get(p.id) || []).map(build).filter(Boolean);
    if (!projectMatches(p, q) && !kids.length) return null;
    return cardHtml(p, kids);
  };
  return (byParent.get('') || []).map(build).filter(Boolean);
}

// ── Sites and groups ─────────────────────────────────────────────────
function inScope(site) {
  const lens = SCOPES[_scope] || SCOPES[DEFAULT_SCOPE];
  return lens.test({
    state: site.state,
    lng: site.lng,
    has_arid_sphere: site.has_arid_sphere,
    in_arid_network: (site.networks || []).includes(ARID_NETWORK),
  });
}

function siteMatches(s, q) {
  if (!q) return true;
  return [s.name, s.acronym, s.state, s.type,
    ...(s.locations || []).map((l) => l.label)]
    .join(' ').toLowerCase().includes(q);
}

function siteHtml(s) {
  const name = s.url
    ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>`
    : esc(s.name);
  const place = s.state || s.country || '';
  // The HQ point is the site's own location; list the others by name.
  const locs = (s.locations || []).filter((l) => l && l.label);
  const locHtml = locs.length
    ? `<div class="prj-site-locs">${locs.map((l) =>
      `<span title="${esc((l.role || 'location').replace(/-/g, ' '))}${
        l.lat != null && l.lng != null ? ` · ${Number(l.lat).toFixed(3)}, ${Number(l.lng).toFixed(3)}` : ''
      }">${esc(l.label)}</span>`).join('')}</div>`
    : '';
  return `<li class="prj-site">
    <div class="prj-site-main">
      <span class="prj-site-name">${name}${s.acronym ? ` <small>(${esc(s.acronym)})</small>` : ''}</span>
      <span class="prj-site-meta">${esc((s.type || '').replace(/-/g, ' '))}${place ? ` · ${esc(place)}` : ''}</span>
    </div>
    ${locHtml}
  </li>`;
}

function groupHtml(g) {
  const net = g.net;
  const head = `
    <span class="prj-group-label">${esc(net.label)}</span>
    ${net.name ? `<span class="prj-group-name">${esc(net.name)}</span>` : ''}
    ${LEVEL_LABELS[net.level] ? `<span class="prj-level">${esc(LEVEL_LABELS[net.level])}</span>` : ''}
    <span class="prj-group-count">${g.sites.length} site${g.sites.length === 1 ? '' : 's'}${
  g.total > g.sites.length ? ` of ${g.total}` : ''}${
  g.projects.length ? ` · ${g.nProjects} project${g.nProjects === 1 ? '' : 's'}` : ''}</span>`;
  const open = g.focus || _q || g.sites.length <= OPEN_LIMIT || g.id === ARID_NETWORK;
  return `<details class="prj-group" id="grp-${esc(g.id)}"${open ? ' open' : ''}>
    <summary>${head}</summary>
    ${net.url ? `<p class="prj-group-link"><a href="${esc(net.url)}" target="_blank" rel="noopener">${esc(net.url.replace(/^https?:\/\//, ''))}</a></p>` : ''}
    ${g.projects.length ? `
      <h4 class="prj-subhead">Projects</h4>
      <div class="prj-list">${g.projects.join('')}</div>` : ''}
    ${g.sites.length ? `
      ${g.projects.length ? '<h4 class="prj-subhead">Member sites</h4>' : ''}
      <ul class="prj-sites">${g.sites.map(siteHtml).join('')}</ul>` : ''}
  </details>`;
}

function buildGroups(q, targetId) {
  const scoped = (_sites || []).filter(inScope);
  const totals = new Map();         // network → sites in the whole catalogue
  for (const s of _sites || []) {
    const nets = s.networks && s.networks.length ? s.networks : [NO_NETWORK];
    for (const n of nets) totals.set(n, (totals.get(n) || 0) + 1);
  }
  const byNet = new Map();
  for (const s of scoped) {
    const nets = s.networks && s.networks.length ? s.networks : [NO_NETWORK];
    for (const n of nets) {
      if (!byNet.has(n)) byNet.set(n, []);
      byNet.get(n).push(s);
    }
  }

  const cards = projectCards(q);
  const nProjects = (_projects || []).filter((p) => !p.parent_id).length;
  const groups = [];
  for (const [id, sites] of byNet) {
    const net = id === NO_NETWORK
      ? { label: 'Not in a catalogued network', name: '', level: '', url: '' }
      : (_networks.get(id) || { label: id, name: '', level: '', url: '' });
    const groupHit = q && `${net.label} ${net.name}`.toLowerCase().includes(q);
    const shown = groupHit ? sites : sites.filter((s) => siteMatches(s, q));
    const projects = id === ARID_NETWORK ? cards : [];
    if (!shown.length && !projects.length) continue;
    groups.push({
      id, net, sites: shown, total: totals.get(id) || shown.length,
      projects, nProjects, focus: id === targetId,
    });
  }
  // ARID first (it carries the projects), unaffiliated last, the rest by
  // how many sites they have in scope.
  const rank = (g) => (g.id === ARID_NETWORK ? 0 : g.id === NO_NETWORK ? 2 : 1);
  groups.sort((a, b) => rank(a) - rank(b)
    || b.sites.length - a.sites.length
    || a.net.label.localeCompare(b.net.label));
  return { groups, nScoped: scoped.length };
}

function render(targetId) {
  const q = _q.trim().toLowerCase();
  const { groups, nScoped } = buildGroups(q, targetId);
  const nGroups = groups.filter((g) => g.id !== NO_NETWORK).length;
  const scopePills = Object.entries(SCOPES).map(([key, s]) =>
    `<button type="button" class="prj-scope${key === _scope ? ' active' : ''}"
       data-scope="${key}" title="${s.hint}">${s.label}</button>`).join('');

  _container.innerHTML = `
    <div class="prj-page">
      <header class="prj-header">
        <h1>Science groups, sites and projects</h1>
        <p class="prj-summary">
          <strong>${nGroups}</strong> networks and programs with
          <strong>${nScoped}</strong> sites in
          <strong>${SCOPES[_scope].label}</strong>. Each group lists its
          member sites and their named locations; a site in several
          networks appears under each. ARID's group also carries its
          projects, read from the institute's own pages.
        </p>
        <div class="prj-scopes" role="group" aria-label="Scope">${scopePills}</div>
        <input id="prj-q" type="search" placeholder="Search groups, sites, projects, people…"
               value="${esc(_q)}" autocomplete="off">
      </header>
      <div class="prj-groups">${groups.length
    ? groups.map(groupHtml).join('')
    : '<p class="no-data">Nothing matches that search in this scope.</p>'}</div>
    </div>`;

  _container.querySelector('#prj-q').addEventListener('input', (ev) => {
    _q = ev.target.value;
    const caret = ev.target.selectionStart;
    render(null);
    const el = _container.querySelector('#prj-q');
    el.focus();
    try { el.setSelectionRange(caret, caret); } catch (_) { /* not a text input */ }
  });
  for (const btn of _container.querySelectorAll('.prj-scope')) {
    btn.addEventListener('click', () => {
      _scope = btn.dataset.scope;
      try { localStorage.setItem('lto:projectsScope', _scope); } catch (_) { /* private mode */ }
      render(null);
    });
  }

  if (targetId) {
    const el = _container.querySelector(`#prj-${CSS.escape(targetId)}`)
      || _container.querySelector(`#grp-${CSS.escape(targetId)}`);
    if (el) {
      if (el.classList.contains('prj-card')) el.classList.add('prj-card-active');
      el.scrollIntoView({ block: 'start' });
    }
  }
}

export function initProjectsView(container) {
  _container = container;
  try {
    const saved = localStorage.getItem('lto:projectsScope');
    if (saved && SCOPES[saved]) _scope = saved;
  } catch (_) { /* private mode */ }
  _container.innerHTML = `
    <div class="prj-page">
      <p class="prj-status">Science groups loading…</p>
    </div>`;
}

export async function renderProjectsView(targetId) {
  if (!_container) return;
  if (!_projects || !_sites || !_networks) {
    try {
      [_projects, _sites, _networks] = await Promise.all([
        loadProjectCards(),
        cacheOrQuery('site_groups.json', SITES_SQL),
        loadNetworks(),
      ]);
    } catch (e) {
      console.error('[projects] load failed', e);
      _container.innerHTML = `<div class="prj-page"><p class="no-data">
        Could not load science groups: ${esc(e.message)}</p></div>`;
      return;
    }
  }
  // A deep link to a project or group outside the saved scope would land
  // on a page that does not contain it; widen to the whole catalogue.
  if (targetId && _networks.has(targetId) && !(_sites || []).some(
    (s) => (s.networks || []).includes(targetId) && inScope(s))) {
    _scope = 'all';
  }
  render(targetId);
}
