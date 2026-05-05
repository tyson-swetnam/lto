import { applyFilters } from './filters.js';
import { DATA_BASE } from './config.js';

let db = null;        // duckdb.AsyncDuckDB instance
let conn = null;
let ready = false;    // set once all parquet views are registered
let readyResolve = null;
const readyPromise = new Promise((r) => { readyResolve = r; });
let fallbackFeatures = null;

const PARQUET_BASE = `${DATA_BASE}parquet/`;

async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Arrow → plain JS unwrap.
//
// DuckDB-Wasm 1.29 returns LIST<STRUCT> columns as Arrow Vector objects
// (not plain JS arrays). They expose a numeric `.length` and integer-keyed
// access, but `Array.isArray()` returns false for them. This silently
// breaks views that gate on Array.isArray() (e.g. People + Network
// affiliation/area lists rendered "No facility roles recorded." even
// when the parquet had data).
//
// `arrowToPlain` walks any value returned by `row.toJSON()` and converts
// every Arrow Vector to a plain JS Array, every nested struct to a
// plain Object, and unwraps BigInts to Numbers (or strings if too big).
// Use it once after `row.toJSON()` and downstream code can treat
// everything as standard JS.
// ---------------------------------------------------------------------------

export function arrowToPlain(v) {
  if (v == null) return v;
  if (typeof v === 'bigint') {
    return (v <= Number.MAX_SAFE_INTEGER && v >= Number.MIN_SAFE_INTEGER)
      ? Number(v) : String(v);
  }
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
    return v;
  }
  if (v instanceof Date) {
    return v;
  }
  if (Array.isArray(v)) {
    // Filter out NULLs/undefineds — Arrow LIST columns can contain null
    // slots which the People view's render code is not defensive
    // against.
    return v.map(arrowToPlain).filter((x) => x != null);
  }
  // Arrow Vector / list-like object: numeric `.length`, indexable.
  // In apache-arrow ≥10 (which DuckDB-Wasm 1.29 ships), `vector[i]`
  // returns undefined and you have to call `vector.get(i)` to read a
  // value. Try .get first, fall back to bracket access, drop null
  // entries either way.
  if (typeof v === 'object' && typeof v.length === 'number') {
    const arr = [];
    const useGet = (typeof v.get === 'function');
    for (let i = 0; i < v.length; i++) {
      const raw = useGet ? v.get(i) : v[i];
      if (raw == null) continue;
      arr.push(arrowToPlain(raw));
    }
    return arr;
  }
  if (typeof v === 'object') {
    // Plain object / Arrow struct row. Arrow struct rows expose their
    // children as own properties via the Proxy returned by row.toJSON()
    // recursively, but in some versions only `.toArray()` / `.toJSON()`
    // unwrap them. Try .toJSON if available, then fall back to
    // Object.keys.
    if (typeof v.toJSON === 'function') {
      try {
        const j = v.toJSON();
        if (j !== v) return arrowToPlain(j);
      } catch (_) { /* fall through */ }
    }
    const out = {};
    for (const k of Object.keys(v)) out[k] = arrowToPlain(v[k]);
    return out;
  }
  return v;
}

// Convenience: unwrap every column of a row object in place. Same as
// `Object.fromEntries(Object.entries(o).map(([k,v]) => [k, arrowToPlain(v)]))`
// but mutates the input for hot paths.
export function unwrapRow(o) {
  if (o == null) return o;
  for (const k of Object.keys(o)) o[k] = arrowToPlain(o[k]);
  return o;
}

export async function loadFallback() {
  const geojson = await fetchJson(`${DATA_BASE}facilities.geojson`);
  fallbackFeatures = geojson.features || [];
  return fallbackFeatures;
}

// Return the DuckDB connection only after every parquet view has been
// registered. Callers that need to run arbitrary SQL should always
// `await whenReady()` first (or null-check both conn AND ready).
export function getConn() {
  return ready ? conn : null;
}

// Await this before issuing any SQL that doesn't go through query().
// Resolves once initDB() has finished registering all parquet views.
// Rejects if initDB is never called or fails (caller then falls back).
export function whenReady() {
  return readyPromise;
}

export async function initDB() {
  const duckdb = await import('@duckdb/duckdb-wasm');
  const bundles = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(bundles);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }),
  );
  const worker = new Worker(workerUrl);
  // Silent logger — the default ConsoleLogger streams every query-plan,
  // worker message, and parquet fetch event to the browser console at
  // INFO level, which quickly buries real warnings under hundreds of
  // {level:2, origin:4, …} entries per page load. Swap in a no-op logger
  // that only surfaces ERROR level events if DuckDB ever reports one.
  const logger = {
    log: (entry) => {
      if (entry && entry.level && entry.level <= 1) {
        console.error('[duckdb]', entry);
      }
    },
  };
  db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  const newConn = await db.connect();

  const tables = [
    'facilities', 'facility_types', 'locations',
    'funders', 'funding_links', 'funding_events',
    'research_areas', 'area_links', 'networks', 'network_membership',
    // Region-side (polygons as first-class rows + spatial containment edges).
    'regions', 'region_area_links', 'facility_regions',
    // People-side (staff, administrators, scientists, publications,
    // co-authorship graph). Empty tables are served as zero-row parquet
    // until the enrichment scripts populate them.
    'people', 'facility_personnel', 'publications', 'authorship',
    'person_areas', 'collaborations', 'publication_topics',
    // MVG (knowledge-map) precomputed groupings — written by
    // scripts/compute_primary_groups.py. One row per facility/person
    // assigning a single primary research area; one row per area with
    // its post-collapse status. Drives src/views/network.js.
    'facility_primary_groups', 'person_primary_groups',
    'research_areas_active',
    // Per-area dashboard metrics — written by
    // scripts/compute_area_metrics.py. Drives src/views/stats.js.
    'person_area_metrics', 'facility_area_funding',
    'funder_area_funding', 'area_coverage_matrix',
  ];
  for (const t of tables) {
    const url = `${PARQUET_BASE}${t}.parquet`;
    await newConn.query(`CREATE OR REPLACE VIEW ${t} AS SELECT * FROM read_parquet('${url}')`);
  }

  // Helper views the SQL tab + future visualisations rely on. These
  // are defined in schema/schema.sql for the canonical DuckDB but
  // they don't survive a parquet round-trip (you can't COPY a view to
  // parquet without materialising it; we keep them computed). Recreate
  // them in DuckDB-Wasm so the app's SQL canned queries work.
  const helperViews = [
    `CREATE OR REPLACE VIEW v_facility_funding_by_year AS
       SELECT f.facility_id,
              f.canonical_name              AS facility,
              f.acronym,
              fe.fiscal_year,
              SUM(fe.amount_usd)            AS total_usd_nominal,
              COUNT(*)                      AS n_awards,
              list(DISTINCT fu.name)        AS funders
       FROM facilities       f
       JOIN funding_events   fe ON fe.facility_id = f.facility_id
       JOIN funders          fu ON fu.funder_id   = fe.funder_id
       WHERE fe.fiscal_year IS NOT NULL AND fe.amount_usd IS NOT NULL
       GROUP BY f.facility_id, f.canonical_name, f.acronym, fe.fiscal_year`,

    `CREATE OR REPLACE VIEW v_funder_funding_by_year AS
       SELECT fu.funder_id,
              fu.name                       AS funder,
              fu.type                       AS funder_type,
              fe.fiscal_year,
              SUM(fe.amount_usd)            AS total_usd_nominal,
              COUNT(*)                      AS n_awards,
              COUNT(DISTINCT fe.facility_id) AS n_facilities
       FROM funders         fu
       JOIN funding_events  fe ON fe.funder_id = fu.funder_id
       WHERE fe.fiscal_year IS NOT NULL AND fe.amount_usd IS NOT NULL
       GROUP BY fu.funder_id, fu.name, fu.type, fe.fiscal_year`,

    `CREATE OR REPLACE VIEW v_facility_key_personnel AS
       SELECT f.facility_id,
              f.canonical_name         AS facility,
              f.acronym                AS facility_acronym,
              p.person_id,
              p.name,
              fp.role,
              fp.title,
              p.orcid,
              p.openalex_id,
              p.email,
              p.homepage_url,
              fp.start_date,
              fp.source_url
       FROM facility_personnel fp
       JOIN people     p ON p.person_id   = fp.person_id
       JOIN facilities f ON f.facility_id = fp.facility_id
       WHERE fp.is_key_personnel = true
         AND (fp.end_date IS NULL OR fp.end_date > CURRENT_DATE)`,

    `CREATE OR REPLACE VIEW v_funding_ledger AS
       SELECT fe.event_id, fe.fiscal_year, fe.period_start, fe.period_end,
              fu.name AS funder, fu.type AS funder_type,
              f.canonical_name AS facility, f.acronym AS facility_acronym,
              f.facility_type  AS facility_kind, f.country,
              fe.amount_usd    AS amount_usd_nominal, fe.amount_currency,
              fe.award_id, fe.award_title, fe.program, fe.relation,
              fe.source, fe.source_url, fe.retrieved_at, fe.confidence, fe.notes
       FROM funding_events fe
       JOIN funders    fu ON fu.funder_id  = fe.funder_id
       JOIN facilities f  ON f.facility_id = fe.facility_id`,

    `CREATE OR REPLACE VIEW v_person_enriched AS
       SELECT p.person_id,
              p.name,
              p.name_family,
              p.orcid,
              p.openalex_id,
              p.email,
              p.homepage_url,
              p.research_interests,
              p.status,
              list(DISTINCT f.canonical_name)  AS facilities,
              list(DISTINCT fp.role)           AS roles,
              list(DISTINCT ra.label)          AS research_areas,
              COUNT(DISTINCT a.publication_id) AS n_publications,
              MAX(pub.pub_year)                AS latest_pub_year
       FROM people p
       LEFT JOIN facility_personnel fp ON fp.person_id   = p.person_id
       LEFT JOIN facilities         f  ON f.facility_id  = fp.facility_id
       LEFT JOIN person_areas       pa ON pa.person_id   = p.person_id
       LEFT JOIN research_areas     ra ON ra.area_id     = pa.area_id
       LEFT JOIN authorship         a  ON a.person_id    = p.person_id
       LEFT JOIN publications       pub ON pub.publication_id = a.publication_id
       GROUP BY p.person_id, p.name, p.name_family, p.orcid, p.openalex_id,
                p.email, p.homepage_url, p.research_interests, p.status`,
  ];
  for (const sql of helperViews) {
    try { await newConn.query(sql); }
    catch (err) { console.warn('[db] helper view create failed:', err.message); }
  }

  // Only now — after every view is live — publish the connection to the
  // rest of the app and flip the readiness flag. This closes a race where
  // early readers (e.g. the Network tab loaded before initDB finishes)
  // would hit a connection with only the first few tables registered.
  conn = newConn;
  ready = true;
  if (readyResolve) readyResolve(conn);
}

export async function query(filterState) {
  if (!ready || !conn) {
    return filterFallback(filterState);
  }
  const { where, params } = applyFilters(filterState);
  // NOTE: we LEFT JOIN facility_regions + regions so every facility row
  // comes back with the list of overlay polygons it sits inside. The list
  // can be empty (e.g., an offshore research vessel that falls outside every
  // NMS / NERR / NPS / NEP / NEON / EPA polygon). This lets the popup show
  // "Inside: <sanctuary>, <EPA region>, <NEON domain>" without a second
  // round-trip for each click.
  const sql = `
    SELECT f.facility_id AS id,
           f.canonical_name AS name,
           f.acronym,
           f.facility_type AS type,
           f.country,
           f.hq_lat AS lat,
           f.hq_lng AS lng,
           f.url,
           f.parent_org,
           list(DISTINCT fu.name)        AS funders,
           list(DISTINCT ra.label)       AS areas,
           list(DISTINCT n.label)        AS networks,
           list(DISTINCT r.name)         AS regions,
           list(DISTINCT r.kind)         AS region_kinds
    FROM facilities f
    LEFT JOIN funding_links fl  ON fl.facility_id = f.facility_id
    LEFT JOIN funders fu        ON fu.funder_id  = fl.funder_id
    LEFT JOIN area_links al     ON al.facility_id = f.facility_id
    LEFT JOIN research_areas ra ON ra.area_id    = al.area_id
    LEFT JOIN network_membership nm ON nm.facility_id = f.facility_id
    LEFT JOIN networks n        ON n.network_id   = nm.network_id
    LEFT JOIN facility_regions fr ON fr.facility_id = f.facility_id
    LEFT JOIN regions r         ON r.region_id   = fr.region_id
    ${where}
    GROUP BY f.facility_id, f.canonical_name, f.acronym, f.facility_type,
             f.country, f.hq_lat, f.hq_lng, f.url, f.parent_org
  `;
  const prepared = await conn.prepare(sql);
  const result = await prepared.query(...params);

  // Emit the same GeoJSON Feature shape loadFallback() returns, so the map
  // source always sees real Features (with a geometry). If we pass raw rows
  // into a FeatureCollection, MapLibre silently drops every point because
  // the members have no `geometry`.
  return result.toArray().map((row) => {
    const o = row.toJSON();
    return {
      type: 'Feature',
      geometry: (o.lat != null && o.lng != null)
        ? { type: 'Point', coordinates: [o.lng, o.lat] }
        : null,
      properties: o,
    };
  }).filter((f) => f.geometry);
}

function filterFallback(filterState) {
  if (!fallbackFeatures) return [];
  const types = filterState.types?.size ? filterState.types : null;
  const countries = filterState.countries?.size ? filterState.countries : null;
  // areas/networks not available in GeoJSON; skip those filters in fallback mode
  const q = (filterState.q || '').toLowerCase();
  return fallbackFeatures.filter((feat) => {
    const p = feat.properties;
    if (types && !types.has(p.type)) return false;
    if (countries && !countries.has(p.country)) return false;
    if (q && !(`${p.name ?? ''} ${p.acronym ?? ''}`.toLowerCase().includes(q))) return false;
    return true;
  });
}
