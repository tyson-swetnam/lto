// docs.js — Docs view: tabbed reader for the repo's human-authored
// markdown under /docs/, with a per-doc auto-generated table of
// contents in the right rail.
//
// NOTE on path resolution
// -----------------------
// docs are fetched from a DIFFERENT base than the rest of the app's
// data. config.js's DATA_BASE points at /<repo>/public/ (where parquet
// + json data live), but the human-authored markdown lives in
// /<repo>/docs/ at the repo root. Using DATA_BASE here produced a 404
// on "public/docs/cod_purpose_and_msi_handout.md" — that path doesn't
// exist on GitHub Pages. Resolving relative to document.baseURI (the
// directory of index.html, which IS the repo root on GitHub Pages)
// fixes it. The deploy workflow (.github/workflows/deploy.yml) stages
// /docs/ alongside /public/ so these paths resolve to
// /<repo>/docs/<file>.md on the live site.
//
// Routing
// -------
// Top-level route '/docs' renders the first tab. Sub-routes like
// '/docs/methods' switch to the matching slug. Slugs are derived from
// the filename (stem, lower-cased, dashes for underscores) so links
// stay stable: e.g. 'docs/cod_purpose_and_msi_handout.md' →
// '#/docs/cod-purpose-and-msi-handout'.

const BASE = new URL('./', document.baseURI).href;

// One entry per markdown file under /docs/. Order = tab order in the
// UI. The first entry is the default tab when no slug is in the URL.
const DOC_PAGES = [
  { title: 'Purpose & MSI Handout',     path: 'docs/cod_purpose_and_msi_handout.md' },
  { title: 'Methods',                   path: 'docs/METHODS.md' },
  { title: 'References',                path: 'docs/REFERENCES.md' },
  { title: 'Reference Documents Report',path: 'docs/reference_documents_report.md' },
  { title: 'Map Visualization Plan',    path: 'docs/map_visualization_plan.md' },
  { title: 'Funding Pipeline Plan',     path: 'docs/funding_pipeline_plan.md' },
  { title: 'Suitability Roadmap',       path: 'docs/suitability_roadmap.md' },
  { title: 'Personnel Gap Research',    path: 'docs/personnel_gap_research_plan.md' },
  { title: 'ORCID Enrichment',          path: 'docs/orcid_enrichment_plan.md' },
  { title: 'Google Scholar Enrichment', path: 'docs/google_scholar_enrichment_plan.md' },
];

// Compute slug once per page. Filename stem with underscores → dashes,
// lower-cased; e.g. 'docs/orcid_enrichment_plan.md' → 'orcid-enrichment-plan'.
DOC_PAGES.forEach((p) => {
  p.slug = p.path.replace(/^docs\//, '').replace(/\.md$/, '')
            .toLowerCase().replace(/_/g, '-');
});

let _container = null;
const _docCache = new Map();   // slug → { html, toc }
let _activeSlug = null;


// ── Markdown → HTML (with id-anchored headings for TOC links) ───────
function escHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function inlinesMd(s) {
  return escHtml(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function slugify(text) {
  return String(text || '')
    .replace(/<[^>]+>/g, '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'h';
}

function parseCells(line) {
  return line.replace(/^\||\|$/g, '').split('|').map((s) => s.trim());
}

function renderTable(lines) {
  const rows = lines.filter((l) => !/^\|[-| ]+\|/.test(l));
  if (!rows.length) return '';
  const [head, ...body] = rows;
  const thCells = parseCells(head).map((c) => `<th>${inlinesMd(c)}</th>`).join('');
  const tbRows = body.map((r) => {
    const tds = parseCells(r).map((c) => `<td>${inlinesMd(c)}</td>`).join('');
    return `<tr>${tds}</tr>`;
  }).join('');
  return `<table class="md-table"><thead><tr>${thCells}</tr></thead><tbody>${tbRows}</tbody></table>`;
}

// Render markdown → { html, toc }. The TOC is a list of
// { level, text, id } extracted from h1/h2/h3 headings; each heading
// in the rendered HTML carries the matching `id` attribute so TOC
// links work as in-page anchors.
function mdToHtml(md) {
  const lines = md.split('\n');
  const out = [];
  const toc = [];
  const seenIds = new Set();
  let inCode = false, codeLines = [];           // ```fenced``` code
  let inIndentCode = false, indentLines = [];   // 4-space-indented code
  let inTable = false, tableLines = [];
  let inBQ = false, bqLines = [];
  let inHtml = false, htmlLines = [];

  // Stack of `<ul>`/`<ol>` indents currently open.
  // Each entry = { indent: number-of-leading-spaces, kind: 'ul'|'ol' }
  const listStack = [];
  const closeListsTo = (targetIndent) => {
    while (listStack.length && listStack[listStack.length - 1].indent >= targetIndent) {
      out.push(`</${listStack.pop().kind}>`);
    }
  };
  const closeAllLists = () => closeListsTo(-1);

  const flushTable = () => {
    if (inTable) { out.push(renderTable(tableLines)); tableLines = []; inTable = false; }
  };
  const flushIndentCode = () => {
    if (inIndentCode) {
      // Strip the 4-space indent before emitting.
      out.push('<pre><code>' + indentLines.map((l) => escHtml(l.replace(/^ {4}/, ''))).join('\n') + '</code></pre>');
      indentLines = [];
      inIndentCode = false;
    }
  };
  const flushBQ = () => {
    if (inBQ) {
      out.push('<blockquote>' + bqLines.map((l) => `<p>${inlinesMd(l)}</p>`).join('') + '</blockquote>');
      bqLines = [];
      inBQ = false;
    }
  };
  const flushHtml = () => {
    if (inHtml) { out.push(htmlLines.join('\n')); htmlLines = []; inHtml = false; }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Fenced code block — highest precedence.
    if (line.startsWith('```')) {
      if (inCode) {
        out.push('<pre><code>' + codeLines.map(escHtml).join('\n') + '</code></pre>');
        codeLines = [];
        inCode = false;
      } else {
        closeAllLists(); flushTable(); flushIndentCode(); flushBQ(); flushHtml();
        inCode = true;
      }
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }

    // Pass-through HTML block (line begins with `<` and looks like a tag).
    // Flushed as-is so authors can drop in <iframe>, <details>, <img>, etc.
    if (/^<[a-zA-Z!][^>]*>?/.test(line.trim()) && !inIndentCode) {
      if (!inHtml) {
        closeAllLists(); flushTable(); flushIndentCode(); flushBQ();
        inHtml = true;
      }
      htmlLines.push(line);
      continue;
    }
    if (inHtml && line.trim() === '') { flushHtml(); continue; }
    if (inHtml) { htmlLines.push(line); continue; }

    // Pipe-table.
    if (line.startsWith('|')) {
      closeAllLists(); flushIndentCode(); flushBQ();
      tableLines.push(line);
      inTable = true;
      continue;
    }
    if (inTable) flushTable();

    // Headings (always close pending blocks first).
    const hMatch = line.match(/^(#{1,6})\s+(.*)/);
    if (hMatch) {
      closeAllLists(); flushIndentCode(); flushBQ();
      const level = hMatch[1].length;
      const rawText = hMatch[2];
      let id = slugify(rawText);
      let n = 2;
      const baseId = id;
      while (seenIds.has(id)) id = `${baseId}-${n++}`;
      seenIds.add(id);
      if (level <= 3) toc.push({ level, text: rawText.replace(/[`*_]/g, ''), id });
      out.push(`<h${level} id="${escHtml(id)}">${inlinesMd(rawText)}</h${level}>`);
      continue;
    }

    // Horizontal rule.
    if (/^---+$/.test(line.trim())) {
      closeAllLists(); flushIndentCode(); flushBQ();
      out.push('<hr>');
      continue;
    }

    // Blockquote.
    const bqMatch = line.match(/^>\s?(.*)/);
    if (bqMatch) {
      closeAllLists(); flushIndentCode();
      if (!inBQ) inBQ = true;
      bqLines.push(bqMatch[1]);
      continue;
    }
    if (inBQ) flushBQ();

    // List item: bullet (- *) or numbered (1. ). Indent (every 2 spaces) is
    // a nesting level. We open / close <ul>/<ol> as the indent depth changes.
    const listMatch = line.match(/^(\s*)([-*]|\d+\.)\s+(.*)/);
    if (listMatch) {
      flushIndentCode(); flushBQ();
      const indent = listMatch[1].length;
      const marker = listMatch[2];
      const text = listMatch[3];
      const kind = /\d+\./.test(marker) ? 'ol' : 'ul';

      // Close deeper lists.
      closeListsTo(indent + 1);
      // Open a new list if the current top is shallower or different kind.
      if (!listStack.length
          || listStack[listStack.length - 1].indent < indent
          || listStack[listStack.length - 1].kind !== kind) {
        listStack.push({ indent, kind });
        out.push(`<${kind}>`);
      }
      out.push(`<li>${inlinesMd(text)}</li>`);
      continue;
    }
    // A list-item continuation line (extra-indented prose under a bullet)
    // — append it to the previous <li> as a soft break so the bullet keeps
    // its full text. Only triggers while we're inside a list.
    if (listStack.length && /^\s{2,}\S/.test(line)) {
      const last = out.length - 1;
      if (last >= 0 && out[last].endsWith('</li>')) {
        out[last] = out[last].replace(/<\/li>$/, ' ' + inlinesMd(line.trim()) + '</li>');
        continue;
      }
    }
    if (line.trim() !== '' && listStack.length) closeAllLists();

    // Indented (4-space) code block — but only when we're NOT in a list.
    if (/^ {4}\S/.test(line) && !listStack.length) {
      flushTable();
      if (!inIndentCode) inIndentCode = true;
      indentLines.push(line);
      continue;
    }
    if (inIndentCode && line.trim() === '') {
      // Blank line inside an indented code block — keep it.
      indentLines.push(line);
      continue;
    }
    if (inIndentCode) flushIndentCode();

    // Blank line: paragraph break.
    if (line.trim() === '') {
      closeAllLists();
      out.push('');
      continue;
    }

    // Paragraph (default).
    out.push(`<p>${inlinesMd(line)}</p>`);
  }

  // Final flush of any open block.
  if (inTable) flushTable();
  flushIndentCode();
  flushBQ();
  flushHtml();
  closeAllLists();
  if (inCode) out.push('<pre><code>' + codeLines.map(escHtml).join('\n') + '</code></pre>');

  return { html: out.join('\n'), toc };
}


// ── Fetch + cache markdown for a single page ───────────────────────
async function loadDoc(page) {
  if (_docCache.has(page.slug)) return _docCache.get(page.slug);
  try {
    const r = await fetch(`${BASE}${page.path}`);
    if (!r.ok) {
      const err = `<p class="docs-error">Failed to load ${escHtml(page.path)}: HTTP ${r.status}</p>`;
      const cached = { html: err, toc: [] };
      _docCache.set(page.slug, cached);
      return cached;
    }
    const md = await r.text();
    const cached = mdToHtml(md);
    _docCache.set(page.slug, cached);
    return cached;
  } catch (e) {
    const err = `<p class="docs-error">Failed to load ${escHtml(page.path)}: ${escHtml(e.message)}</p>`;
    const cached = { html: err, toc: [] };
    _docCache.set(page.slug, cached);
    return cached;
  }
}


// ── Render: tab bar, active doc, TOC sidebar ───────────────────────
function tabBarHtml(activeSlug) {
  return `<nav class="docs-tabs" role="tablist">${
    DOC_PAGES.map((p) => {
      const active = (p.slug === activeSlug);
      return `<a href="#/docs/${p.slug}" class="docs-tab${active ? ' active' : ''}"
                 role="tab" aria-selected="${active}"
                 data-doc-slug="${p.slug}">${escHtml(p.title)}</a>`;
    }).join('')
  }</nav>`;
}

function tocHtml(toc) {
  if (!toc.length) {
    return '<aside class="docs-toc"><h4>On this page</h4>'
         + '<p class="docs-toc-empty">No headings yet.</p></aside>';
  }
  const items = toc.map((h) =>
    `<li class="docs-toc-l${h.level}"><a href="#${escHtml(h.id)}">${escHtml(h.text)}</a></li>`
  ).join('');
  return `<aside class="docs-toc">
            <h4>On this page</h4>
            <ul>${items}</ul>
          </aside>`;
}

function pageShellHtml(activeSlug) {
  return `
    ${tabBarHtml(activeSlug)}
    <div class="docs-layout">
      <article class="docs-body" id="docs-article">
        <p class="docs-loading" style="color:var(--c-muted)">Loading documentation…</p>
      </article>
      <aside class="docs-toc-wrap" id="docs-toc-wrap">
        <aside class="docs-toc"><h4>On this page</h4>
          <p class="docs-toc-empty">Loading…</p>
        </aside>
      </aside>
    </div>`;
}

async function renderActive(slug) {
  if (!_container) return;
  const page = DOC_PAGES.find((p) => p.slug === slug) || DOC_PAGES[0];
  _activeSlug = page.slug;

  // Update tab bar active state without a full re-render of the shell.
  _container.querySelectorAll('.docs-tab').forEach((a) => {
    const isActive = a.dataset.docSlug === page.slug;
    a.classList.toggle('active', isActive);
    a.setAttribute('aria-selected', String(isActive));
  });

  const article = _container.querySelector('#docs-article');
  const tocWrap = _container.querySelector('#docs-toc-wrap');
  if (!article || !tocWrap) return;
  article.innerHTML = `<p class="docs-loading" style="color:var(--c-muted)">Loading ${escHtml(page.title)}…</p>`;

  const { html, toc } = await loadDoc(page);
  // Bail if the user already switched tabs while we were fetching.
  if (_activeSlug !== page.slug) return;

  article.innerHTML = `
    <header class="docs-page-head">
      <h1>${escHtml(page.title)}</h1>
      <p class="docs-page-source">
        Source: <code>${escHtml(page.path)}</code>
        · <a href="${BASE}${page.path}" target="_blank" rel="noopener">view raw</a>
      </p>
    </header>
    ${html}`;
  tocWrap.innerHTML = tocHtml(toc);

  // Scroll to top of the article when switching tabs (anchored TOC
  // clicks within a page navigate normally and we DON'T re-scroll).
  article.scrollTop = 0;
  const root = _container.querySelector('.docs-layout');
  if (root) root.scrollTop = 0;
}


// ── Public API ─────────────────────────────────────────────────────
//
// initDocsView(container) is called once when the user first navigates
// to '#/docs'. renderDocsView(path) is called by main.js on every
// route change so we can pick up '/docs/<slug>' deep-links.

export function initDocsView(container) {
  _container = container;
  if (!_container.dataset.docsReady) {
    // Build the persistent shell only once. Tab clicks update the URL
    // hash; the router calls renderDocsView() to swap content.
    _container.innerHTML = pageShellHtml(_activeSlug || DOC_PAGES[0].slug);
    _container.dataset.docsReady = '1';
  }
  // Pull initial slug from the URL.
  const slug = (location.hash.match(/^#\/docs\/(.+)$/) || [])[1];
  const page = DOC_PAGES.find((p) => p.slug === slug) || DOC_PAGES[0];
  renderActive(page.slug);
}

export function renderDocsView(path) {
  if (!_container) return;
  // Ensure the shell exists even if main.js routed straight to a
  // sub-path on first visit.
  if (!_container.dataset.docsReady) {
    _container.innerHTML = pageShellHtml((path || '').split('/')[2] || DOC_PAGES[0].slug);
    _container.dataset.docsReady = '1';
  }
  const slug = (path || '').split('/')[2] || DOC_PAGES[0].slug;
  if (slug !== _activeSlug) renderActive(slug);
}
