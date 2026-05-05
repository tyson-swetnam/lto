"""Nominatim-backed geocoder with a disk cache.

Respects Nominatim usage policy: 1 request/second, descriptive User-Agent,
and local caching so repeat runs do not re-query.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from geopy.geocoders import Nominatim

CACHE_PATH = Path(__file__).resolve().parent.parent / ".geocode_cache.json"


class Geocoder:
    def __init__(self, user_agent: str = "cod-kmap/0.1 (coastal-obs-design knowledge map)"):
        self._nom = Nominatim(user_agent=user_agent, timeout=10)
        self._cache: dict[str, list[float] | None] = {}
        if CACHE_PATH.exists():
            try:
                self._cache = json.loads(CACHE_PATH.read_text())
            except json.JSONDecodeError:
                self._cache = {}
        self._last = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last = time.time()

    def lookup(self, address: str) -> tuple[float, float] | None:
        if not address:
            return None
        key = address.strip()
        if key in self._cache:
            hit = self._cache[key]
            return (hit[0], hit[1]) if hit else None

        self._rate_limit()
        try:
            loc = self._nom.geocode(key)
        except Exception as e:
            print(f"[geocode] error for {key!r}: {e}")
            return None

        value = [loc.latitude, loc.longitude] if loc else None
        self._cache[key] = value
        CACHE_PATH.write_text(json.dumps(self._cache, indent=2))
        return (value[0], value[1]) if value else None
