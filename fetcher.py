import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()


def get_news(location: str, days: int) -> list[dict]:
    """Fetch recent news articles mentioning a location from NewsAPI.

    Returns a list of article dicts with keys: title, date, source, url, description.
    """
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key or api_key == "your_newsapi_key_here":
        raise EnvironmentError(
            "NEWSAPI_KEY is not set. Add it to your .env file.\n"
            "Get a free key at https://newsapi.org/register"
        )

    from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "q": location,
        "from": from_date,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 100,
    }
    headers = {"X-Api-Key": api_key}

    try:
        response = requests.get(
            "https://newsapi.org/v2/everything",
            params=params,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        raise RuntimeError(f"NewsAPI request failed (HTTP {status}): {e}") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error contacting NewsAPI: {e}") from e

    data = response.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {data.get('message', 'unknown error')}")

    articles = []
    for item in data.get("articles", []):
        articles.append(
            {
                "title": item.get("title") or "",
                "date": (item.get("publishedAt") or "")[:10],
                "source": (item.get("source") or {}).get("name") or "",
                "url": item.get("url") or "",
                "description": item.get("description") or "",
            }
        )

    return articles
