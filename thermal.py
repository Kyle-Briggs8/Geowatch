"""Satellite thermal-anomaly ingestion via NASA FIRMS (VIIRS active fires).

Remote-sensing layer for the dashboard: near-real-time fire/thermal detections
from the VIIRS instrument, queried by bounding box over the reporting window.
Free MAP_KEY from https://firms.modaps.eosdis.nasa.gov/api/map_key/ (rate limit
5000 transactions / 10 min — far above our ~6 requests per run).

High-volume noise (agricultural burning) is filtered to signal: nominal/high
confidence detections above an FRP floor, capped to the strongest N by fire
radiative power. Failure is always non-fatal.
"""

import csv
import io
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

_AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}/{date}"
_SOURCE = "VIIRS_SNPP_NRT"
_WINDOW_DAYS = 5          # API maximum per request
_MIN_FRP = 5.0            # MW — drops most smoldering agricultural burns
_GOOD_CONFIDENCE = {"n", "h", "nominal", "high"}
_MAX_FIRES = 400          # retention budget for the map layer
_FOCUS_RADIUS_KM = 25.0   # detections near focus points are always retained
_GRID = 6                 # stratification grid (per axis) for spatially fair retention
_MINI_BBOX_PAD = 0.4      # degrees around out-of-AOI events for their own queries


def has_firms_key() -> bool:
    """Return True if a FIRMS MAP_KEY is configured."""
    key = os.getenv("FIRMS_MAP_KEY")
    return bool(key) and key != "your_firms_map_key_here"


def _parse_rows(text: str) -> list[dict]:
    """Parse a FIRMS CSV response into normalized detection dicts."""
    fires = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            conf = (row.get("confidence") or "").strip().lower()
            if conf not in _GOOD_CONFIDENCE:
                continue
            frp = float(row.get("frp") or 0)
            if frp < _MIN_FRP:
                continue
            fires.append({
                "lat":        float(row["latitude"]),
                "lon":        float(row["longitude"]),
                "date":       (row.get("acq_date") or "").strip(),
                "time":       (row.get("acq_time") or "").strip(),
                "frp":        frp,
                "confidence": "high" if conf in ("h", "high") else "nominal",
                "daynight":   (row.get("daynight") or "").strip().upper(),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return fires


def _near_any(lat: float, lon: float, points: list) -> bool:
    """True if (lat, lon) is within _FOCUS_RADIUS_KM of any focus point."""
    for plat, plon in points:
        dlat = math.radians(lat - plat)
        dlon = math.radians(lon - plon)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(plat)) * math.cos(math.radians(lat))
             * math.sin(dlon / 2) ** 2)
        if 2 * 6371.0 * math.asin(math.sqrt(a)) <= _FOCUS_RADIUS_KM:
            return True
    return False


def _fetch_bbox(key: str, bbox: tuple, days: int) -> list[dict]:
    """Run the windowed FIRMS queries for one bounding box. Returns parsed rows."""
    bbox_str = ",".join(f"{v:.4f}" for v in bbox)
    now = datetime.now(timezone.utc).date()
    start = now - timedelta(days=days)

    fires: list[dict] = []
    cur = start
    while cur <= now:
        span = min(_WINDOW_DAYS, (now - cur).days + 1)
        url = _AREA_URL.format(key=key, source=_SOURCE, bbox=bbox_str,
                               days=span, date=cur.strftime("%Y-%m-%d"))
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            text = resp.text
            if text.lstrip().lower().startswith("invalid"):
                print(f"  [WARN] FIRMS rejected the request: {text[:120]}", file=sys.stderr)
                return fires
            fires.extend(_parse_rows(text))
        except Exception as exc:  # broad: thermal layer is supplementary, never fatal
            print(f"  [WARN] FIRMS window {cur} failed: {exc}", file=sys.stderr)
        cur += timedelta(days=_WINDOW_DAYS)
    return fires


def _in_bbox(lat: float, lon: float, bbox: tuple) -> bool:
    w, s, e, n = bbox
    return s <= lat <= n and w <= lon <= e


def _stratified_fill(rest: list[dict], bbox: tuple, limit: int) -> list[dict]:
    """Spatially fair top-up: grid the bbox and round-robin each cell's
    strongest detections, so big-burn regions can't crowd out the rest of
    the country."""
    if limit <= 0 or not rest:
        return []
    w, s, e, n = bbox
    cw = (e - w) / _GRID or 1.0
    ch = (n - s) / _GRID or 1.0

    cells: dict = {}
    for f in rest:
        ci = min(_GRID - 1, max(0, int((f["lon"] - w) / cw)))
        cj = min(_GRID - 1, max(0, int((f["lat"] - s) / ch)))
        cells.setdefault((ci, cj), []).append(f)
    for arr in cells.values():
        arr.sort(key=lambda f: -f["frp"])

    picked: list[dict] = []
    rank = 0
    while len(picked) < limit:
        advanced = False
        for arr in cells.values():
            if rank < len(arr):
                picked.append(arr[rank])
                advanced = True
                if len(picked) == limit:
                    break
        if not advanced:
            break
        rank += 1
    return picked


def get_fires(bbox: tuple[float, float, float, float], days: int,
              focus_points: list | None = None) -> list[dict]:
    """Fetch filtered VIIRS detections for the AOI and for out-of-AOI events.

    The AOI bbox is queried in 5-day windows; focus points falling OUTSIDE the
    AOI (e.g. a strike inside Russia reported in a Ukraine query) get their own
    small bounding-box queries so cross-border events are observable too.
    Retention: detections near any focus point are always kept, then the map
    layer fills to _MAX_FIRES with a spatially stratified top-by-FRP sample —
    a plain FRP sort would over-represent big-burn regions. Never raises.
    """
    if not has_firms_key():
        return []

    key = os.getenv("FIRMS_MAP_KEY")
    focus = [(p[0], p[1]) for p in (focus_points or []) if p and len(p) == 2]

    fires = _fetch_bbox(key, bbox, days)

    # Cross-border coverage: dedicated mini-boxes for events outside the AOI
    outside = [p for p in focus if not _in_bbox(p[0], p[1], bbox)]
    covered: list[tuple] = []
    for lat, lon in outside:
        if any(abs(lat - a) < _MINI_BBOX_PAD and abs(lon - o) < _MINI_BBOX_PAD
               for a, o in covered):
            continue
        covered.append((lat, lon))
        mini = (lon - _MINI_BBOX_PAD, lat - _MINI_BBOX_PAD,
                lon + _MINI_BBOX_PAD, lat + _MINI_BBOX_PAD)
        fires.extend(_fetch_bbox(key, mini, days))

    # Dedupe (window seams + overlapping boxes)
    seen: set = set()
    unique: list[dict] = []
    for f in fires:
        sig = (f["lat"], f["lon"], f["date"], f["time"])
        if sig not in seen:
            seen.add(sig)
            unique.append(f)

    near = [f for f in unique if focus and _near_any(f["lat"], f["lon"], focus)]
    near_ids = {id(f) for f in near}
    rest = [f for f in unique if id(f) not in near_ids]
    kept = near + _stratified_fill(rest, bbox, _MAX_FIRES - len(near))

    if unique:
        peak = max(f["frp"] for f in unique)
        print(f"  FIRMS:    {len(kept):>4} thermal detections kept "
              f"({len(near)} near events, {len(covered)} cross-border boxes, "
              f"of {len(unique)} confident, peak FRP {peak:.0f} MW)")
    else:
        print("  FIRMS:       0 thermal detections in window")
    return kept
