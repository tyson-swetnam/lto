#!/usr/bin/env python3
"""Shared OpenAlex authentication for every script that calls the API.

This project authenticates to OpenAlex with an API key rather than with
the older "polite pool" convention of passing ``mailto=`` in the query
string or User-Agent. Six scripts in this repo each built their own
``requests.Session`` with the mailto convention baked in, so the key
handling lives here rather than being copied six times.

Verified against the live API on 2026-07-26: a request carrying
``api_key`` returns 200, and the key is attached to api.openalex.org
only. Whether an unauthenticated request still succeeds was not tested
and is not relied on — the key is used because it is the credential
this project is configured with, and rate limits for keyed clients are
the ones OpenAlex documents.

Usage::

    from openalex_auth import openalex_session

    sess = openalex_session()              # OpenAlex-only client
    sess = openalex_session(mixed=True)    # also used for pub.orcid.org

``OpenAlexSession`` injects ``api_key`` on requests to
``api.openalex.org`` and on no other host, so a session shared with
ORCID (``scripts/enrich_people_gscholar.py``) never leaks the key. It
also strips ``mailto`` from OpenAlex query strings: the key identifies
the client, so the address adds nothing, and not sending a contact
address to a third-party API by default is the safer posture.

Environment:
    OPENALEX_API_KEY   required for any OpenAlex call
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

import requests

OPENALEX_HOST = "api.openalex.org"

# No mailto: OpenAlex is keyed now, and the key is the identity.
DEFAULT_UA = "lto/0.2 (+https://github.com/tyson-swetnam/lto)"


def api_key() -> str:
    """Return the configured OpenAlex API key, or "" if unset."""
    return (os.environ.get("OPENALEX_API_KEY") or "").strip()


def require_api_key() -> str:
    """Return the key, or exit with an actionable message.

    Scripts that cannot do anything useful without OpenAlex call this at
    startup, so a missing key is one clear line at the top rather than a
    surprise partway through a several-thousand-request harvest.
    """
    key = api_key()
    if not key:
        print(
            "[error] OPENALEX_API_KEY is not set. This project calls "
            "OpenAlex with an API key; set one before running. Keys are "
            "free at https://openalex.org/.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return key


class OpenAlexSession(requests.Session):
    """A Session that authenticates api.openalex.org requests.

    Other hosts pass through untouched, which is what lets one session
    serve both OpenAlex and ORCID.
    """

    def request(self, method, url, *args, **kwargs):  # noqa: D102
        if urlparse(str(url)).hostname == OPENALEX_HOST:
            params = kwargs.get("params")
            if params is None:
                params = {}
            elif isinstance(params, dict):
                params = dict(params)
            else:  # list of pairs / str — normalise to a dict of pairs
                params = dict(params)
            params.pop("mailto", None)
            key = api_key()
            if key:
                params["api_key"] = key
            kwargs["params"] = params
        return super().request(method, url, *args, **kwargs)


def openalex_session(user_agent: str | None = None,
                     accept_json: bool = True) -> OpenAlexSession:
    """Build a session that keys OpenAlex requests and leaves others alone."""
    s = OpenAlexSession()
    s.headers["User-Agent"] = user_agent or DEFAULT_UA
    if accept_json:
        s.headers["Accept"] = "application/json"
    return s
