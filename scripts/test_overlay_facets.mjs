// Exercises src/overlay-facets.js against the real manifest + vocab.
//
//     node scripts/test_overlay_facets.mjs      # exit 0 = green
//
// Regression guard for a bug reported twice: filtering the facility
// points left the estuary (NERR/NEP) and NEON overlays painted, so the
// map read as unfiltered. Assertions cover both directions — the layers
// must vanish when the facets exclude them AND survive when they don't —
// plus tag-table hygiene (every id is a real overlay, every slug is in
// the vocab CSV), which is what silently rots when a layer is renamed.
// No test framework: this is plain node, and it stays out of the deploy
// staging list because deploy.yml ships only src/ public/ docs/.
import { readFileSync } from 'node:fs';
import {
  SPHERE_TAGS, NETWORK_TAGS, RESULTS_DUPLICATING,
  facetsNarrowing, overlayHiddenByFilters,
} from '../src/overlay-facets.js';

const ROOT = new URL('..', import.meta.url).pathname;
const manifest = JSON.parse(readFileSync(`${ROOT}/public/overlays/manifest.json`, 'utf8'));
const slugs = (f) => new Set(readFileSync(`${ROOT}/public/vocab/${f}`, 'utf8')
  .trim().split('\n').slice(1).map((l) => l.split(',')[0]));
const sphereSlugs = slugs('spheres.csv');
const networkSlugs = slugs('networks.csv');

let fail = 0;
const ok = (cond, msg) => { if (!cond) { fail++; console.log(`FAIL ${msg}`); } else console.log(`ok   ${msg}`); };
const F = (o) => ({ spheres: new Set(), ecosystems: new Set(), lifeZones: new Set(),
                    networks: new Set(), types: new Set(), countries: new Set(),
                    areas: new Set(), ...o });

// 1. every tagged id exists in the manifest, every tag in the vocab
for (const [id, tags] of Object.entries(SPHERE_TAGS)) {
  ok(id in manifest, `SPHERE_TAGS ${id} is a real overlay`);
  for (const t of tags) ok(sphereSlugs.has(t), `sphere slug ${t} (${id}) is in spheres.csv`);
}
for (const [id, nets] of Object.entries(NETWORK_TAGS)) {
  ok(id in manifest, `NETWORK_TAGS ${id} is a real overlay`);
  for (const n of nets) ok(networkSlugs.has(n), `network slug ${n} (${id}) is in networks.csv`);
}
for (const id of RESULTS_DUPLICATING) ok(id in manifest, `RESULTS_DUPLICATING ${id} is a real overlay`);

// 2. no facets → nothing hides (the default view keeps every layer)
ok(!facetsNarrowing(F({})), 'no facets selected → not narrowing');
for (const id of Object.keys(manifest)) {
  ok(!overlayHiddenByFilters(id, F({})), `no facets → ${id} stays visible`);
}

// 3. the reported bug: pick a non-coastal sphere, estuary + NEON go away
const arid = F({ spheres: new Set(['arid']) });
ok(overlayHiddenByFilters('nerr-reserves', arid), 'arid sphere hides NERR estuary reserves');
ok(overlayHiddenByFilters('nep-programs', arid), 'arid sphere hides National Estuary Program');
ok(overlayHiddenByFilters('marine-sanctuaries', arid), 'arid sphere hides marine sanctuaries');
ok(overlayHiddenByFilters('neon-sites', arid), 'arid sphere hides NEON site polygons');
ok(!overlayHiddenByFilters('epa-regions', arid), 'arid sphere leaves EPA admin context alone');
ok(!overlayHiddenByFilters('neon-domains', arid), 'arid sphere leaves NEON domain context alone');

// 4. the ocean sphere KEEPS its own layers (no over-hiding)
const ocean = F({ spheres: new Set(['ocean-estuarine']) });
ok(!overlayHiddenByFilters('nerr-reserves', ocean), 'ocean sphere keeps NERR reserves');
ok(!overlayHiddenByFilters('ramsar-us', ocean), 'ocean sphere keeps Ramsar wetlands');
ok(!overlayHiddenByFilters('ramsar-us', F({ spheres: new Set(['freshwater']) })),
   'freshwater sphere keeps Ramsar wetlands (dual-tagged)');

// 5. the network facet — the gap this commit closes
const neonOnly = F({ networks: new Set(['neon']) });
ok(overlayHiddenByFilters('nerr-reserves', neonOnly), 'NEON network hides estuary reserves');
ok(overlayHiddenByFilters('marine-sanctuaries', neonOnly), 'NEON network hides marine sanctuaries');
const nerrsOnly = F({ networks: new Set(['nerrs']) });
ok(!overlayHiddenByFilters('nerr-reserves', nerrsOnly), 'NERRS network keeps estuary reserves');
ok(overlayHiddenByFilters('nep-programs', nerrsOnly), 'NERRS network hides the NEP layer');
ok(overlayHiddenByFilters('neon-sites', nerrsOnly), 'NERRS network hides NEON site polygons');

// 6. a type facet alone still clears the results-duplicating layer
const typeOnly = F({ types: new Set(['flux-tower']) });
ok(overlayHiddenByFilters('neon-sites', typeOnly), 'type facet hides NEON site polygons');
ok(!overlayHiddenByFilters('coastal-wilderness', typeOnly),
   'type facet leaves sphere-governed context layers alone');

// 7. country/area are not narrowing facets for overlays
ok(!facetsNarrowing(F({ countries: new Set(['US']), areas: new Set(['hydrology']) })),
   'country/area selections do not hide overlays');

console.log(fail ? `\n${fail} FAILURE(S)` : '\nall assertions passed');
process.exit(fail ? 1 : 0);
