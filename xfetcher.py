"""X/Twitter post ingestion via an Apify pay-per-result tweet-scraper actor.

Uses the actor's synchronous run endpoint so one POST returns the dataset
directly. One call per run (each call carries a minimum charge, so no per-day
windowing like fetcher.py). Failure is always non-fatal — like GDELT, X data
is a supplementary signal and must never crash the pipeline.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

_ACTOR = "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
_RUN_SYNC_URL = f"https://api.apify.com/v2/acts/{_ACTOR}/run-sync-get-dataset-items"
# Apify kills sync runs at 300s server-side; stay under that client-side
_TIMEOUT_S = 240
_MIN_ITEMS = 20   # actor's floor — smaller values are not honored
_MAX_ITEMS = 200

# Tweet createdAt uses classic Twitter format: "Thu Oct 17 09:30:41 +0000 2024"
_CREATED_AT_FMT = "%a %b %d %H:%M:%S %z %Y"


def has_x_token() -> bool:
    """Return True if an Apify API token is configured."""
    token = os.getenv("APIFY_TOKEN")
    return bool(token) and token != "your_apify_token_here"


def _parse_created_at(raw: str) -> str:
    """Convert a tweet createdAt string to 'YYYY-MM-DD', or '' if unparseable."""
    if not raw:
        return ""
    try:
        return datetime.strptime(raw, _CREATED_AT_FMT).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    try:  # some responses use ISO 8601
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def _normalize_item(item: dict) -> dict | None:
    """Normalize one Apify tweet item to the GeoWatch post dict, or None to skip.

    The actor pads empty result sets with placeholder items typed 'mock_tweet';
    only genuine '"type": "tweet"' items are kept.
    """
    if item.get("type") != "tweet":
        return None
    author = item.get("author") or {}
    text = (item.get("text") or "").strip()
    if not text:
        return None
    return {
        "id":          str(item.get("id") or ""),
        "text":        text,
        "date":        _parse_created_at(item.get("createdAt") or ""),
        "author":      "@" + (author.get("userName") or "unknown"),
        "author_name": author.get("name") or "",
        "followers":   int(author.get("followers") or 0),
        "verified":    bool(author.get("isVerified") or author.get("isBlueVerified")),
        "url":         item.get("url") or item.get("twitterUrl") or "",
        "likes":       int(item.get("likeCount") or 0),
        "retweets":    int(item.get("retweetCount") or 0),
        "replies":     int(item.get("replyCount") or 0),
        "views":       int(item.get("viewCount") or 0),
    }


def _fmt_daterange(posts: list[dict]) -> str:
    """Return 'Mon D — Mon D' from the posts' date fields, or empty string."""
    dates = sorted(d for p in posts if (d := p.get("date", "")))
    if not dates:
        return ""
    try:
        def _fmt(ds: str) -> str:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            return dt.strftime("%b ") + str(dt.day)
        return f"{_fmt(dates[0])} — {_fmt(dates[-1])}"
    except (ValueError, TypeError):
        return ""


def _x_window(location: str, since: datetime, until: datetime, max_items: int) -> list:
    """One synchronous Apify actor run for a date window. Returns raw items or [].

    Date bounds go inline as Twitter search operators — the actor's separate
    since_time/until_time fields do not reliably constrain 'Latest' searches.
    """
    # 'until:' is exclusive of the date — pad a day so the boundary day is
    # included (dedupe by id absorbs any overlap between adjacent windows).
    # lang goes inline too: the top-level lang field doesn't constrain
    # inline-operator queries.
    # -filter:replies + min_faves biases toward original, visible posts
    # rather than reply-thread chatter
    query = (f"{location} lang:en -filter:replies min_faves:2 "
             f"since:{since.strftime('%Y-%m-%d')} "
             f"until:{(until + timedelta(days=1)).strftime('%Y-%m-%d')}")
    payload = {
        "searchTerms": [query],
        "maxItems": max(_MIN_ITEMS, min(max_items, _MAX_ITEMS)),
        "queryType": "Latest",
        "lang": "en",
    }
    try:
        resp = requests.post(
            _RUN_SYNC_URL,
            json=payload,
            headers={"Authorization": f"Bearer {os.getenv('APIFY_TOKEN')}"},
            timeout=_TIMEOUT_S,
        )
        if resp.status_code in (402, 403):
            print("  [WARN] X window failed: Apify credit exhausted or access denied "
                  f"(HTTP {resp.status_code})", file=sys.stderr)
            return []
        if resp.status_code == 408:
            print("  [WARN] X window failed: Apify actor run timed out", file=sys.stderr)
            return []
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            print("  [WARN] X window failed: unexpected Apify response shape", file=sys.stderr)
            return []
        return items
    except Exception as exc:  # broad: X data is supplementary and must never crash a run
        print(f"  [WARN] X window failed: {exc}", file=sys.stderr)
        return []


def get_x_posts(location: str, days: int, max_items: int = 100) -> tuple[list[dict], int]:
    """Fetch X posts mentioning the location via Apify, spread across the window.

    Like fetcher.py's date-windowed news fetch, the range is split into up to 4
    windows queried separately — a single 'Latest' query would cluster all posts
    in the most recent hours for high-volume topics. Never raises: on total
    failure returns ([], days).
    """
    if not has_x_token():
        return [], days

    now = datetime.now(timezone.utc)
    n_windows = min(4, max(1, days // 7))
    span = days / n_windows
    per_window = max(_MIN_ITEMS, max_items // n_windows)

    windows = [
        (now - timedelta(days=span * (i + 1)), now - timedelta(days=span * i))
        for i in range(n_windows)
    ]

    all_items: list = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_x_window, location, since, until, per_window)
                for since, until in windows]
        for fut in futs:
            all_items.extend(fut.result())

    seen: set[str] = set()
    posts: list[dict] = []
    for item in all_items:
        post = _normalize_item(item) if isinstance(item, dict) else None
        if post and post["id"] and post["id"] not in seen:
            seen.add(post["id"])
            posts.append(post)

    posts.sort(key=lambda p: p.get("date") or "")

    x_range = _fmt_daterange(posts)
    print(f"  X/Twitter:{len(posts):>4} posts"
          + (f" ({x_range})" if x_range else ""))
    return posts, days
