/**
 * Minimal RFC-4180-ish CSV parser.
 * Returns an array of objects keyed by the first-row headers.
 * Handles: quoted fields, embedded commas, escaped double-quotes ("").
 */
export function parseCSV(text) {
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const headers = splitRow(lines[0]);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const values = splitRow(line);
    const obj = {};
    headers.forEach((h, idx) => { obj[h] = values[idx] ?? ''; });
    rows.push(obj);
  }
  return rows;
}

function splitRow(line) {
  const fields = [];
  let cur = '';
  let inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuote) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') { inQuote = false; }
      else { cur += ch; }
    } else {
      if (ch === '"') { inQuote = true; }
      else if (ch === ',') { fields.push(cur); cur = ''; }
      else { cur += ch; }
    }
  }
  fields.push(cur);
  return fields;
}

/** Fetch a CSV from a URL and return parsed rows. Caches by URL. */
const _cache = new Map();
export async function fetchCSV(url) {
  if (_cache.has(url)) return _cache.get(url);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`CSV fetch failed: ${url} (${res.status})`);
  const rows = parseCSV(await res.text());
  _cache.set(url, rows);
  return rows;
}
