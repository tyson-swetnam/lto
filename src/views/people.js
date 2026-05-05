// people.js — Researcher directory view (#/people and #/people/<id>).
//
// Shows every researcher in the cod-kmap dataset (~242) as a card
// listing their affiliations, role(s), publication+citation+co-author
// metrics, primary research area, and any external profile links
// (ORCID, OpenAlex, homepage).
//
// Routes:
//   #/people            → grid of all researcher cards (sortable)
//   #/people/<person_id> → that researcher's card scrolled into view
//                          and visually highlighted
//
// Data source: DuckDB-Wasm + the parquets we already ship
// (people, person_primary_groups, person_area_metrics, facility_personnel,
// facilities, facility_area_funding).

import { getConn, whenReady, unwrapRow } from '../db.js';

let _container = null;
let _renderedOnce = false;
let _sort = 'composite';   // 'composite' | 'name' | 'pubs' | 'citations' | 'coauthors' | 'funding'
let _qFilter = '';

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
// DuckDB-Wasm 1.29 returns BIGINTs as JS bigints and LIST<STRUCT> values
// as Arrow Vector objects (NOT plain JS arrays — Array.isArray() returns
// false for them). The People view's affiliations / areas / urls lists
// rendered empty because the Array.isArray() guards short-circuited.
// `unwrapRow` (defined in db.js) recursively converts every column so
// downstream code can treat lists like plain arrays and structs like
// plain objects.
function numify(o) {
  return unwrapRow(o);
}

async function fetchPeople() {
  await whenReady();
  const conn = getConn();
  if (!conn) throw new Error('DuckDB connection not ready');

  // Per-person aggregate row + list of affiliations + list of areas.
  // Cleaned-up version (DuckDB-Wasm is stricter than CLI DuckDB about
  // join-alias-shadowing-CTE-name and untyped empty-list literals):
  // separate area-list CTE, no correlated subqueries inside aggregate
  // arguments, no `COALESCE(x, [])` coercion games.
  const sql = `
    WITH per_pa AS (
      SELECT person_id,
             SUM(n_publications)  AS n_pubs,
             SUM(total_citations) AS total_citations,
             MAX(h_index)         AS h_index,
             SUM(n_co_authors)    AS n_coauth,
             SUM(composite_z)     AS composite_z
      FROM person_area_metrics
      GROUP BY person_id
    ),
    per_pa_areas AS (
      SELECT pam.person_id,
             list(struct_pack(
               area_id   := pam.area_id,
               area      := ra.label,
               n_pubs    := pam.n_publications,
               citations := pam.total_citations,
               h         := pam.h_index
             ) ORDER BY pam.composite_z DESC) AS areas
      FROM person_area_metrics pam
      LEFT JOIN research_areas ra ON ra.area_id = pam.area_id
      GROUP BY pam.person_id
    ),
    per_fund AS (
      SELECT fp.person_id,
             SUM(faf.total_usd_nominal) AS facility_funding_usd
      FROM facility_personnel fp
      JOIN facility_area_funding faf ON faf.facility_id = fp.facility_id
      GROUP BY fp.person_id
    ),
    per_aff AS (
      SELECT fp.person_id,
             list(struct_pack(
               role        := fp.role,
               title       := fp.title,
               facility    := COALESCE(f.acronym || ' — ' || f.canonical_name,
                                       f.canonical_name),
               facility_id := f.facility_id,
               url         := f.url,
               country     := f.country,
               is_key      := fp.is_key_personnel
             ) ORDER BY fp.is_key_personnel DESC, fp.role) AS affiliations
      FROM facility_personnel fp
      JOIN facilities f ON f.facility_id = fp.facility_id
      GROUP BY fp.person_id
    )
    SELECT p.person_id  AS id,
           p.name,
           p.orcid,
           p.openalex_id,
           p.google_scholar_id,
           p.homepage_url,
           p.research_interests,
           p.bio,
           g.primary_area_id,
           ra.label                            AS primary_area_label,
           COALESCE(pa.n_pubs, 0)              AS n_pubs,
           COALESCE(pa.total_citations, 0)     AS total_citations,
           COALESCE(pa.h_index, 0)             AS h_index,
           COALESCE(pa.n_coauth, 0)            AS n_coauth,
           COALESCE(pa.composite_z, 0)         AS composite_z,
           COALESCE(pf.facility_funding_usd, 0) AS facility_funding_usd,
           paa.areas                           AS areas,
           pa2.affiliations                    AS affiliations
    FROM   people p
    LEFT JOIN person_primary_groups g  ON g.person_id  = p.person_id
    LEFT JOIN research_areas       ra  ON ra.area_id   = g.primary_area_id
    LEFT JOIN per_pa               pa  ON pa.person_id = p.person_id
    LEFT JOIN per_pa_areas         paa ON paa.person_id = p.person_id
    LEFT JOIN per_fund             pf  ON pf.person_id = p.person_id
    LEFT JOIN per_aff              pa2 ON pa2.person_id = p.person_id
  `;
  const r = await conn.query(sql);
  return r.toArray().map((row) => numify(row.toJSON()));
}


function cardHtml(p) {
  const urls = [];
  if (p.homepage_url) urls.push(`<a href="${esc(p.homepage_url)}" target="_blank" rel="noopener">homepage</a>`);
  if (p.orcid)        urls.push(`<a href="https://orcid.org/${esc(p.orcid)}" target="_blank" rel="noopener">ORCID</a>`);
  if (p.openalex_id)  urls.push(`<a href="https://openalex.org/${esc(p.openalex_id)}" target="_blank" rel="noopener">OpenAlex</a>`);
  if (p.google_scholar_id) urls.push(`<a href="https://scholar.google.com/citations?user=${esc(p.google_scholar_id)}" target="_blank" rel="noopener">Google&nbsp;Scholar</a>`);

  // affiliations / areas may come back as null when a person has no
  // facility_personnel or no person_area_metrics rows. unwrapRow in
  // db.js handles the Arrow → plain JS conversion + drops null list
  // entries, but we still defend here against partial structs (e.g. a
  // list element that's an empty {} from a quirky DuckDB-Wasm decode).
  const affRaw = (Array.isArray(p.affiliations) ? p.affiliations : [])
    .filter((a) => a && (a.role || a.facility || a.title));
  const areaRaw = (Array.isArray(p.areas) ? p.areas : [])
    .filter((a) => a && (a.area || a.area_id));
  const aff = affRaw.slice(0, 4).map((a) => `
    <li>
      <strong>${esc(a.role || '—')}</strong>
      ${a.title ? ` · ${esc(a.title)}` : ''}
      <br><small>${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.facility || '')}</a>` : esc(a.facility || '')}${a.country ? ` <span class="ppl-flag">${esc(a.country)}</span>` : ''}</small>
    </li>`).join('');
  const moreAff = affRaw.length > 4
    ? `<li class="ppl-more">+${affRaw.length - 4} more</li>` : '';

  const areas = areaRaw.slice(0, 6).map((a) => `
    <li>
      <span class="ppl-area-label">${esc(a.area || a.area_id || '')}</span>
      <small>${fmtInt(a.n_pubs)} pubs · ${fmtInt(a.citations)} citations · h ${fmtInt(a.h)}</small>
    </li>`).join('');

  return `
  <article class="ppl-card" id="ppl-${esc(p.id)}" data-id="${esc(p.id)}">
    <header class="ppl-card-head">
      <h3>${esc(p.name)}</h3>
      ${p.primary_area_label
        ? `<span class="ppl-pchip">${esc(p.primary_area_label)}</span>`
        : ''}
    </header>
    <div class="ppl-metrics">
      <span class="ppl-metric"><strong>${fmtInt(p.n_pubs)}</strong><br>pubs</span>
      <span class="ppl-metric"><strong>${fmtInt(p.total_citations)}</strong><br>citations</span>
      <span class="ppl-metric"><strong>${fmtInt(p.h_index)}</strong><br>h-index</span>
      <span class="ppl-metric"><strong>${fmtInt(p.n_coauth)}</strong><br>co-authors</span>
      <span class="ppl-metric"><strong>${fmtUsd(p.facility_funding_usd)}</strong><br>funding base</span>
    </div>
    <div class="ppl-cols">
      <div>
        <h4>Affiliations</h4>
        <ul class="ppl-aff">${aff || '<li class="ppl-none">No facility roles recorded.</li>'}${moreAff}</ul>
      </div>
      <div>
        <h4>Research areas</h4>
        <ul class="ppl-areas">${areas || '<li class="ppl-none">No publications mapped to a cod-kmap area.</li>'}</ul>
      </div>
    </div>
    ${p.bio
      ? `<div class="ppl-bio"><h4>Bio</h4><p>${esc(p.bio)}</p></div>`
      : ''}
    ${p.research_interests
      ? `<div class="ppl-interests"><h4>Research interests</h4><p>${esc(p.research_interests)}</p></div>`
      : ''}
    ${urls.length ? `<footer class="ppl-links">${urls.join(' · ')}</footer>` : ''}
  </article>`;
}


function applyFilterSort(people) {
  const q = _qFilter.trim().toLowerCase();
  let rows = q
    ? people.filter((p) => {
        const aff = (Array.isArray(p.affiliations) ? p.affiliations : [])
          .filter((a) => a);
        const hay = [
          p.name, p.primary_area_label,
          ...aff.map((a) => a.facility || ''),
          ...aff.map((a) => a.role || ''),
        ].join(' ').toLowerCase();
        return hay.includes(q);
      })
    : people.slice();

  const cmp = {
    composite : (a, b) => (b.composite_z || 0) - (a.composite_z || 0),
    name      : (a, b) => String(a.name).localeCompare(String(b.name)),
    pubs      : (a, b) => (b.n_pubs || 0) - (a.n_pubs || 0),
    citations : (a, b) => (b.total_citations || 0) - (a.total_citations || 0),
    coauthors : (a, b) => (b.n_coauth || 0) - (a.n_coauth || 0),
    funding   : (a, b) => (b.facility_funding_usd || 0) - (a.facility_funding_usd || 0),
  }[_sort] || ((a, b) => (b.composite_z || 0) - (a.composite_z || 0));
  rows.sort(cmp);
  return rows;
}


let _cachedPeople = null;

async function renderDirectory(targetId) {
  if (!_container) return;
  const status = _container.querySelector('.ppl-status');
  if (status) status.textContent = 'Loading…';

  if (!_cachedPeople) {
    try {
      _cachedPeople = await fetchPeople();
    } catch (e) {
      if (status) status.textContent = `Failed to load: ${e.message}`;
      console.error(e);
      return;
    }
  }

  const rows = applyFilterSort(_cachedPeople);
  const cards = rows.map(cardHtml).join('');

  _container.innerHTML = `
    <div class="ppl-page">
      <header class="ppl-header">
        <h1>Researcher directory</h1>
        <p class="ppl-summary">
          <strong>${fmtInt(_cachedPeople.length)}</strong> researchers
          across the cod-kmap dataset.
          ${rows.length !== _cachedPeople.length
             ? `Showing <strong>${fmtInt(rows.length)}</strong> after filter.` : ''}
          Click into the Network knowledge map to see who appears in
          which research-area polygon, or use search/sort below to drill
          in here.
        </p>
        <div class="ppl-controls">
          <input id="ppl-q" type="search" placeholder="Search name, affiliation, role…" value="${esc(_qFilter)}">
          <label>Sort by:
            <select id="ppl-sort">
              <option value="composite"${_sort === 'composite' ? ' selected' : ''}>Composite (default)</option>
              <option value="name"${_sort === 'name' ? ' selected' : ''}>Name (A→Z)</option>
              <option value="pubs"${_sort === 'pubs' ? ' selected' : ''}>Publications</option>
              <option value="citations"${_sort === 'citations' ? ' selected' : ''}>Citations</option>
              <option value="coauthors"${_sort === 'coauthors' ? ' selected' : ''}>Co-authors</option>
              <option value="funding"${_sort === 'funding' ? ' selected' : ''}>Funding base</option>
            </select>
          </label>
        </div>
      </header>
      <div class="ppl-grid">${cards}</div>
      <p class="ppl-status" style="text-align:center;color:#64748b;padding:14px">Done.</p>
    </div>`;

  _container.querySelector('#ppl-q').addEventListener('input', (ev) => {
    _qFilter = ev.target.value;
    renderDirectory(targetId);  // re-render filtered list
  });
  _container.querySelector('#ppl-sort').addEventListener('change', (ev) => {
    _sort = ev.target.value;
    renderDirectory(targetId);
  });

  if (targetId) {
    const el = _container.querySelector(`#ppl-${CSS.escape(targetId)}`);
    if (el) {
      el.classList.add('ppl-card-active');
      requestAnimationFrame(() => el.scrollIntoView({
        behavior: 'smooth', block: 'start',
      }));
    }
  }
  _renderedOnce = true;
}


export function initPeopleView(container) {
  _container = container;
  _container.innerHTML = `
    <div class="ppl-page">
      <p class="ppl-status" style="padding:24px;color:#64748b">
        Researcher directory loading…
      </p>
    </div>`;
}

// renderPeopleView(targetId) — call with a person_id when navigating
// from #/people/<id>; without one for the plain directory view.
export function renderPeopleView(targetId) {
  if (!_container) return;
  renderDirectory(targetId).catch((e) => {
    console.error('[people] render failed', e);
    const s = _container.querySelector('.ppl-status');
    if (s) s.textContent = `Render failed: ${e.message}`;
  });
}
