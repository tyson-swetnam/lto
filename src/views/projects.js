// projects.js — ARID projects (#/projects).
//
// A project is a body of work, not a place: who runs it, where the
// source says it happens, and which catalogued facilities it involves.
// Most have no map point at all (a statewide study pinned to a campus
// would be a false location), which is why they live here rather than
// on the Browse tab. Sub-projects (the CHANGES cores and their field
// efforts) nest under their parent.
//
// Routes:
//   #/projects        → every project, parents first
//   #/projects/<id>   → that project's card scrolled into view
//
// Data: projects + project_personnel + project_facilities, loaded by
// scripts/load_arid.py. Like Browse and People this reads a JSON cache
// first (public/cache/project_cards.json, written by
// scripts/export_view_caches.py) and falls through to DuckDB only if
// that fetch fails. PROJECTS_SQL below and PROJECTS_SQL in that script
// must stay identical in row shape.

import { getConn, whenReady, unwrapRow } from '../db.js';
import { DATA_BASE } from '../config.js';

let _container = null;
let _cached = null;
let _q = '';

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

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/** Project cards, cache first. Shared with main.js for the map rings. */
let _cardsPromise = null;
export function loadProjectCards() {
  if (_cardsPromise) return _cardsPromise;
  _cardsPromise = (async () => {
    try {
      const res = await fetch(`${DATA_BASE}cache/project_cards.json`, { cache: 'force-cache' });
      if (res.ok) return await res.json();
    } catch (_) { /* fall through to DuckDB */ }
    await whenReady();
    const conn = getConn();
    if (!conn) throw new Error('DuckDB connection not ready');
    const res = await conn.query(PROJECTS_SQL);
    return res.toArray().map((row) => unwrapRow(row.toJSON()));
  })().catch((err) => {
    _cardsPromise = null;      // let a later visit retry
    throw err;
  });
  return _cardsPromise;
}

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

function matches(p, q) {
  if (!q) return true;
  const hay = [p.name, p.acronym, p.description, p.extent_label, p.funding_text,
    ...(p.team || []).map((m) => m.name),
    ...(p.facilities || []).map((f) => `${f.name} ${f.acronym || ''}`)]
    .join(' ').toLowerCase();
  return hay.includes(q);
}

function render(targetId) {
  const rows = _cached || [];
  const q = _q.trim().toLowerCase();
  const byParent = new Map();
  for (const p of rows) {
    const key = p.parent_id || '';
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(p);
  }
  // A project shows when it, or anything beneath it, matches the search.
  const build = (p) => {
    const kids = (byParent.get(p.id) || []).map(build).filter(Boolean);
    if (!matches(p, q) && !kids.length) return null;
    return cardHtml(p, kids);
  };
  const cards = (byParent.get('') || []).map(build).filter(Boolean);
  const nPeople = new Set(rows.flatMap((p) => (p.team || []).map((m) => m.person_id))).size;
  const nTop = (byParent.get('') || []).length;
  const lead = rows.find((p) => p.lead_name);

  _container.innerHTML = `
    <div class="prj-page">
      <header class="prj-header">
        <h1>Projects</h1>
        <p class="prj-summary">
          <strong>${nTop}</strong> projects and
          <strong>${rows.length - nTop}</strong> sub-projects listed by
          ${lead ? esc(lead.lead_name) : 'the ARID Institute'}, with
          <strong>${nPeople}</strong> named team members. Everything here is
          read from the institute's own pages; a project has a map point only
          where its page names a place.
        </p>
        <input id="prj-q" type="search" placeholder="Search projects, people, places…"
               value="${esc(_q)}" autocomplete="off">
      </header>
      <div class="prj-list">${cards.length
    ? cards.join('')
    : '<p class="no-data">No project matches that search.</p>'}</div>
    </div>`;

  _container.querySelector('#prj-q').addEventListener('input', (ev) => {
    _q = ev.target.value;
    const caret = ev.target.selectionStart;
    render(null);
    const el = _container.querySelector('#prj-q');
    el.focus();
    try { el.setSelectionRange(caret, caret); } catch (_) { /* not a text input */ }
  });

  if (targetId) {
    const el = _container.querySelector(`#prj-${CSS.escape(targetId)}`);
    if (el) {
      el.classList.add('prj-card-active');
      el.scrollIntoView({ block: 'start' });
    }
  }
}

export function initProjectsView(container) {
  _container = container;
  _container.innerHTML = `
    <div class="prj-page">
      <p class="prj-status">Projects loading…</p>
    </div>`;
}

export async function renderProjectsView(targetId) {
  if (!_container) return;
  if (!_cached) {
    try {
      _cached = await loadProjectCards();
    } catch (e) {
      console.error('[projects] load failed', e);
      _container.innerHTML = `<div class="prj-page"><p class="no-data">
        Could not load projects: ${esc(e.message)}</p></div>`;
      return;
    }
  }
  render(targetId);
}
