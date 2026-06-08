import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_NEWSAPI_MAX_DAYS   = 30
_GDELT_MAX_DAYS     = 90
_NEWSAPI_PER_DAY    = 5   # articles fetched per day from NewsAPI
_GDELT_PER_DAY      = 5   # articles fetched per day from GDELT


def _make_daily_windows(days: int) -> list[tuple[datetime, datetime]]:
    """Return one (start, end) tuple per calendar day covering [now-days, now]."""
    end = datetime.utcnow()
    windows: list[tuple[datetime, datetime]] = []
    for offset in range(days):
        day_end   = end - timedelta(days=offset)
        day_start = day_end - timedelta(days=1)
        windows.append((day_start, day_end))
    return windows   # newest day first; order doesn't matter since we run in parallel


def _fmt_daterange(articles: list[dict]) -> str:
    """Return 'Mon D — Mon D' from the articles' date fields, or empty string."""
    dates = sorted(d for a in articles if (d := a.get("date", "")))
    if not dates:
        return ""
    try:
        def _fmt(ds: str) -> str:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            return dt.strftime("%b ") + str(dt.day)   # "Jun 6" not "Jun 06"
        return f"{_fmt(dates[0])} — {_fmt(dates[-1])}"
    except (ValueError, TypeError):
        return ""


# ── NewsAPI ───────────────────────────────────────────────────────────────────

def _newsapi_window(
    location: str, from_dt: datetime, to_dt: datetime, api_key: str
) -> list[dict]:
    """One NewsAPI request for a specific date window. Returns normalised dicts."""
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q":        location,
                "from":     from_dt.strftime("%Y-%m-%d"),
                "to":       to_dt.strftime("%Y-%m-%d"),
                "language": "en",
                "sortBy":   "publishedAt",
                "pageSize": _NEWSAPI_PER_DAY,
            },
            headers={"X-Api-Key": api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    if data.get("status") != "ok":
        return []

    return [
        {
            "title":       item.get("title")       or "",
            "date":        (item.get("publishedAt") or "")[:10],
            "source":      (item.get("source") or {}).get("name") or "",
            "url":         item.get("url")         or "",
            "description": item.get("description") or "",
            "image_url":   item.get("urlToImage")  or None,
        }
        for item in data.get("articles", [])
    ]


def get_newsapi_news(location: str, days: int) -> tuple[list[dict], int]:
    """One request per calendar day, all in parallel. Returns (articles, actual_days)."""
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key or api_key == "your_newsapi_key_here":
        raise EnvironmentError(
            "NEWSAPI_KEY is not set. Add it to your .env file.\n"
            "Get a free key at https://newsapi.org/register"
        )

    actual_days = days
    if days > _NEWSAPI_MAX_DAYS:
        actual_days = _NEWSAPI_MAX_DAYS
        print(
            "  [WARN] NewsAPI free tier limited to 30 days — "
            "GDELT will cover the remaining history.",
            file=sys.stderr,
        )

    windows = _make_daily_windows(actual_days)
    seen: set[str] = set()
    articles: list[dict] = []

    with ThreadPoolExecutor(max_workers=min(len(windows), 10)) as ex:
        futs = [ex.submit(_newsapi_window, location, ws, we, api_key) for ws, we in windows]
        for f in as_completed(futs):
            for art in f.result():
                url = art["url"]
                if url and url not in seen:
                    seen.add(url)
                    articles.append(art)

    return articles, actual_days


# ── GDELT ─────────────────────────────────────────────────────────────────────

def _gdelt_window(
    location: str, win_start: datetime, win_end: datetime
) -> list[dict]:
    """One GDELT request for a specific time window. Fails fast on 429 (no retry sleep)."""
    query     = f"{location} sourcelang:eng"
    start_str = win_start.strftime("%Y%m%d%H%M%S")
    end_str   = win_end.strftime("%Y%m%d%H%M%S")
    try:
        r = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query":         query,
                "mode":          "artlist",
                "maxrecords":    _GDELT_PER_DAY,
                "format":        "json",
                "startdatetime": start_str,
                "enddatetime":   end_str,
            },
            timeout=10,
        )
        if r.status_code == 429:
            return []   # rate-limited — skip this window, don't sleep
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"  [WARN] GDELT window {start_str[:8]}–{end_str[:8]} failed: {exc}",
              file=sys.stderr)
        return []

    out = []
    for item in (data.get("articles") or []):
        # Belt-and-suspenders English check alongside sourcelang:eng in the query
        lang = (item.get("language") or "").lower()
        if lang and lang not in ("eng", "english"):
            continue

        # seendate can be "20260601120000" or "20260601T120000Z" — normalise first
        seendate = (item.get("seendate") or "").replace("T", "").replace("Z", "")
        try:
            date_str = datetime.strptime(seendate[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            try:
                date_str = datetime.strptime(seendate[:8], "%Y%m%d").strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                date_str = ""

        out.append({
            "title":       item.get("title")  or "",
            "date":        date_str,
            "source":      item.get("domain") or "",
            "url":         item.get("url")    or "",
            "description": "",
            "image_url":   None,
        })
    return out


def get_gdelt_news(location: str, days: int) -> tuple[list[dict], int]:
    """Query each 7-day window in parallel. Returns (articles, actual_days).
    Never raises — returns empty list on total failure so NewsAPI still works.
    """
    actual_days = days
    if days > _GDELT_MAX_DAYS:
        actual_days = _GDELT_MAX_DAYS
        print(
            "  [WARN] GDELT free tier limited to 90 days — showing maximum available history.",
            file=sys.stderr,
        )

    windows = _make_daily_windows(actual_days)
    seen: set[str] = set()
    articles: list[dict] = []

    # Limit concurrency to avoid GDELT rate-limiting (especially on shared production IPs)
    try:
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(_gdelt_window, location, ws, we) for ws, we in windows]
            for f in as_completed(futs):
                for art in f.result():
                    url = art["url"]
                    if url and url not in seen:
                        seen.add(url)
                        articles.append(art)
    except Exception as exc:
        print(f"  [WARN] GDELT fetch failed: {exc}", file=sys.stderr)

    return articles[:200], actual_days


# ── Location synonym expansion ────────────────────────────────────────────────

def _get_location_synonyms(location: str) -> set[str]:
    """Ask Groq for ~20 terms that appear in news about this location.

    Returns a set containing at minimum the location name itself.
    Falls back silently if the API key is missing or the call fails.
    """
    base = {location.lower()}
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        return base
    try:
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": (
                    f"Return a JSON array of up to 20 lowercase search terms that commonly "
                    f"appear in English news articles about '{location}'. "
                    f"Include: the location name itself, demonym, capital city, major cities, "
                    f"key regions, and common abbreviations or proper nouns. "
                    f"Return ONLY a JSON array of strings, no explanation, no markdown."
                ),
            }],
            temperature=0.1,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip().strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
        terms = json.loads(raw)
        if isinstance(terms, list):
            result = {t.lower() for t in terms if isinstance(t, str) and t.strip()}
            result.update(base)
            return result
    except Exception as exc:
        print(f"  [WARN] Synonym expansion failed: {exc}", file=sys.stderr)
    return base


# ── Combined entry point ──────────────────────────────────────────────────────

def get_news(location: str, days: int) -> list[dict]:
    """Fetch from NewsAPI and GDELT in parallel, merge, deduplicate, sort by date.

    NewsAPI articles win on URL collision (they carry images + descriptions).
    Prints a sourcing summary with actual date coverage.
    Raises EnvironmentError if the NewsAPI key is missing.
    """
    newsapi_articles: list[dict] = []
    gdelt_articles:   list[dict] = []
    newsapi_days = min(days, _NEWSAPI_MAX_DAYS)
    gdelt_days   = min(days, _GDELT_MAX_DAYS)

    # Run synonym expansion in parallel with fetching — adds zero wall-clock time
    with ThreadPoolExecutor(max_workers=3) as ex:
        synonyms_fut  = ex.submit(_get_location_synonyms, location)
        newsapi_fut   = ex.submit(get_newsapi_news, location, days)
        gdelt_fut     = ex.submit(get_gdelt_news,   location, days)

        synonyms                    = synonyms_fut.result()
        newsapi_articles, newsapi_days = newsapi_fut.result()   # propagates EnvironmentError
        try:
            gdelt_articles, gdelt_days = gdelt_fut.result()
        except Exception as exc:
            print(f"  [WARN] GDELT unavailable: {exc}", file=sys.stderr)

    # Merge: NewsAPI first so richer articles win on URL collision
    seen: set[str] = set()
    merged: list[dict] = []
    for art in newsapi_articles:
        url = art["url"]
        if url and url not in seen:
            seen.add(url)
            merged.append(art)
    for art in gdelt_articles:
        url = art["url"]
        if url and url not in seen:
            seen.add(url)
            merged.append(art)

    # Keep articles where any synonym appears in title or description
    before = len(merged)
    def _relevant(art: dict) -> bool:
        text = ((art.get("title") or "") + " " + (art.get("description") or "")).lower()
        return any(syn in text for syn in synonyms)
    merged = [a for a in merged if _relevant(a)]
    dropped = before - len(merged)

    # Sort chronologically so visualisations reflect the full time span
    merged.sort(key=lambda a: a.get("date") or "")

    # Print sourcing summary
    na_range = _fmt_daterange(newsapi_articles)
    gd_range = _fmt_daterange(gdelt_articles)
    all_range = _fmt_daterange(merged)
    print(f"  NewsAPI:  {len(newsapi_articles):>4} articles"
          + (f" ({na_range})" if na_range else ""))
    print(f"  GDELT:    {len(gdelt_articles):>4} articles"
          + (f" ({gd_range})" if gd_range else ""))
    print(f"  Terms:    {', '.join(sorted(synonyms)[:10])}"
          + (" …" if len(synonyms) > 10 else ""))
    if dropped:
        print(f"  Filtered: {dropped:>4} articles (no synonym match)")
    print(f"  Total:    {len(merged):>4} articles (after dedup + filter)")
    if all_range:
        print(f"  Date coverage: {all_range}")

    return merged
