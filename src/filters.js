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
    state.setFilters({
      types: new Set(), countries: new Set(),
      areas: new Set(), networks: new Set(),
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

  // Async: load vocab CSVs, then insert research-area + network sections before type
  (async () => {
    try {
      const [areaRows, networkRows, typeRows] = await Promise.all([
        fetchCSV(`${BASE}vocab/research_areas.csv`),
        fetchCSV(`${BASE}vocab/networks.csv`),
        fetchCSV(`${BASE}vocab/facility_types.csv`),
      ]);

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

    const keyMap = { type: 'types', country: 'countries', area: 'areas', network: 'networks' };
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
