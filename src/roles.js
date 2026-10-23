// Role labels shared by the People and Browse cards.
//
// Facility roles come from the shared vocabulary
// (public/vocab/personnel_roles.csv, a copy of schema/vocab/). Project
// team roles (project_personnel, ARID wave) are free text in the project
// seeds and are not facility roles, so they are labelled here instead of
// being added to that vocabulary. An unknown value falls back to itself.

import { DATA_BASE } from './config.js';

const PROJECT_ROLE_LABELS = {
  PI: 'PI',
  'co-PI': 'Co-PI',
  leader: 'Leader',
  'co-leader': 'Co-leader',
  team: 'Team member',
};

let _labels = {};
let _loading = null;

// Fetch once; callers await it before rendering. Never rejects: a missing
// file leaves the slugs as labels.
export function loadRoleLabels() {
  if (_loading) return _loading;
  _loading = (async () => {
    try {
      const res = await fetch(`${DATA_BASE}vocab/personnel_roles.csv`, { cache: 'force-cache' });
      if (!res.ok) return;
      const lines = (await res.text()).split(/\r?\n/).slice(1);
      for (const line of lines) {
        const m = line.match(/^([^,]+),("[^"]*"|[^,]*)/);
        if (m) _labels[m[1].trim()] = m[2].replace(/^"|"$/g, '').trim();
      }
    } catch (_) { /* slugs it is */ }
  })();
  return _loading;
}

export function roleLabel(r) {
  if (!r) return '—';
  return _labels[r] || PROJECT_ROLE_LABELS[r] || _labels[String(r).toLowerCase()]
    || PROJECT_ROLE_LABELS[String(r).toLowerCase()] || r;
}
