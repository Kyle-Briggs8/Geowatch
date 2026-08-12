"""Cross-INT fusion: correlate news events with X social posts.

A social post corroborates a news event when it names at least one of the
event's *distinctive* entities within a ±2 day window of the article date.
Entities that appear in most events (the AOI itself, ubiquitous actors like
the belligerents in a war query) carry no discriminating power and are
excluded IDF-style, so corroboration means genuinely specific overlap —
same people, same organizations, same places — not just "both mention the
topic".

Posts dated before the article are flagged as early signals: social chatter
that led the news reporting.
"""

import math
from datetime import datetime

# Entities appearing in more than this share of events are too generic to
# corroborate anything (e.g. "Ukraine" in a Ukraine query)
_GENERIC_DF = 0.5
_MIN_ENTITY_LEN = 4
_WINDOW_DAYS = 2

# Thermal corroboration: a satellite detection supports an event when it sits
# within this radius and day window of the event's point-precision coordinates
_FIRE_RADIUS_KM = 20.0
_FIRE_WINDOW_DAYS = 1


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def correlate_fires(events: list[dict], fires: list[dict]) -> dict:
    """Match satellite thermal detections to point-precision news events.

    A detection corroborates an event when it lies within _FIRE_RADIUS_KM of
    the event's geocoded coordinates and within ±_FIRE_WINDOW_DAYS of the
    article date. Country-level and un-geocoded events are excluded — a
    country-wide match would be meaningless.

    Returns {event_url: {"count": int, "peak_frp": float, "dates": [..]}}.
    """
    result: dict = {}
    if not fires:
        return result

    parsed_fires = []
    for f in fires:
        d = _parse_date(f.get("date"))
        if d and f.get("lat") is not None and f.get("lon") is not None:
            parsed_fires.append((f["lat"], f["lon"], d, f.get("frp") or 0.0))

    for ev in events:
        if not ev.get("analysis"):
            continue
        if ev.get("loc_precision") not in ("point", "region"):
            continue
        coords = ev.get("coords")
        if not coords or len(coords) != 2:
            continue
        ev_date = _parse_date(ev.get("article", {}).get("date"))
        if not ev_date:
            continue

        count, peak, dates = 0, 0.0, set()
        for lat, lon, f_date, frp in parsed_fires:
            if abs((f_date - ev_date).days) > _FIRE_WINDOW_DAYS:
                continue
            if _haversine_km(coords[0], coords[1], lat, lon) <= _FIRE_RADIUS_KM:
                count += 1
                peak = max(peak, frp)
                dates.add(f_date.strftime("%b %d"))

        if count:
            url = ev.get("article", {}).get("url") or ""
            result[url] = {"count": count, "peak_frp": peak, "dates": sorted(dates)}
    return result


def _parse_date(s: str | None):
    try:
        return datetime.strptime(s or "", "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _distinctive_entities(events: list[dict], location: str) -> dict[str, set]:
    """Map event url -> set of lowercase distinctive entity names."""
    analyzed = [e for e in events if e.get("analysis")]
    n = len(analyzed) or 1
    df: dict[str, int] = {}
    per_event: dict[str, set] = {}

    for ev in analyzed:
        ents = {
            e.strip().lower()
            for e in (ev["analysis"].get("entities") or [])
            if isinstance(e, str) and len(e.strip()) >= _MIN_ENTITY_LEN
        }
        per_event[ev.get("article", {}).get("url") or id(ev)] = ents
        for e in ents:
            df[e] = df.get(e, 0) + 1

    loc = location.strip().lower()
    generic = {e for e, c in df.items() if c >= 2 and c / n > _GENERIC_DF} | {loc}

    return {url: ents - generic for url, ents in per_event.items()}


def correlate(events: list[dict], x_events: list[dict], location: str) -> dict:
    """Match X posts to news events by distinctive-entity overlap within ±2 days.

    Returns {
      "by_event":  {event_url: {"post_ids": [...], "early": bool}},
      "early_ids": set of post ids that led any matched news report by >= 1 day,
      "n_corroborated": int,
      "n_events": int,
    }
    """
    result = {"by_event": {}, "early_ids": set(), "n_corroborated": 0,
              "n_events": sum(1 for e in events if e.get("analysis"))}
    if not x_events:
        return result

    ent_map = _distinctive_entities(events, location)

    posts = [
        (e["post"].get("id") or "", (e["post"].get("text") or "").lower(),
         _parse_date(e["post"].get("date")))
        for e in x_events
    ]

    for ev in events:
        if not ev.get("analysis"):
            continue
        url = ev.get("article", {}).get("url") or id(ev)
        ents = ent_map.get(url) or set()
        if not ents:
            continue
        ev_date = _parse_date(ev.get("article", {}).get("date"))
        if not ev_date:
            continue

        matched, early = [], False
        for pid, text, p_date in posts:
            if not pid or not p_date:
                continue
            delta = (p_date - ev_date).days
            if abs(delta) > _WINDOW_DAYS:
                continue
            if any(ent in text for ent in ents):
                matched.append(pid)
                if delta <= -1:
                    early = True
                    result["early_ids"].add(pid)

        if matched:
            result["by_event"][url] = {"post_ids": matched, "early": early}
            result["n_corroborated"] += 1

    return result
