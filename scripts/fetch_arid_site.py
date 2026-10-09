#!/usr/bin/env python3
"""Scrape the structured pages of arid.unm.edu into data/raw/R-ARID/.

ARID (Accelerating Resilience Innovations in Drylands) is the UNM
institute this catalogue's New Mexico layer is organised around. Its
site is small and hand-edited, so this reads only the parts with a
regular shape and leaves everything else to the curated seeds:

  scraped here                       curated in data/seed/
  ---------------------------------  ----------------------------------
  leadership-team cards (26)         arid_people.csv    identity, aliases
  contact-page staff (4)             arid_projects.csv  the projects
  FOR-NM leadership panels (15)      arid_partner_centers.csv  facilities
  CHANGES leaders / co-leaders
  CHANGES engagement-core team
  "PIs:" line of each project page
  "Resources at UNM" link list

Output is one file, data/raw/R-ARID/arid_site.json, holding what each
page says *as written* — typos included ("Kim Eichorst", "Eva
Sticker"). Reconciling those to one person is scripts/load_arid.py's
job, through the alias column of arid_people.csv; a name the seed does
not know makes the loader fail, which is how a new face on the site
gets noticed.

Email addresses are on the source pages but are deliberately not
written out: the catalogue does not need them and republishing them
only widens their exposure.

Run from the repo root::

    python scripts/fetch_arid_site.py            # fetch (1 req/s) and parse
    python scripts/fetch_arid_site.py --offline  # re-parse the cached HTML

Fetched HTML is cached under data/raw/R-ARID/_state/html/ (gitignored).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "raw" / "R-ARID"
CACHE = OUT_DIR / "_state" / "html"
OUT = OUT_DIR / "arid_site.json"

BASE = "https://arid.unm.edu/"
USER_AGENT = "lto-catalogue/0.2 (+https://github.com/tyson-swetnam/lto)"

LEADERSHIP = "leadership-team.html"
CONTACT = "contact.html"
HUB = "contact1.html"
FOR_NM = "projects/for-nm.html"
CHANGES = "projects/changes/index.html"
CEC_TEAM = "projects/changes/community-engagement-core/team.html"

# Pages whose only people statement is a single "PI:" / "PIs:" line.
PI_LINE_PAGES = [
    "projects/decentralized-water-and-wastewater-systems-in-rural-areas.html",
    "projects/the-intermountain-west-transformation-network.html",
    "projects/public-perceptions-of-potable-water-reuse.html",
    "projects/sevilleta-long-term-ecological-research-program.html",
]
PAGES = [LEADERSHIP, CONTACT, HUB, FOR_NM, CHANGES, CEC_TEAM, *PI_LINE_PAGES]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DEGREE_RE = re.compile(r",?\s*\b(?:Ph\.?\s?D\.?|P\.?E\.?|M\.?D\.?)\s*$", re.I)


def cache_path(page: str) -> Path:
    return CACHE / page.replace("/", "_")


def get(page: str, offline: bool) -> BeautifulSoup:
    f = cache_path(page)
    if not offline:
        r = requests.get(urljoin(BASE, page), headers={"User-Agent": USER_AGENT}, timeout=40)
        r.raise_for_status()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(r.text)
        time.sleep(1.0)
    elif not f.exists():
        raise SystemExit(f"[error] --offline but no cached copy of {page}")
    soup = BeautifulSoup(f.read_text(), "html.parser")
    primary = soup.select_one("#primary")
    if primary is None:
        raise SystemExit(f"[error] {page}: no #primary block — the site layout changed")
    return primary


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def clean_name(s: str) -> str:
    """Name as written, minus degree suffixes and stray whitespace."""
    s = squash(s)
    prev = None
    while prev != s:
        prev, s = s, DEGREE_RE.sub("", s).strip(" ,")
    return s


def unwrap(href: str | None) -> str | None:
    """Undo Outlook safelinks wrappers pasted into the page."""
    if not href:
        return None
    href = href.strip()
    if "safelinks.protection.outlook.com" in href:
        inner = parse_qs(urlparse(href).query).get("url")
        if inner:
            return inner[0]
    return href


def parse_leadership(primary) -> list[dict]:
    out = []
    for card in primary.select("div.row > div[class*=col-]"):
        bio = card.select_one("p.bio-txt")
        if bio is None or bio.find("strong") is None:
            continue
        name = clean_name(bio.find("strong").get_text(" "))
        img = card.find("img")
        link = card.select_one("p.bio-txt a[href]")
        # Title = the bio paragraph with the name and the link label removed.
        title_el = BeautifulSoup(str(bio), "html.parser")
        title_el.find("strong").decompose()
        for a in title_el.find_all("a"):
            a.decompose()
        title = squash(title_el.get_text(" "))
        out.append({
            "name_as_written": name,
            "title": title,
            "url": unwrap(link["href"]) if link else None,
            "photo_url": urljoin(BASE, img["src"]) if img and img.get("src") else None,
        })
    return out


def parse_contact(primary) -> list[dict]:
    out = []
    for p in primary.find_all("p"):
        strong = p.find("strong")
        if strong is None:
            continue
        lines = [squash(x) for x in p.get_text("\n").split("\n")]
        lines = [x for x in lines if x and not EMAIL_RE.fullmatch(x)]
        name = clean_name(strong.get_text(" "))
        if not name or name not in lines:
            continue
        rest = lines[lines.index(name) + 1:]
        out.append({
            "name_as_written": name,
            "title": rest[0] if rest else None,
            "organisation": rest[1] if len(rest) > 1 else None,
        })
    return out


def parse_for_nm(primary) -> list[dict]:
    out = []
    for panel in primary.select("div.panel"):
        head = panel.select_one(".panel-heading")
        if head is None:
            continue
        name, _, affil = squash(head.get_text(" ")).partition(",")
        bodies = panel.select(".panel-body")
        role = squash(EMAIL_RE.sub("", bodies[0].get_text(" "))).strip(" ,") if bodies else ""
        url = None
        for a in panel.find_all("a", href=True):
            if not a["href"].startswith("mailto:"):
                url = unwrap(a["href"])
        out.append({
            "name_as_written": clean_name(name),
            "affiliation": squash(affil),
            "role_text": role,
            "url": url,
        })
    return out


def split_people(text: str) -> list[str]:
    """'A, Ph.D., B, Ph.D.' or 'A and B' → ['A', 'B']."""
    text = re.sub(r"\b(?:Ph\.?\s?D\.?)", "", text)
    parts = re.split(r",|\band\b|;", text)
    return [n for n in (clean_name(p) for p in parts) if n]


def parse_changes(primary) -> list[dict]:
    """Sub-projects are <h4> headings; leader lines follow in <p><strong>."""
    out, current = [], None
    for el in primary.find_all(["h4", "p"]):
        if el.name == "h4":
            title = squash(el.get_text(" "))
            if title:
                current = {"title": title, "leaders": [], "co_leaders": []}
                out.append(current)
            continue
        strong = el.find("strong")
        if current is None or strong is None:
            continue
        label = squash(strong.get_text(" ")).rstrip(":").lower()
        names = squash(el.get_text(" ").replace(strong.get_text(" "), "", 1))
        if label == "project leaders":
            current["leaders"] = split_people(names)
        elif label == "co-leaders or mentors":
            current["co_leaders"] = split_people(names)
    return out


def parse_cec_team(primary) -> list[dict]:
    out = []
    for h in primary.find_all("h3"):
        text = squash(h.get_text(" "))
        if not text:
            continue
        name, _, role = text.partition("–")
        out.append({"name_as_written": clean_name(name), "role_text": squash(role) or None})
    return out


def parse_pi_line(primary) -> dict:
    title = squash(primary.find("h1").get_text(" "))
    for strong in primary.find_all("strong"):
        text = squash(strong.get_text(" "))
        m = re.match(r"PIs?:\s*(.+)", text)
        if m:
            names = [n for n in split_people(m.group(1))
                     if n.lower() not in {"additional team members"}]
            return {"title": title, "pi_text": text, "pis": names}
    raise SystemExit(f"[error] no 'PIs:' line under '{title}' — the page layout changed")


def parse_hub(primary) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for h in primary.find_all("h3"):
        ul = h.find_next_sibling("ul")
        if ul is None:
            continue
        out[squash(h.get_text(" "))] = [
            {"label": squash(a.get_text(" ")), "url": a["href"].strip()}
            for a in ul.find_all("a", href=True)
        ]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true",
                    help="parse the cached HTML instead of fetching")
    args = ap.parse_args()

    soup = {p: get(p, args.offline) for p in PAGES}
    hub = parse_hub(soup[HUB])

    doc = {
        "source": BASE,
        "retrieved_at": date.today().isoformat(),
        "leadership": {
            "source_url": urljoin(BASE, LEADERSHIP),
            "people": parse_leadership(soup[LEADERSHIP]),
        },
        "staff": {
            "source_url": urljoin(BASE, CONTACT),
            "people": parse_contact(soup[CONTACT]),
        },
        "for_nm": {
            "source_url": urljoin(BASE, FOR_NM),
            "people": parse_for_nm(soup[FOR_NM]),
        },
        "changes": {
            "source_url": urljoin(BASE, CHANGES),
            "sub_projects": parse_changes(soup[CHANGES]),
        },
        "changes_cec_team": {
            "source_url": urljoin(BASE, CEC_TEAM),
            "people": parse_cec_team(soup[CEC_TEAM]),
        },
        "pi_lines": [
            {"source_url": urljoin(BASE, p), **parse_pi_line(soup[p])}
            for p in PI_LINE_PAGES
        ],
        "resources_at_unm": {
            "source_url": urljoin(BASE, HUB),
            "links": hub.get("Resources at UNM", []),
        },
    }

    # Shape checks. These pages are edited by hand; a count that drifts is
    # worth a look, an empty section means the selectors no longer match.
    counts = {
        "leadership": len(doc["leadership"]["people"]),
        "staff": len(doc["staff"]["people"]),
        "for_nm": len(doc["for_nm"]["people"]),
        "changes sub-projects": len(doc["changes"]["sub_projects"]),
        "cec team": len(doc["changes_cec_team"]["people"]),
        "resources at UNM": len(doc["resources_at_unm"]["links"]),
    }
    empty = [k for k, n in counts.items() if n == 0]
    if empty:
        raise SystemExit(f"[error] nothing parsed for: {empty} — the site layout changed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print("[ok] " + ", ".join(f"{k}={n}" for k, n in counts.items()))
    print(f"[ok] wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
