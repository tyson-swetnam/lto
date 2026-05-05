import { fetchCSV } from './csv.js';
import { DATA_BASE as BASE } from './config.js';

// ISO 3166-1 alpha-2 codes that cover the Atlantic/Gulf/Pacific/Caribbean
// coastline the knowledge map tracks, paired with display names. The code
// stays as the data value (facilities.country is ISO alpha-2), only the
// label shown to the user becomes the full country / territory name.
// Ordered roughly North → South along the Americas then outward through
// the Caribbean to keep the vertical checklist intuitive to scan.
const COUNTRIES = [
  ['US', 'United States'],
  ['CA', 'Canada'],
  ['MX', 'Mexico'],
  ['BZ', 'Belize'],
  ['GT', 'Guatemala'],
  ['HN', 'Honduras'],
  ['SV', 'El Salvador'],
  ['NI', 'Nicaragua'],
  ['CR', 'Costa Rica'],
  ['PA', 'Panama'],
  ['CO', 'Colombia'],
  ['VE', 'Venezuela'],
  ['EC', 'Ecuador'],
  ['PE', 'Peru'],
  ['CL', 'Chile'],
  ['AR', 'Argentina'],
  ['UY', 'Uruguay'],
  ['BR', 'Brazil'],
  ['PR', 'Puerto Rico'],
  ['VI', 'U.S. Virgin Islands'],
  ['CU', 'Cuba'],
  ['JM', 'Jamaica'],
  ['DO', 'Dominican Republic'],
  ['HT', 'Haiti'],
  ['BS', 'Bahamas'],
  ['BB', 'Barbados'],
  ['KY', 'Cayman Islands'],
  ['TC', 'Turks and Caicos Islands'],
];

/** Build a collapsible facet section element. */
function makeFacetSection(id, title, bodyHtml, collapsed = false) {
  const sec = document.createElement('div');
  sec.className = 'facet-section' + (collapsed ? ' collapsed' : '');
  sec.id = id;
  sec.innerHTML = `
    <div class="facet-header">
      <h2>${title}</h2>
      <span class="facet-toggle">${collapsed ? '&#9660;' : '&#9650;'}</span>
    </div>
    <div class="facet-body">${bodyHtml}</div>
  `;
  sec.querySelector('.facet-header').addEventListener('click', () => {
    sec.classList.toggle('collapsed');
    sec.querySelector('.facet-toggle').innerHTML =
      sec.classList.contains('collapsed') ? '&#9660;' : '&#9650;';
  });
  return sec;
}

function checkbox(facet, value, label) {
  const safeVal = String(value).replace(/"/g, '&quot;');
  const safeLabel = String(label ?? value).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  return `<label><input type="checkbox" data-facet="${facet}" data-value="${safeVal}" /> ${safeLabel}</label>`;
}

/** Build tree HTML for research_areas (parent/child) */
function buildAreaTree(rows) {
  const roots = rows.filter((r) => !r.parent_slug);
  const childMap = {};
  rows.filter((r) => r.parent_slug).forEach((r) => {
    (childMap[r.parent_slug] ??= []).push(r);
  });
  let html = '';
  for (const root of roots) {
    html += checkbox('area', root.slug, root.label);
    if (childMap[root.slug]) {
      html += '<div class="child-item">';
      html += childMap[root.slug].map((c) => checkbox('area', c.slug, c.label)).join('');
      html += '</div>';
    }
  }
  return html;
}

export async function initFilters(container, state) {
  // "Clear all" link (only clears facility-filter checkboxes, not overlays)
  const clearLink = document.createElement('a');
  clearLink.id = 'clear-all';
  clearLink.textContent = 'Clear all filters';
  clearLink.href = '#';
  clearLink.addEventListener('click', (e) => {
    e.preventDefault();
    container.querySelectorAll('input[type=checkbox]').forEach((cb) => { cb.checked = false; });
    // Numeric / boolean LTO filters reset back to their defaults too.
    const ltMet = container.querySelector('#f-long-term-only');
    if (ltMet) ltMet.checked = false;
    const eMin = container.querySelector('#f-established-min');
    const eMax = container.querySelector('#f-established-max');
    if (eMin) eMin.value = '';
    if (eMax) eMax.value = '';
    state.setFilters({
      types: new Set(), countries: new Set(),
      areas: new Set(), networks: new Set(),
      spheres: new Set(), ecosystems: new Set(), lifeZones: new Set(),
      longTermOnly: false,
      establishedMin: null, establishedMax: null,
    });
  });
  container.appendChild(clearLink);

  // ── Facility type (loaded synchronously from hardcoded slugs first, labels async) ──
  //
  // Only types that currently have ≥1 facility in the dataset are rendered
  // as filter checkboxes. The five "reserved" slugs in the vocab CSV
  // (industry, local-gov, university-institute, vessel, virtual) stay in
  // schema/vocab/facility_types.csv so future ingests can use them, but
  // showing them as always-zero-match checkboxes just clutters the UI.
  // The async block below cross-checks the CSV against this list, so
  // dropping or re-enabling a slug is a single edit here.
  const typeSlugs = [
    'federal', 'state', 'university-marine-lab', 'nonprofit', 'foundation',
    'network', 'international-federal', 'international-university',
    'international-nonprofit', 'observatory',
    // Coastal-terrestrial protected-area facility types (R11 ingest).
    // These cover thousands of points (state parks, NWRs, etc.) so they
    // need to be toggleable in the Facility-type filter.
    'protected-area-federal', 'protected-area-state', 'protected-area-private',
  ];
  const typeSection = makeFacetSection(
    'f-type', 'Facility type',
    typeSlugs.map((s) => checkbox('type', s, s)).join(''),
    true,
  );
  container.appendChild(typeSection);

  // ── Country ──
  const countrySection = makeFacetSection(
    'f-country', 'Country / territory',
    // Value stays the ISO alpha-2 code (matches facilities.country in the
    // DB); label is the full country / territory name for readability.
    COUNTRIES.map(([code, name]) => checkbox('country', code, name)).join(''),
    true,
  );
  container.appendChild(countrySection);

  // ── LTO six-sphere model: primary sphere, ecosystem type, life zone ──
  //
  // These are LTO-specific facets driven by the new vocab CSVs in
  // public/vocab/. Each section is rendered with a stub body up front
  // so the section is visible even if the CSV fetch is slow / fails;
  // the async block below replaces stubBody with real labels once the
  // CSV loads. Default-collapsed for life zones (Holdridge classes are
  // long and narrow-audience), default-expanded for sphere + ecosystem.
  const sphereSection = makeFacetSection(
    'f-sphere', 'Primary sphere', '<div class="facet-loading">Loading…</div>', false,
  );
  container.appendChild(sphereSection);

  const ecosystemSection = makeFacetSection(
    'f-ecosystem', 'Ecosystem type', '<div class="facet-loading">Loading…</div>', true,
  );
  container.appendChild(ecosystemSection);

  const lifeZoneSection = makeFacetSection(
    'f-life-zone', 'Life zone (Holdridge)', '<div class="facet-loading">Loading…</div>', true,
  );
  container.appendChild(lifeZoneSection);

  // ── Long-term threshold (Peters et al. 2013) ──
  //
  // A simple boolean toggle: when checked, the SQL WHERE clause adds
  // `f.long_term_threshold_met = TRUE`, which is precomputed in the
  // facilities table by the ingest pipeline (established <= today-10y
  // AND record_length_years >= 10). Default off so users see the full
  // catalog first.
  const thresholdSection = makeFacetSection(
    'f-threshold', 'Long-term threshold',
    `<label><input type="checkbox" id="f-long-term-only" />
       Show only facilities with &ge;10y record</label>`,
    false,
  );
  container.appendChild(thresholdSection);

  // ── Established year range ──
  //
  // Two numeric inputs filtering on facilities.established (an INTEGER
  // year). Empty input = no bound. Validated lightly (we just coerce
  // to a Number; non-numeric input clears that bound).
  const yearSection = makeFacetSection(
    'f-established', 'Established year',
    `<div class="year-range">
       <label>Min <input type="number" id="f-established-min" min="1700" max="2100" step="1" placeholder="e.g. 1980" /></label>
       <label>Max <input type="number" id="f-established-max" min="1700" max="2100" step="1" placeholder="e.g. 2025" /></label>
     </div>`,
    true,
  );
  container.appendChild(yearSection);

  // Wire numeric / boolean LTO inputs separately from the unified
  // checkbox handler at the bottom of this function — they aren't
  // checkboxes (the threshold one *is* but it has its own state key)
  // and the change handler matches by data-facet attribute.
  thresholdSection.querySelector('#f-long-term-only').addEventListener('change', (ev) => {
    state.setFilters({ longTermOnly: !!ev.target.checked });
  });
  const onYearChange = () => {
    const minEl = yearSection.querySelector('#f-established-min');
    const maxEl = yearSection.querySelector('#f-established-max');
    const min = minEl.value === '' ? null : Number(minEl.value);
    const max = maxEl.value === '' ? null : Number(maxEl.value);
    state.setFilters({
      establishedMin: Number.isFinite(min) ? min : null,
      establishedMax: Number.isFinite(max) ? max : null,
    });
  };
  yearSection.querySelector('#f-established-min').addEventListener('change', onYearChange);
  yearSection.querySelector('#f-established-max').addEventListener('change', onYearChange);

  // Async: load vocab CSVs, then insert research-area + network sections before type
  (async () => {
    try {
      const [areaRows, networkRows, typeRows] = await Promise.all([
        fetchCSV(`${BASE}vocab/research_areas.csv`),
        fetchCSV(`${BASE}vocab/networks.csv`),
        fetchCSV(`${BASE}vocab/facility_types.csv`),
      ]);

      // LTO vocab — sphere / ecosystem / life-zone CSVs. Loaded with
      // Promise.allSettled so a missing CSV (e.g. on a deploy that
      // hasn't synced public/vocab/ yet) leaves its filter section
      // empty rather than wiping out the whole sidebar.
      Promise.allSettled([
        fetchCSV(`${BASE}vocab/spheres.csv`),
        fetchCSV(`${BASE}vocab/ecosystem_types.csv`),
        fetchCSV(`${BASE}vocab/life_zones.csv`),
      ]).then(([sphRes, ecoRes, lzRes]) => {
        const fillFacet = (section, facetKey, rows, emptyMsg) => {
          const body = section.querySelector('.facet-body');
          if (!body) return;
          if (!Array.isArray(rows) || rows.length === 0) {
            body.innerHTML = `<div class="facet-empty">${emptyMsg}</div>`;
            return;
          }
          body.innerHTML = rows
            .map((r) => checkbox(facetKey, r.slug, r.label || r.slug))
            .join('');
        };
        fillFacet(
          sphereSection, 'sphere',
          sphRes.status === 'fulfilled' ? sphRes.value : null,
          'Spheres vocab unavailable.'
        );
        fillFacet(
          ecosystemSection, 'ecosystem',
          ecoRes.status === 'fulfilled' ? ecoRes.value : null,
          'Ecosystem-type vocab unavailable.'
        );
        fillFacet(
          lifeZoneSection, 'life-zone',
          lzRes.status === 'fulfilled' ? lzRes.value : null,
          'Life-zone vocab unavailable.'
        );
      });

      // Update type labels now that we have the CSV. Filter the rows
      // against the in-use set above so "reserved" vocab entries
      // (industry / local-gov / university-institute / vessel / virtual)
      // stay in the schema but don't appear as dead-end checkboxes.
      const usedSlugs = new Set(typeSlugs);
      const typeBody = typeSection.querySelector('.facet-body');
      typeBody.innerHTML = typeRows
        .filter((r) => usedSlugs.has(r.slug))
        .map((r) => checkbox('type', r.slug, r.label))
        .join('');

      // Network section — show "ACRONYM — Full Name" so users can both
      // pattern-match on the acronym they know (IOOS, NERRS…) and read
      // the full organisation name. The schema stores the short form
      // in `label` and the expanded form(s) in `aliases` (pipe-separated
      // when a network goes by multiple names). Fall back to label
      // alone if no alias is on file or if the alias is identical
      // to the label (e.g. "Sea Grant" row whose alias is just "Sea
      // Grant"). Escaping happens inside checkbox().
      const netLabel = (r) => {
        const label = (r.label || '').trim();
        const alias = String(r.aliases || '').split('|')[0].trim();
        if (!alias || alias.toLowerCase() === label.toLowerCase()) return label;
        return `${label} — ${alias}`;
      };
      const netSection = makeFacetSection(
        'f-network', 'Network',
        networkRows.map((r) => checkbox('network', r.slug, netLabel(r))).join(''),
        true,
      );
      container.insertBefore(netSection, typeSection);

      // Research area section
      const areaSection = makeFacetSection(
        'f-area', 'Research area',
        buildAreaTree(areaRows),
        true,
      );
      container.insertBefore(areaSection, netSection);
    } catch (e) {
      console.warn('Could not load vocab CSVs for filters:', e);
    }
  })();

  // Unified change handler
  container.addEventListener('change', (ev) => {
    const input = ev.target;
    if (!(input instanceof HTMLInputElement)) return;
    const { facet, value } = input.dataset;
    if (!facet) return;

    const keyMap = {
      type: 'types', country: 'countries', area: 'areas', network: 'networks',
      // LTO six-sphere model facets.
      sphere: 'spheres', ecosystem: 'ecosystems', 'life-zone': 'lifeZones',
    };
    const key = keyMap[facet];
    if (!key) return;
    const set = new Set(state.filters[key]);
    if (input.checked) set.add(value);
    else set.delete(value);
    state.setFilters({ [key]: set });
  });
}

export function applyFilters(filterState) {
  const clauses = [];
  const params = [];

  if (filterState.types?.size) {
    clauses.push(`f.facility_type IN (${Array.from(filterState.types).map(() => '?').join(',')})`);
    params.push(...filterState.types);
  }
  if (filterState.countries?.size) {
    clauses.push(`f.country IN (${Array.from(filterState.countries).map(() => '?').join(',')})`);
    params.push(...filterState.countries);
  }
  if (filterState.areas?.size) {
    const slugs = Array.from(filterState.areas);
    clauses.push(
      `f.facility_id IN (SELECT al.facility_id FROM area_links al ` +
      `WHERE al.area_id IN (${slugs.map(() => '?').join(',')}))`
    );
    params.push(...slugs);
  }
  if (filterState.networks?.size) {
    const slugs = Array.from(filterState.networks);
    clauses.push(
      `f.facility_id IN (SELECT nm.facility_id FROM network_membership nm ` +
      `WHERE nm.network_id IN (${slugs.map(() => '?').join(',')}))`
    );
    params.push(...slugs);
  }
  // LTO six-sphere facets. Each is a slug-IN subquery against the new
  // crosswalk tables (facility_spheres, facility_ecosystems,
  // facility_life_zones). Wrapped so an empty Set → no clause emitted.
  if (filterState.spheres?.size) {
    const slugs = Array.from(filterState.spheres);
    clauses.push(
      `f.facility_id IN (SELECT fs.facility_id FROM facility_spheres fs ` +
      `WHERE fs.sphere_slug IN (${slugs.map(() => '?').join(',')}))`
    );
    params.push(...slugs);
  }
  if (filterState.ecosystems?.size) {
    const slugs = Array.from(filterState.ecosystems);
    clauses.push(
      `f.facility_id IN (SELECT fe.facility_id FROM facility_ecosystems fe ` +
      `WHERE fe.ecosystem_slug IN (${slugs.map(() => '?').join(',')}))`
    );
    params.push(...slugs);
  }
  if (filterState.lifeZones?.size) {
    const slugs = Array.from(filterState.lifeZones);
    clauses.push(
      `f.facility_id IN (SELECT fl.facility_id FROM facility_life_zones fl ` +
      `WHERE fl.life_zone_slug IN (${slugs.map(() => '?').join(',')}))`
    );
    params.push(...slugs);
  }
  // Long-term threshold (Peters et al. 2013): the boolean column is
  // precomputed in facilities.parquet by the ingest pipeline.
  if (filterState.longTermOnly) {
    clauses.push(`f.long_term_threshold_met = TRUE`);
  }
  // Established-year bounds. Use IS NOT NULL + bound so that a facility
  // with NULL `established` doesn't get accidentally swept in by a
  // permissive bound (DuckDB returns NULL for `f.established >= ?`
  // when established is NULL, which evaluates to false in WHERE — but
  // we add the explicit IS NOT NULL for symmetry with the threshold
  // clause and to make the intent obvious.
  if (Number.isFinite(filterState.establishedMin)) {
    clauses.push(`f.established IS NOT NULL AND f.established >= ?`);
    params.push(filterState.establishedMin);
  }
  if (Number.isFinite(filterState.establishedMax)) {
    clauses.push(`f.established IS NOT NULL AND f.established <= ?`);
    params.push(filterState.establishedMax);
  }
  if (filterState.q) {
    clauses.push(`(lower(f.canonical_name) LIKE ? OR lower(f.acronym) LIKE ?)`);
    const q = `%${filterState.q.toLowerCase()}%`;
    params.push(q, q);
  }

  return {
    where: clauses.length ? `WHERE ${clauses.join(' AND ')}` : '',
    params,
  };
}
