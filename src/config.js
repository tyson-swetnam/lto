// All data files live under public/ (sibling of index.html). Pages serves
// the repo root, so DATA_BASE resolves to /<repo>/public/.

export const DATA_BASE = new URL('./public/', document.baseURI).href;
