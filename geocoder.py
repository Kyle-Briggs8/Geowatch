"""Per-event geocoding via Nominatim (OpenStreetMap).

The LLM extracts a `location_mentioned` string per article; this module turns
those into coordinates so map markers sit on the actual cities rather than the
region centroid. Free, no API key. Nominatim usage policy requires a real
User-Agent and max 1 request/second — respected here, and a persistent JSON
cache means repeat locations (and repeat runs) cost zero requests.

Coordinates are stored on the event dict itself (`ev["coords"] = [lat, lon]`),
so demo-cache replays never touch the network.
"""

import json
import os
import sys
import threading
import time

import requests

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "GeoWatch/1.0 (open-source geospatial dashboard; github.com/Kyle-Briggs8/Geowatch)"
_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_cache.json")
_RATE_LIMIT_S = 1.1

_cache: dict | None = None
_last_request = 0.0
# Serializes requests across threads (comparison mode geocodes two locations
# in parallel pipelines) so the 1 req/s Nominatim policy holds globally
_lock = threading.Lock()


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(_CACHE_PATH, encoding="utf-8") as f:
                _cache = json.load(f)
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=0)
    except OSError as exc:
        print(f"  [WARN] Could not save geocode cache: {exc}", file=sys.stderr)


def _throttle() -> None:
    """Enforce Nominatim's 1 request/second policy."""
    global _last_request
    wait = _RATE_LIMIT_S - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def _query(q: str) -> tuple[bool, tuple[float, float] | None]:
    """One Nominatim lookup. Returns (ok, coords) — ok=False means a network
    error (retryable), while (True, None) means a definitive 'not found'."""
    with _lock:
        _throttle()
        try:
            resp = requests.get(
                _NOMINATIM_URL,
                params={"q": q, "format": "json", "limit": 1},
                headers={"User-Agent": _USER_AGENT},
                timeout=20,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                return True, (float(results[0]["lat"]), float(results[0]["lon"]))
            return True, None
        except Exception as exc:  # broad: geocoding is best-effort, never fatal
            print(f"  [WARN] Geocode failed for '{q}': {exc}", file=sys.stderr)
            return False, None


def geocode_place(place: str, region: str | None = None) -> tuple[float, float] | None:
    """Geocode a place name, optionally with a region fallback.

    The bare place name goes first — Nominatim's importance ranking correctly
    resolves prominent names (Krakow → Poland, Baku → Azerbaijan) whereas a
    "<place>, <region>" hint fuzzy-matches foreign names to spurious in-region
    locations. The hinted form is only a fallback for obscure local places the
    bare query can't find. Results — including misses — are cached persistently.
    """
    if not place or not place.strip():
        return None
    cache = _load_cache()
    key = f"{place.strip().lower()}|{(region or '').strip().lower()}"
    if key in cache:
        hit = cache[key]
        return tuple(hit) if hit else None

    queries = [place]
    if region and region.strip().lower() not in place.lower():
        queries.append(f"{place}, {region}")

    coords = None
    definitive = True
    for q in queries:
        ok, coords = _query(q)
        if not ok:
            ok, coords = _query(q)  # one retry on network trouble
        if not ok:
            # network failure: don't degrade to the weaker hinted query,
            # and don't cache — a later run should try again
            definitive = False
            break
        if coords:
            break

    if definitive or coords:
        cache[key] = list(coords) if coords else None
        _save_cache()
    return coords


def geocode_events(events: list[dict], region: str) -> int:
    """Attach coords to analyzed events from their location_mentioned. Mutates.

    Returns the number of events that received coordinates. Events without a
    usable location (or failed lookups) get coords=None and fall back to the
    region centroid on the map.
    """
    placed = 0
    for ev in events:
        analysis = ev.get("analysis")
        if not analysis:
            continue
        place = analysis.get("location_mentioned")
        if not place or not isinstance(place, str) or place.strip().lower() in ("null", "none"):
            ev["coords"] = None
            continue
        coords = geocode_place(place, region)
        ev["coords"] = list(coords) if coords else None
        if coords:
            placed += 1
    return placed
