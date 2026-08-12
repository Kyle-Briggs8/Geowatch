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

# Country → capital, for anchoring country-level mentions somewhere meaningful
# (a static table beats an external API here: no churn, no network, no quota)
_CAPITALS = {
    "ukraine": "Kyiv", "russia": "Moscow", "belarus": "Minsk",
    "germany": "Berlin", "france": "Paris", "poland": "Warsaw",
    "uk": "London", "united kingdom": "London", "britain": "London",
    "great britain": "London", "england": "London",
    "usa": "Washington, D.C.", "united states": "Washington, D.C.",
    "us": "Washington, D.C.", "america": "Washington, D.C.",
    "china": "Beijing", "taiwan": "Taipei", "japan": "Tokyo",
    "north korea": "Pyongyang", "south korea": "Seoul",
    "iran": "Tehran", "israel": "Jerusalem", "syria": "Damascus",
    "lebanon": "Beirut", "iraq": "Baghdad", "turkey": "Ankara",
    "saudi arabia": "Riyadh", "yemen": "Sanaa", "oman": "Muscat",
    "qatar": "Doha", "kuwait": "Kuwait City", "jordan": "Amman",
    "united arab emirates": "Abu Dhabi", "uae": "Abu Dhabi",
    "egypt": "Cairo", "libya": "Tripoli", "sudan": "Khartoum",
    "ethiopia": "Addis Ababa", "somalia": "Mogadishu", "kenya": "Nairobi",
    "nigeria": "Abuja", "india": "New Delhi", "pakistan": "Islamabad",
    "afghanistan": "Kabul", "myanmar": "Naypyidaw",
    "moldova": "Chisinau", "romania": "Bucharest", "hungary": "Budapest",
    "slovakia": "Bratislava", "bulgaria": "Sofia", "serbia": "Belgrade",
    "azerbaijan": "Baku", "armenia": "Yerevan", "georgia": "Tbilisi",
    "kazakhstan": "Astana", "italy": "Rome", "spain": "Madrid",
    "netherlands": "Amsterdam", "belgium": "Brussels", "sweden": "Stockholm",
    "norway": "Oslo", "finland": "Helsinki", "denmark": "Copenhagen",
    "czech republic": "Prague", "czechia": "Prague", "austria": "Vienna",
    "switzerland": "Bern", "greece": "Athens", "lithuania": "Vilnius",
    "latvia": "Riga", "estonia": "Tallinn", "canada": "Ottawa",
    "mexico": "Mexico City", "brazil": "Brasilia", "australia": "Canberra",
    "venezuela": "Caracas", "colombia": "Bogota",
}
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


# Nominatim addresstypes that are broader than a point location
_REGION_TYPES = {"state", "region", "province", "county", "sea", "ocean", "bay", "state_district"}


def _precision(addresstype: str) -> str:
    """Map a Nominatim addresstype to a GeoWatch precision label."""
    if addresstype == "country":
        return "country"
    if addresstype in _REGION_TYPES:
        return "region"
    return "point"


def _query(q: str) -> tuple[bool, dict | None]:
    """One Nominatim lookup. Returns (ok, hit) — ok=False means a network
    error (retryable), while (True, None) means a definitive 'not found'.
    A hit is {"coords": [lat, lon], "precision": "point"|"region"|"country"}."""
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
                r = results[0]
                return True, {
                    "coords": [float(r["lat"]), float(r["lon"])],
                    "precision": _precision(r.get("addresstype") or r.get("type") or ""),
                }
            return True, None
        except Exception as exc:  # broad: geocoding is best-effort, never fatal
            print(f"  [WARN] Geocode failed for '{q}': {exc}", file=sys.stderr)
            return False, None


def _anchor_country_at_capital(country: str, hit: dict) -> dict:
    """For a country-level geocode, move the anchor point to the capital city.

    A geometric centroid can be visually absurd (Russia's is in central
    Siberia); the capital is where country-level news usually concerns.
    Precision stays 'country' — the anchor is presentational, not a claim.
    """
    capital = _CAPITALS.get(country.strip().lower())
    if not capital:
        return hit
    ok, cap_hit = _query(f"{capital}, {country}")
    if ok and cap_hit:
        return {"coords": cap_hit["coords"], "precision": "country"}
    return hit


def geocode_place(place: str, region: str | None = None) -> dict | None:
    """Geocode a place name, optionally with a region fallback.

    Returns {"coords": [lat, lon], "precision": "point"|"region"|"country"}
    or None. The bare place name goes first — Nominatim's importance ranking
    correctly resolves prominent names (Krakow → Poland, Baku → Azerbaijan)
    whereas a "<place>, <region>" hint fuzzy-matches foreign names to spurious
    in-region locations. The hinted form is only a fallback for obscure local
    places the bare query can't find. Results — including misses — are cached
    persistently; legacy list-valued cache entries are upgraded on read.
    """
    if not place or not place.strip():
        return None
    cache = _load_cache()
    key = f"{place.strip().lower()}|{(region or '').strip().lower()}"
    if key in cache:
        hit = cache[key]
        if isinstance(hit, list):  # legacy format: bare coords
            hit = {"coords": hit, "precision": "point"}
        return hit or None

    queries = [place]
    if region and region.strip().lower() not in place.lower():
        queries.append(f"{place}, {region}")

    hit = None
    definitive = True
    for q in queries:
        ok, hit = _query(q)
        if not ok:
            ok, hit = _query(q)  # one retry on network trouble
        if not ok:
            # network failure: don't degrade to the weaker hinted query,
            # and don't cache — a later run should try again
            definitive = False
            break
        if hit:
            break

    if hit and hit["precision"] == "country":
        hit = _anchor_country_at_capital(place, hit)

    if definitive or hit:
        cache[key] = hit
        _save_cache()
    return hit


def get_bbox(place: str) -> tuple[float, float, float, float] | None:
    """Return the (west, south, east, north) bounding box for a place, cached.

    Used to scope the FIRMS thermal query to the AOI. Nominatim returns
    boundingbox as [south, north, west, east] strings.
    """
    if not place or not place.strip():
        return None
    cache = _load_cache()
    key = f"__bbox__|{place.strip().lower()}"
    if key in cache:
        hit = cache[key]
        return tuple(hit) if hit else None

    with _lock:
        _throttle()
        try:
            resp = requests.get(
                _NOMINATIM_URL,
                params={"q": place, "format": "json", "limit": 1},
                headers={"User-Agent": _USER_AGENT},
                timeout=20,
            )
            resp.raise_for_status()
            results = resp.json()
        except Exception as exc:  # broad: best-effort, never fatal, don't cache failures
            print(f"  [WARN] Bounding-box lookup failed for '{place}': {exc}", file=sys.stderr)
            return None

    bbox = None
    if results and results[0].get("boundingbox"):
        s, n, w, e = (float(v) for v in results[0]["boundingbox"])
        bbox = [w, s, e, n]
    cache[key] = bbox
    _save_cache()
    return tuple(bbox) if bbox else None


def geocode_events(events: list[dict], region: str) -> int:
    """Attach coords + loc_precision to analyzed events. Mutates.

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
            ev["loc_precision"] = None
            continue
        hit = geocode_place(place, region)
        ev["coords"] = hit["coords"] if hit else None
        ev["loc_precision"] = hit["precision"] if hit else None
        if hit:
            placed += 1
    return placed
