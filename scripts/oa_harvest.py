
"""OpenAlex LTO-works harvest + co-author pair extraction.

Shared by the harvest runner (scripts/harvest_runner.py). Cursor-pages works
for a set of authors restricted to the curated LTO topic set, writes works and
co-author pairs to parquet incrementally so an interrupted run resumes instead
of restarting.
"""
import csv
import json, sys, time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openalex_auth

OA = "https://api.openalex.org/"
UA = "lto/0.2 (+https://github.com/tyson-swetnam/lto)"

ROOT = Path(__file__).resolve().parents[1]
# The curated LTO topic set the harvest is restricted to (topic_id,label,notes).
TOPICS_CSV = ROOT / "schema" / "vocab" / "lto_openalex_topics.csv"

_session = None


def _sess():
    """Lazily build the shared keyed session.

    Lazy so importing this module never exits on a missing key -- only
    actually calling the API does. Auth lives in openalex_auth: the session
    injects api_key on api.openalex.org and never sends mailto.
    """
    global _session
    if _session is None:
        openalex_auth.require_api_key()
        _session = openalex_auth.openalex_session(user_agent=UA)
    return _session


def load_topic_ids(path=TOPICS_CSV):
    """Load the curated LTO topic ids from schema/vocab/lto_openalex_topics.csv.

    Fails loudly when the file is missing or empty: a harvest with no topic
    restriction would pull every work by every author and burn the 10k/day
    request quota on off-topic output.
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError(
            f"LTO topic vocabulary not found: {p}. The harvest is scoped to "
            "the curated topic set; create schema/vocab/lto_openalex_topics.csv "
            "(columns: topic_id,label,notes) before running.")
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [short_id((r.get("topic_id") or "").strip())
           for r in rows if (r.get("topic_id") or "").strip()]
    if not ids:
        raise RuntimeError(
            f"LTO topic vocabulary is empty: {p}. Refusing to run an "
            "unrestricted works harvest; add topic_id rows first.")
    return ids


def oa_get(path, retries=5, **params):
    """One OpenAlex GET with backoff on 429/5xx. Never sends mailto.

    The key is attached by the shared session (scripts/openalex_auth.py),
    which scopes it to api.openalex.org and strips any mailto param.
    """
    url = OA + path
    delay = 1.0
    for attempt in range(retries):
        try:
            r = _sess().get(url, params=params, timeout=90)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay); delay *= 2; continue
            r.raise_for_status()
            return r.json()
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
                json.JSONDecodeError):
            # A truncated body on an otherwise-200 response -- observed once
            # mid-harvest on upstream cod-kmap ("857785 bytes read, 93039 more
            # expected"), which killed a run that had spent real quota. It is
            # transient and retryable; JSONDecodeError is the same failure when
            # the truncation lands mid-token.
            if attempt < retries - 1:
                time.sleep(delay); delay *= 2; continue
            raise
    raise RuntimeError("unreachable")


def short_id(v):
    """'https://openalex.org/A123' -> 'A123'; passes bare ids through."""
    if v is None:
        return None
    return str(v).rsplit("/", 1)[-1]


def bare_orcid(v):
    """ORCID URL or bare -> bare 0000-0000-0000-0000, else None."""
    if not v:
        return None
    s = str(v).rsplit("/", 1)[-1].strip()
    return s or None


def harvest_author_works(author_id, topic_ids, per_page=200, max_pages=200):
    """Cursor-page one author's works restricted to topic_ids.
    Yields work dicts. topic_ids empty/None means no topic restriction."""
    filt = f"author.id:{short_id(author_id)}"
    if topic_ids:
        filt += ",topics.id:" + "|".join(short_id(t) for t in topic_ids)
    cursor = "*"
    for _ in range(max_pages):
        d = oa_get("works", filter=filt,
                   select="id,doi,publication_year,title,cited_by_count,authorships",
                   cursor=cursor, **{"per-page": str(per_page)})
        results = d.get("results") or []
        for w in results:
            yield w
        cursor = (d.get("meta") or {}).get("next_cursor")
        if not cursor or not results:
            return


def coauthor_pairs(work, focal_author_id):
    """One row per co-author on `work`, excluding the focal author.
    Returns (work_row, [pair_rows]). Provenance: every pair carries work_id."""
    wid = short_id(work.get("id"))
    year = work.get("publication_year")
    focal = short_id(focal_author_id)
    authorships = work.get("authorships") or []
    work_row = dict(work_id=wid, doi=work.get("doi"),
                    publication_year=year, title=(work.get("title") or "")[:500],
                    cited_by_count=work.get("cited_by_count"),
                    n_authors=len(authorships))
    pairs = []
    for a in authorships:
        au = a.get("author") or {}
        aid = short_id(au.get("id"))
        if not aid or aid == focal:
            continue
        rors = [i.get("ror") for i in (a.get("institutions") or []) if i.get("ror")]
        pairs.append(dict(
            focal_openalex_id=focal, coauthor_openalex_id=aid,
            coauthor_display_name=au.get("display_name"),
            coauthor_orcid=bare_orcid(au.get("orcid")),
            coauthor_ror=short_id(rors[0]) if rors else None,
            work_id=wid, publication_year=year,
            author_position=a.get("author_position")))
    return work_row, pairs
