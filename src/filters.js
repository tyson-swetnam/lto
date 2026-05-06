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

  // ── Filter sidebar ordering ──
  //
  // For an LTO catalog the most useful discovery facets are:
  //   1. ≥10-year-record toggle (Peters et al. 2013 inclusion gate)
  //   2. Primary sphere (atmosphere / cryosphere / terrestrial / agriculture
  //      / ocean-estuarine / freshwater)
  //   3. Network (LTER, NEON, USFS-EFR, LTAR, IOOS RAs, NERRS, AmeriFlux …)
  //   — those three answer "show me LTERs in the cryosphere with ≥30 yr"
  //
  // Everything else (research area, ecosystem, life zone, country, type,
  // established year range) is secondary and starts collapsed.
  //
  // Each LTO-specific facet is rendered with a stub body up front so the
  // section is visible even if its CSV fetch is slow / fails; the async
  // block at the bottom replaces stubBody with real labels.

  // 1. Long-term threshold — primary inclusion gate.
  const thresholdSection = makeFacetSection(
    'f-threshold', 'Long-term threshold',
    `<label><input type="checkbox" id="f-long-term-only" />
       Show only facilities with &ge;10y record</label>`,
    true,  // expanded by default
  );
  container.appendChild(thresholdSection);

  // 2. Primary sphere.
  const sphereSection = makeFacetSection(
    'f-sphere', 'Primary sphere', '<div class="facet-loading">Loading…</div>', true,
  );
  container.appendChild(sphereSection);

  // 3. Network — loaded async into this placeholder. The previous code
  // inserted the network section *before* type after the CSV fetch; now
  // we reserve its slot up-front so the layout doesn't reflow.
  const networkSection = makeFacetSection(
    'f-network', 'Network', '<div class="facet-loading">Loading…</div>', true,
  );
  container.appendChild(networkSection);

  // 4. Facility type. Hardcoded slug list curated for the LTO catalog —
  // only types that currently have ≥1 facility are rendered. Reserved or
  // never-instantiated slugs (industry, local-gov, university-institute,
  // vessel, virtual, foundation, observatory, international-*,
  // protected-area-state/private) stay in schema/vocab/facility_types.csv
  // so future ingests can use them but don't clutter the UI as
  // always-zero checkboxes.
  const typeSlugs = [
    'federal', 'state', 'nonprofit',
    // LTO-specific observatory types — these dominate the dataset.
    'experimental-forest-range', 'flux-tower', 'ltar-site',
    'streamgage-network', 'glacier-monitoring', 'atmospheric-baseline',
    'field-station', 'university-field-station', 'university-marine-lab',
    'protected-area-federal', 'network',
  ];
  const typeSection = makeFacetSection(
    'f-type', 'Facility type',
    typeSlugs.map((s) => checkbox('type', s, s)).join(''),
    false,  // collapsed
  );
  container.appendChild(typeSection);

  // 5. Established year range (numeric inputs, populated below).
  // Section appended later via the dedicated established block so the
  // markup stays in one place. Placeholder kept here only for ordering.

  // 6. Ecosystem type (LTO vocab, async).
  const ecosystemSection = makeFacetSection(
    'f-ecosystem', 'Ecosystem type', '<div class="facet-loading">Loading…</div>', false,
  );
  container.appendChild(ecosystemSection);

  // 7. Research area — async placeholder. The CSV fetch fills this with
  // the GCMD-aligned hierarchy.
  const areaSection = makeFacetSection(
    'f-area', 'Research area', '<div class="facet-loading">Loading…</div>', false,
  );
  container.appendChild(areaSection);

  // 8. Life zone (Holdridge) — narrow-audience facet.
  const lifeZoneSection = makeFacetSection(
    'f-life-zone', 'Life zone (Holdridge)', '<div class="facet-loading">Loading…</div>', false,
  );
  container.appendChild(lifeZoneSection);

  // 9. Country / territory — defaults to US + territories anyway, so collapsed.
  const countrySection = makeFacetSection(
    'f-country', 'Country / territory',
    COUNTRIES.map(([code, name]) => checkbox('country', code, name)).join(''),
    false,
  );
  container.appendChild(countrySection);

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

      // Fill the pre-allocated Network section. Show "ACRONYM — Full Name"
      // so users can both pattern-match on the acronym they know
      // (IOOS, NERRS, LTER…) and read the full organisation name. The
      // schema stores the short form in `label` and the expanded form(s)
      // in `aliases` (pipe-separated). Fall back to label alone if the
      // alias is missing or identical to the label.
      const netLabel = (r) => {
        const label = (r.label || '').trim();
        const alias = String(r.aliases || '').split('|')[0].trim();
        if (!alias || alias.toLowerCase() === label.toLowerCase()) return label;
        return `${label} — ${alias}`;
      };
      const netBody = networkSection.querySelector('.facet-body');
      if (netBody) {
        netBody.innerHTML = networkRows
          .map((r) => checkbox('network', r.slug, netLabel(r)))
          .join('');
      }

      // Fill the pre-allocated Research area section.
      const areaBody = areaSection.querySelector('.facet-body');
      if (areaBody) areaBody.innerHTML = buildAreaTree(areaRows);
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
