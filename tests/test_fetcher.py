"""Tests for fetcher.py — all external calls mocked."""
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_newsapi_response(articles):
    """Build a mock requests.Response that looks like a successful NewsAPI reply."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "ok",
        "totalResults": len(articles),
        "articles": articles,
    }
    mock_resp.raise_for_status = MagicMock()  # no-op
    return mock_resp


def _newsapi_article(n=1):
    return {
        "title": f"Test Article {n}",
        "publishedAt": f"2026-05-{n:02d}T12:00:00Z",
        "source": {"name": f"Source {n}"},
        "url": f"https://example.com/article-{n}",
        "description": f"Description {n}",
        "urlToImage": f"https://example.com/image-{n}.jpg",
    }


# ---------------------------------------------------------------------------
# get_newsapi_news
# ---------------------------------------------------------------------------

class TestGetNewsapiNews:

    def test_returns_list_of_dicts_with_expected_keys(self):
        """Returns a list of dicts with the normalised keys on a 200 OK response."""
        raw_article = _newsapi_article(1)
        mock_resp = _make_newsapi_response([raw_article])

        with patch("fetcher._newsapi_window") as mock_window, \
             patch.dict(os.environ, {"NEWSAPI_KEY": "test-key-123"}):
            # Patch _newsapi_window to return our normalized dict directly
            mock_window.return_value = [
                {
                    "title": raw_article["title"],
                    "date": raw_article["publishedAt"][:10],
                    "source": raw_article["source"]["name"],
                    "url": raw_article["url"],
                    "description": raw_article["description"],
                    "image_url": raw_article["urlToImage"],
                }
            ]
            import fetcher
            articles, actual_days = fetcher.get_newsapi_news("TestLocation", 1)

        assert isinstance(articles, list)
        assert len(articles) >= 1
        expected_keys = {"title", "date", "source", "url", "description", "image_url"}
        for art in articles:
            assert expected_keys == set(art.keys()), f"Missing keys in: {art}"

    def test_returns_empty_list_on_http_500(self):
        """Returns an empty list when the API returns HTTP 500."""
        with patch("requests.get") as mock_get, \
             patch.dict(os.environ, {"NEWSAPI_KEY": "test-key-123"}):
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.raise_for_status.side_effect = Exception("Server Error")
            mock_get.return_value = mock_resp

            import fetcher
            articles, _ = fetcher.get_newsapi_news("TestLocation", 1)

        assert articles == []

    def test_normalized_keys_from_newsapi_json(self):
        """_newsapi_window correctly maps NewsAPI JSON keys to normalised keys."""
        raw_article = _newsapi_article(1)
        mock_resp = _make_newsapi_response([raw_article])

        with patch("requests.get", return_value=mock_resp), \
             patch.dict(os.environ, {"NEWSAPI_KEY": "test-key-123"}):
            import fetcher
            result = fetcher._newsapi_window(
                "TestLocation",
                datetime(2026, 5, 1),
                datetime(2026, 5, 2),
                "test-key-123",
            )

        assert len(result) == 1
        art = result[0]
        assert art["title"] == raw_article["title"]
        assert art["date"] == "2026-05-01"
        assert art["source"] == "Source 1"
        assert art["url"] == raw_article["url"]
        assert art["description"] == raw_article["description"]
        assert art["image_url"] == raw_article["urlToImage"]


# ---------------------------------------------------------------------------
# _gdelt_window
# ---------------------------------------------------------------------------

class TestGdeltWindow:

    def test_parses_seendate_yyyymmddhhmmss(self):
        """_gdelt_window converts GDELT's 'YYYYMMDDHHMMSS' seendate to 'YYYY-MM-DD'."""
        gdelt_data = {
            "articles": [
                {
                    "title": "GDELT article",
                    "seendate": "20260601120000",
                    "language": "English",
                    "domain": "bbc.com",
                    "url": "https://bbc.com/gdelt-article-1",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = gdelt_data
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_resp):
            import fetcher
            result = fetcher._gdelt_window(
                "TestLocation",
                datetime(2026, 6, 1),
                datetime(2026, 6, 2),
            )

        assert len(result) == 1
        assert result[0]["date"] == "2026-06-01"

    def test_parses_seendate_with_T_and_Z(self):
        """_gdelt_window handles 'YYYYMMDDTHHMMSSZ' seendate format."""
        gdelt_data = {
            "articles": [
                {
                    "title": "GDELT article T format",
                    "seendate": "20260601T120000Z",
                    "language": "eng",
                    "domain": "reuters.com",
                    "url": "https://reuters.com/gdelt-2",
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = gdelt_data
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_resp):
            import fetcher
            result = fetcher._gdelt_window(
                "TestLocation",
                datetime(2026, 6, 1),
                datetime(2026, 6, 2),
            )

        assert len(result) == 1
        assert result[0]["date"] == "2026-06-01"

    def test_filters_non_english_articles(self):
        """_gdelt_window excludes articles with a non-English language tag."""
        gdelt_data = {
            "articles": [
                {
                    "title": "English article",
                    "seendate": "20260601120000",
                    "language": "English",
                    "domain": "bbc.com",
                    "url": "https://bbc.com/en-article",
                },
                {
                    "title": "French article",
                    "seendate": "20260601120000",
                    "language": "French",
                    "domain": "lemonde.fr",
                    "url": "https://lemonde.fr/fr-article",
                },
                {
                    "title": "Eng tag article",
                    "seendate": "20260601120000",
                    "language": "eng",
                    "domain": "reuters.com",
                    "url": "https://reuters.com/eng-article",
                },
                {
                    "title": "Spanish article",
                    "seendate": "20260601120000",
                    "language": "Spanish",
                    "domain": "elpais.com",
                    "url": "https://elpais.com/es-article",
                },
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = gdelt_data
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_resp):
            import fetcher
            result = fetcher._gdelt_window(
                "TestLocation",
                datetime(2026, 6, 1),
                datetime(2026, 6, 2),
            )

        urls = [r["url"] for r in result]
        assert "https://bbc.com/en-article" in urls
        assert "https://reuters.com/eng-article" in urls
        assert "https://lemonde.fr/fr-article" not in urls
        assert "https://elpais.com/es-article" not in urls
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:

    def test_duplicate_urls_appear_only_once_in_merged_results(self):
        """When NewsAPI and GDELT return the same URL, it appears only once."""
        shared_url = "https://shared.com/duplicate-article"

        newsapi_article = {
            "title": "Shared article (NewsAPI)",
            "date": "2026-05-01",
            "source": "Reuters",
            "url": shared_url,
            "description": "From NewsAPI",
            "image_url": "https://img.com/pic.jpg",
        }
        gdelt_article = {
            "title": "Shared article (GDELT)",
            "date": "2026-05-01",
            "source": "reuters.com",
            "url": shared_url,
            "description": "",
            "image_url": None,
        }

        with patch("fetcher.get_newsapi_news", return_value=([newsapi_article], 1)), \
             patch("fetcher.get_gdelt_news", return_value=([gdelt_article], 1)), \
             patch("fetcher._get_location_synonyms", return_value={"testlocation", "shared"}), \
             patch.dict(os.environ, {"NEWSAPI_KEY": "test-key-123"}):
            import fetcher
            result = fetcher.get_news("TestLocation", 1)

        urls = [a["url"] for a in result]
        assert urls.count(shared_url) == 1, "Duplicate URL appeared more than once"


# ---------------------------------------------------------------------------
# _make_daily_windows
# ---------------------------------------------------------------------------

class TestMakeDailyWindows:

    def test_28_days_returns_exactly_28_windows(self):
        """_make_daily_windows(28) returns exactly 28 (start, end) tuples."""
        import fetcher
        windows = fetcher._make_daily_windows(28)
        assert len(windows) == 28

    def test_1_day_returns_1_window(self):
        import fetcher
        windows = fetcher._make_daily_windows(1)
        assert len(windows) == 1

    def test_windows_are_tuples_of_datetimes(self):
        import fetcher
        windows = fetcher._make_daily_windows(7)
        for start, end in windows:
            assert isinstance(start, datetime)
            assert isinstance(end, datetime)

    def test_each_window_is_one_day_wide(self):
        """Each window should span exactly 1 day (timedelta of 1 day)."""
        from datetime import timedelta
        import fetcher
        windows = fetcher._make_daily_windows(5)
        for start, end in windows:
            delta = end - start
            assert delta == timedelta(days=1), f"Window not 1 day wide: {delta}"
