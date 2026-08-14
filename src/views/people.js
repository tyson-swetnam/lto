// people.js — Researcher directory view (#/people and #/people/<id>).
//
// Shows every researcher in the lto dataset (~242) as a card
// listing their affiliations, role(s), publication+citation+co-author
// metrics, primary research area, and any external profile links
// (ORCID, OpenAlex, homepage).
//
// Routes:
//   #/people            → paged grid of all researcher cards (sortable)
//   #/people/<id>       → that researcher's card scrolled into view and
//                         visually highlighted. <id> may be a person_id
//                         OR a canonical_id from person_registry
//                         (orcid:… / openalex:…) — the registry panels on
//                         the Data/Stats tabs deep-link with canonical
//                         ids, while the Network tab still uses
//                         person_id. Both resolve to the same card.
//
// Cohorts: person_registry tags each identity is_site_personnel and/or
// is_scholar. The cache/SQL below folds those flags into a per-card
// `cohorts` field ('site', 'scholar', or 'site,scholar') and the pill
// row filters on it. When the shipped people_cards.json predates the
// registry join the field is absent on every card — the pill row then
// hides entirely rather than showing filters that can never match.
//
// Data source: DuckDB-Wasm + the parquets we already ship
// (people, person_primary_groups, person_area_metrics, facility_personnel,
// facilities, facility_area_funding, person_registry).

import { getConn, whenReady, unwrapRow } from '../db.js';
import { DATA_BASE } from '../config.js';

// 60 cards per page: enough that a page feels like a directory, small
// enough that innerHTML swaps stay instant on mobile. Filter and sort
// always run over the whole in-memory roster; only one page renders.
const PAGE_SIZE = 60;

// lto cohorts. There is no is_team here (that is a cod-kmap concept —
// lto has no org chart); the two registry flags plus their intersection
// are the whole space. `all` is the default and the fallback whenever
// the cards carry no cohort data.
const COHORTS = {
  all     : { label: 'All',             test: () => true },
  site    : { label: 'Site personnel',  test: (p) => hasCohort(p, 'site') },
  scholar : { label: 'Scholar harvest', test: (p) => hasCohort(p, 'scholar') },
  both    : { label: 'Both',            test: (p) => hasCohort(p, 'site') && hasCohort(p, 'scholar') },
};

let _container = null;
let _renderedOnce = false;
let _sort = 'composite';   // 'composite' | 'name' | 'pubs' | 'citations' | 'coauthors' | 'funding'
let _qFilter = '';
let _cohort = 'all';
let _page = 0;
let _focusId = null;       // resolved person_id to highlight, or null
let _unresolved = null;    // {id} when a deep link named nobody we ship

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
// Metric display: show "n/a" when there's no signal (zero or null) so
// the card doesn't read as a confident "this person has 0 publications"
// when the truth is "we have no data on this person yet". Only the
// per-person metric tiles use this; aggregate sums elsewhere keep
// showing 0 because 0 is a meaningful answer in those contexts.
function fmtMetric(n) {
  if (n == null || n === 0) return 'n/a';
  return Math.round(n).toLocaleString();
}
// The `cohorts` field arrives as a comma-joined string from the SQL
// (concat_ws), but tolerate a plain list too — the JSON cache and a
// future refactor could reasonably ship ['site','scholar'] instead.
function hasCohort(p, want) {
  const v = p && p.cohorts;
  if (v == null) return false;
  if (Array.isArray(v)) return v.includes(want);
  return String(v).split(',').includes(want);
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
  // Fast path: a pre-computed JSON cache built by
  // scripts/export_view_caches.py. This is the SAME data the heavy
  // DuckDB query below produces, so the cards render identically —
  // just shipped pre-aggregated so the browser does fetch + JSON.parse
  // instead of pulling 8 parquets, registering views, and running a
  // multi-CTE aggregation. On mobile that's a 5-10x speedup.
  try {
    const res = await fetch(`${DATA_BASE}cache/people_cards.json`,
      { cache: 'force-cache' });
    if (res.ok) return await res.json();
  } catch (_) { /* fall through to DuckDB */ }

  // Fallback: query DuckDB directly. Used during local dev before the
  // cache exists, or if the JSON 404s.
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
      -- person_area_metrics carries the person's TOTAL stats on every area row
      -- (per scripts/compute_lto_person_metrics.py), so MAX rolls them up to
      -- the per-person total without double-counting. composite_z is the
      -- within-area z-score so SUM gives a meaningful "breadth × strength"
      -- composite suitable for sorting researchers across areas.
      SELECT person_id,
             MAX(n_publications)  AS n_pubs,
             MAX(total_citations) AS total_citations,
             MAX(h_index)         AS h_index,
             MAX(n_co_authors)    AS n_coauth,
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
           pa2.affiliations                    AS affiliations,
           pr.canonical_id                     AS canonical_id,
           NULLIF(concat_ws(',',
             CASE WHEN pr.is_site_personnel THEN 'site' END,
             CASE WHEN pr.is_scholar THEN 'scholar' END), '') AS cohorts,
           pr.tier                             AS tier
    FROM   people p
    LEFT JOIN person_primary_groups g  ON g.person_id  = p.person_id
    LEFT JOIN research_areas       ra  ON ra.area_id   = g.primary_area_id
    LEFT JOIN per_pa               pa  ON pa.person_id = p.person_id
    LEFT JOIN per_pa_areas         paa ON paa.person_id = p.person_id
    LEFT JOIN per_fund             pf  ON pf.person_id = p.person_id
    LEFT JOIN per_aff              pa2 ON pa2.person_id = p.person_id
    LEFT JOIN person_registry      pr  ON pr.person_id = p.person_id
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
    <div class="ppl-metrics" title="Counts are computed from the LTO publication corpus only — i.e. the ~600 flagship papers manually curated across the 6 spheres. They are NOT career-wide h-index / citation totals; for that, follow the ORCID / OpenAlex / Google Scholar links above. The full per-author publication history will be backfilled by the CI-side OpenAlex enrichment script (see RUNBOOK.md step 2).">
      <span class="ppl-metric"><strong>${fmtMetric(p.n_pubs)}</strong><br>lto&nbsp;pubs</span>
      <span class="ppl-metric"><strong>${fmtMetric(p.total_citations)}</strong><br>lto&nbsp;cites</span>
      <span class="ppl-metric"><strong>${fmtMetric(p.h_index)}</strong><br>lto&nbsp;h-idx</span>
      <span class="ppl-metric"><strong>${fmtMetric(p.n_coauth)}</strong><br>lto&nbsp;co-authors</span>
      <span class="ppl-metric"><strong>${fmtUsd(p.facility_funding_usd)}</strong><br>funding base</span>
    </div>
    <div class="ppl-metrics-caveat">
      <small>* counts reflect <strong>only the flagship papers in the LTO corpus</strong> (~600 across all sites);
      not full-career stats. Open the ORCID/Scholar links for true career numbers.</small>
    </div>
    <div class="ppl-cols">
      <div>
        <h4>Affiliations</h4>
        <ul class="ppl-aff">${aff || '<li class="ppl-none">No facility roles recorded.</li>'}${moreAff}</ul>
      </div>
      <div>
        <h4>Research areas</h4>
        <ul class="ppl-areas">${areas || '<li class="ppl-none">No publications mapped to an lto area.</li>'}</ul>
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
  const test = (COHORTS[_cohort] || COHORTS.all).test;
  const q = _qFilter.trim().toLowerCase();
  let rows = people.filter(test);
  if (q) {
    rows = rows.filter((p) => {
      const aff = (Array.isArray(p.affiliations) ? p.affiliations : [])
        .filter((a) => a);
      const hay = [
        p.name, p.primary_area_label,
        ...aff.map((a) => a.facility || ''),
        ...aff.map((a) => a.role || ''),
      ].join(' ').toLowerCase();
      return hay.includes(q);
    });
  }

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

// A deep link that resolves to nobody gets an explanation, not a silent
// unfiltered directory. Deliberately worded so "not shipped" is not read
// as "does not exist" — the registry currently ships core-tier identities
// only, and the scholar-harvest ids land in a later wave.
function noticeHtml(id) {
  return `<div class="ppl-notice" role="status">
    <span>The link target <code>${esc(id)}</code> did not match anyone in
    the directory — it is neither a person_id nor a canonical id
    (orcid:… / openalex:…) of a researcher shipped to the browser. It may
    belong to an identity the registry has not shipped yet, which is a
    coverage gap, not evidence the person does not exist.</span>
    <button type="button" class="ppl-notice-dismiss" aria-label="Dismiss notice">&times;</button>
  </div>`;
}

// Cohort pill row. Rendered only when at least one card actually carries
// a cohorts value — an old people_cards.json (pre-registry-join) has no
// such field, and a pill row where only "All" can ever match would read
// as a bug. Hiding the whole row degrades gracefully to the old UI.
function cohortRowHtml() {
  if (!_cachedPeople || !_cachedPeople.some((p) => p.cohorts)) return '';
  const pills = Object.entries(COHORTS).map(([k, c]) => `
    <button type="button" class="ppl-cohort${k === _cohort ? ' ppl-cohort-on' : ''}" data-cohort="${k}">
      ${esc(c.label)} <span class="ppl-cohort-n">${fmtInt(_cachedPeople.filter(c.test).length)}</span>
    </button>`).join('');
  return `<div class="ppl-cohorts">${pills}</div>`;
}

// Repaint the grid + notice + summary + pager from current state. The
// shell (header, search input, sort select, cohort pills) is never
// touched here, so the search box keeps focus and caret across repaints.
function paint() {
  if (!_container) return;
  const grid = _container.querySelector('.ppl-grid');
  if (!grid) return;

  const slot = _container.querySelector('#ppl-notice-slot');
  if (slot) {
    slot.innerHTML = _unresolved ? noticeHtml(_unresolved.id) : '';
    const dismiss = slot.querySelector('.ppl-notice-dismiss');
    if (dismiss) {
      dismiss.addEventListener('click', () => {
        _unresolved = null;
        paint();
      });
    }
  }

  const rows = applyFilterSort(_cachedPeople);
  const nPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  if (_page > nPages - 1) _page = nPages - 1;
  if (_page < 0) _page = 0;
  const start = _page * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);

  grid.innerHTML = pageRows.length
    ? pageRows.map(cardHtml).join('')
    : '<p class="ppl-none" style="padding:24px">No researchers match this filter.</p>';

  const summary = _container.querySelector('.ppl-summary');
  if (summary) {
    summary.innerHTML =
      `<strong>${fmtInt(_cachedPeople.length)}</strong> researchers `
      + `across the lto dataset.`
      + (rows.length !== _cachedPeople.length
          ? ` Showing <strong>${fmtInt(rows.length)}</strong> after filter.`
          : '')
      + (nPages > 1
          ? ` Cards <strong>${fmtInt(start + 1)}–${fmtInt(start + pageRows.length)}</strong>`
            + ` of ${fmtInt(rows.length)} on this page.`
          : '')
      + ` Click into the Network knowledge map to see who appears in `
      + `which research-area polygon, or use search/sort below to drill in here.`;
  }

  const pager = _container.querySelector('#ppl-pager');
  if (pager) {
    pager.innerHTML = nPages > 1 ? `
      <button type="button" data-page="first" ${_page === 0 ? 'disabled' : ''}>&laquo; First</button>
      <button type="button" data-page="prev"  ${_page === 0 ? 'disabled' : ''}>&lsaquo; Prev</button>
      <span class="ppl-pageno">Page ${fmtInt(_page + 1)} of ${fmtInt(nPages)}</span>
      <button type="button" data-page="next" ${_page >= nPages - 1 ? 'disabled' : ''}>Next &rsaquo;</button>
      <button type="button" data-page="last" ${_page >= nPages - 1 ? 'disabled' : ''}>Last &raquo;</button>` : '';
    for (const btn of pager.querySelectorAll('button[data-page]')) {
      btn.addEventListener('click', () => {
        const to = { first: 0, prev: _page - 1, next: _page + 1, last: nPages - 1 }[btn.dataset.page];
        _page = Math.min(Math.max(0, to), nPages - 1);
        paint();
        const head = _container.querySelector('.ppl-header');
        if (head) head.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
  }

  // Highlight + scroll to a deep-linked card if it is on this page.
  if (_focusId) {
    const el = grid.querySelector(`#ppl-${CSS.escape(_focusId)}`);
    if (el) {
      el.classList.add('ppl-card-active');
      requestAnimationFrame(() => el.scrollIntoView({
        behavior: 'smooth', block: 'start',
      }));
    }
  }
}

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

  // With no cohort data on any card the pill row is hidden, so the state
  // must never be stuck on a filter the user cannot see or change.
  if (!_cachedPeople.some((p) => p.cohorts)) _cohort = 'all';

  // Multi-id deep-link resolution: #/people/<id> accepts a person_id
  // (Network tab, old links) or a canonical_id from person_registry
  // (orcid:… / openalex:…). Either resolves to the same card; the
  // highlight mechanism below always keys on person_id.
  _focusId = null;
  _unresolved = null;
  if (targetId) {
    const hit = _cachedPeople.find((p) => p.id === targetId)
             || _cachedPeople.find((p) => p.canonical_id === targetId);
    if (hit) {
      _focusId = hit.id;
      // The target may sit outside the active cohort filter; landing on
      // an empty or wrong page would look like the link is broken.
      _cohort = 'all';
    } else {
      _unresolved = { id: targetId };
    }
  }

  // First render builds the page chrome (header + input + select +
  // pills + grid). Subsequent renders only swap the grid + summary +
  // pager (see paint). Otherwise re-rendering destroys the search input
  // element on every keystroke, which kills focus + the cursor position
  // and makes the search bar unusable on mobile.
  if (!_container.querySelector('.ppl-grid')) {
    _container.innerHTML = `
      <div class="ppl-page">
        <header class="ppl-header">
          <h1>Researcher directory</h1>
          <p class="ppl-summary"></p>
          <div class="ppl-controls">
            <input id="ppl-q" type="search" placeholder="Search name, affiliation, role…" value="${esc(_qFilter)}">
            <label>Sort by:
              <select id="ppl-sort">
                <option value="composite">Composite (default)</option>
                <option value="name">Name (A→Z)</option>
                <option value="pubs">Publications</option>
                <option value="citations">Citations</option>
                <option value="coauthors">Co-authors</option>
                <option value="funding">Funding base</option>
              </select>
            </label>
          </div>
          ${cohortRowHtml()}
        </header>
        <div id="ppl-notice-slot"></div>
        <div class="ppl-grid"></div>
        <div class="ppl-pager" id="ppl-pager"></div>
        <p class="ppl-status" style="text-align:center;color:#64748b;padding:14px">Done.</p>
      </div>`;

    // Debounce the search input. Without this, every keystroke triggers
    // a full re-render of 60+ cards — on mobile that means the keyboard
    // visibly stutters. 120ms is below the threshold of perceptible
    // latency but coarse enough that fast typing only re-renders once
    // per word.
    const qInput = _container.querySelector('#ppl-q');
    let qTimer = null;
    qInput.addEventListener('input', (ev) => {
      const v = ev.target.value;
      clearTimeout(qTimer);
      qTimer = setTimeout(() => {
        _qFilter = v;
        _page = 0;
        _focusId = null;
        _unresolved = null;
        paint();
      }, 120);
    });
    _container.querySelector('#ppl-sort').addEventListener('change', (ev) => {
      _sort = ev.target.value;
      _page = 0;
      paint();
    });
    for (const btn of _container.querySelectorAll('.ppl-cohort')) {
      btn.addEventListener('click', () => {
        _cohort = btn.dataset.cohort;
        _page = 0;
        _focusId = null;
        _unresolved = null;
        for (const b of _container.querySelectorAll('.ppl-cohort')) {
          b.classList.toggle('ppl-cohort-on', b.dataset.cohort === _cohort);
        }
        paint();
      });
    }
  } else {
    // Shell survives; resync the pill active state (a deep link may have
    // reset the cohort to 'all' above).
    for (const b of _container.querySelectorAll('.ppl-cohort')) {
      b.classList.toggle('ppl-cohort-on', b.dataset.cohort === _cohort);
    }
  }

  // Sync sort dropdown to current state (in case it was set externally).
  const sortSel = _container.querySelector('#ppl-sort');
  if (sortSel && sortSel.value !== _sort) sortSel.value = _sort;

  // A deep link has to land on the page its card is actually on, which
  // depends on the active sort + filters — compute the page index first.
  if (_focusId) {
    const rows = applyFilterSort(_cachedPeople);
    const idx = rows.findIndex((p) => p.id === _focusId);
    if (idx >= 0) _page = Math.floor(idx / PAGE_SIZE);
  }
  paint();

  const statusEl = _container.querySelector('.ppl-status');
  if (statusEl) statusEl.textContent = 'Done.';
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

// renderPeopleView(targetId) — call with a person_id OR canonical_id
// (orcid:… / openalex:…) when navigating from #/people/<id>; without one
// for the plain directory view.
export function renderPeopleView(targetId) {
  if (!_container) return;
  renderDirectory(targetId).catch((e) => {
    console.error('[people] render failed', e);
    const s = _container.querySelector('.ppl-status');
    if (s) s.textContent = `Render failed: ${e.message}`;
  });
}
