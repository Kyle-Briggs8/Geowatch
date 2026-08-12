"""Demo-mode cache: save and reload analyzed event sets as JSON.

Lets the dashboard render from a previously captured run so live demos never
depend on NewsAPI quotas, GDELT availability, or Groq rate limits.
Cached datasets live in demo_data/ and are committed to the repo.
"""

import json
import os
from datetime import datetime

DEMO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_data")


def _demo_path(location: str) -> str:
    """Return the cache file path for a location (lowercased, spaces to underscores)."""
    slug = location.strip().lower().replace(" ", "_")
    return os.path.join(DEMO_DIR, f"{slug}.json")


def has_demo(location: str) -> bool:
    """Return True if a cached demo dataset exists for the location."""
    return os.path.isfile(_demo_path(location))


def save_demo_events(location: str, days: int, events: list[dict],
                     x_events: list[dict] | None = None,
                     fires: list[dict] | None = None) -> str:
    """Write analyzed events (and optionally X posts and thermal detections)
    to the demo cache.

    Returns the file path. Optional keys are only present when captured,
    so older cache files remain valid.
    """
    os.makedirs(DEMO_DIR, exist_ok=True)
    path = _demo_path(location)
    payload = {
        "location": location,
        "days": days,
        "captured_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "events": events,
    }
    if x_events is not None:
        payload["x_events"] = x_events
    if fires is not None:
        payload["fires"] = fires
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def load_demo_events(location: str) -> dict:
    """Return the cached payload {location, days, captured_at, events} for a location.

    Raises FileNotFoundError with a helpful message if no cache exists.
    """
    path = _demo_path(location)
    if not os.path.isfile(path):
        available = ", ".join(sorted(list_demo_locations())) or "none"
        raise FileNotFoundError(
            f"No demo dataset for '{location}'. Available: {available}. "
            f"Capture one with: python main.py --location \"{location}\" --save-demo"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_demo_locations() -> list[str]:
    """Return location names (slugs) that have cached demo datasets."""
    if not os.path.isdir(DEMO_DIR):
        return []
    return [
        os.path.splitext(name)[0]
        for name in os.listdir(DEMO_DIR)
        if name.endswith(".json")
    ]
