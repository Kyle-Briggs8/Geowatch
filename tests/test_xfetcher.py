"""Tests for xfetcher.py — Apify item normalization and failure handling, no live calls."""
from unittest.mock import patch, MagicMock

import pytest

import xfetcher


def _apify_item(**overrides):
    item = {
        "type": "tweet",
        "id": "1846000000000000001",
        "url": "https://x.com/reporter/status/1846000000000000001",
        "text": "Explosions reported in the capital tonight, air defense active.",
        "createdAt": "Thu Oct 17 09:30:41 +0000 2024",
        "likeCount": 1250,
        "retweetCount": 340,
        "replyCount": 89,
        "viewCount": 120000,
        "author": {
            "userName": "reporter",
            "name": "Field Reporter",
            "followers": 52000,
            "isVerified": False,
            "isBlueVerified": True,
        },
    }
    item.update(overrides)
    return item


class TestNormalizeItem:

    def test_normalizes_all_fields(self):
        post = xfetcher._normalize_item(_apify_item())
        assert post == {
            "media": [],
            "id": "1846000000000000001",
            "text": "Explosions reported in the capital tonight, air defense active.",
            "date": "2024-10-17",
            "author": "@reporter",
            "author_name": "Field Reporter",
            "followers": 52000,
            "verified": True,
            "url": "https://x.com/reporter/status/1846000000000000001",
            "likes": 1250,
            "retweets": 340,
            "replies": 89,
            "views": 120000,
        }

    def test_mock_tweet_items_are_dropped(self):
        assert xfetcher._normalize_item(_apify_item(type="mock_tweet")) is None

    def test_empty_text_is_dropped(self):
        assert xfetcher._normalize_item(_apify_item(text="   ")) is None

    def test_missing_counts_default_to_zero(self):
        item = _apify_item()
        for key in ("likeCount", "retweetCount", "replyCount", "viewCount"):
            del item[key]
        post = xfetcher._normalize_item(item)
        assert (post["likes"], post["retweets"], post["replies"], post["views"]) == (0, 0, 0, 0)

    def test_twitterurl_fallback(self):
        item = _apify_item(url=None, twitterUrl="https://x.com/a/status/1")
        assert xfetcher._normalize_item(item)["url"] == "https://x.com/a/status/1"

    def test_no_media_gives_empty_list(self):
        assert xfetcher._normalize_item(_apify_item())["media"] == []

    def test_photo_media_extracted(self):
        item = _apify_item(extendedEntities={"media": [{
            "type": "photo",
            "media_url_https": "https://pbs.twimg.com/media/ABC.jpg",
            "expanded_url": "https://x.com/a/status/1/photo/1",
        }]})
        assert xfetcher._normalize_item(item)["media"] == [
            {"type": "photo", "thumb": "https://pbs.twimg.com/media/ABC.jpg"}
        ]

    def test_video_media_inferred_without_type(self):
        item = _apify_item(extendedEntities={"media": [{
            "media_url_https": "https://pbs.twimg.com/amplify_video_thumb/1/img/x.jpg",
            "expanded_url": "https://x.com/a/status/1/video/1",
        }]})
        assert xfetcher._normalize_item(item)["media"][0]["type"] == "video"

    def test_media_capped_at_four(self):
        entries = [{"type": "photo",
                    "media_url_https": f"https://pbs.twimg.com/media/{i}.jpg"}
                   for i in range(6)]
        item = _apify_item(extendedEntities={"media": entries})
        assert len(xfetcher._normalize_item(item)["media"]) == 4


class TestParseCreatedAt:

    def test_classic_twitter_format(self):
        assert xfetcher._parse_created_at("Thu Oct 17 09:30:41 +0000 2024") == "2024-10-17"

    def test_iso_format_fallback(self):
        assert xfetcher._parse_created_at("2026-08-01T12:00:00Z") == "2026-08-01"

    def test_garbage_returns_empty(self):
        assert xfetcher._parse_created_at("not a date") == ""
        assert xfetcher._parse_created_at("") == ""


class TestGetXPosts:

    def test_missing_token_returns_empty_without_http(self, monkeypatch):
        monkeypatch.delenv("APIFY_TOKEN", raising=False)
        with patch("xfetcher.requests.post") as mock_post:
            posts, days = xfetcher.get_x_posts("Ukraine", 30)
        assert posts == []
        assert days == 30
        mock_post.assert_not_called()

    def test_successful_fetch_normalizes_dedupes_sorts(self, monkeypatch):
        monkeypatch.setenv("APIFY_TOKEN", "test-token")
        items = [
            _apify_item(id="2", createdAt="Fri Oct 18 10:00:00 +0000 2024"),
            _apify_item(id="1"),
            _apify_item(id="1"),                      # duplicate
            _apify_item(type="mock_tweet", id="3"),   # padding item
        ]
        resp = MagicMock(status_code=200)
        resp.json.return_value = items
        with patch("xfetcher.requests.post", return_value=resp):
            posts, _ = xfetcher.get_x_posts("Ukraine", 30)
        assert [p["id"] for p in posts] == ["1", "2"]  # deduped, sorted by date

    @pytest.mark.parametrize("status", [402, 403, 408])
    def test_error_statuses_return_empty_without_raising(self, monkeypatch, status):
        monkeypatch.setenv("APIFY_TOKEN", "test-token")
        resp = MagicMock(status_code=status)
        with patch("xfetcher.requests.post", return_value=resp):
            posts, days = xfetcher.get_x_posts("Ukraine", 30)
        assert posts == []
        assert days == 30

    def test_network_exception_returns_empty(self, monkeypatch):
        monkeypatch.setenv("APIFY_TOKEN", "test-token")
        with patch("xfetcher.requests.post", side_effect=ConnectionError("boom")):
            posts, _ = xfetcher.get_x_posts("Ukraine", 30)
        assert posts == []

    def test_non_list_response_returns_empty(self, monkeypatch):
        monkeypatch.setenv("APIFY_TOKEN", "test-token")
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"error": "unexpected"}
        with patch("xfetcher.requests.post", return_value=resp):
            posts, _ = xfetcher.get_x_posts("Ukraine", 30)
        assert posts == []

    def test_max_items_clamped_to_actor_floor(self, monkeypatch):
        monkeypatch.setenv("APIFY_TOKEN", "test-token")
        resp = MagicMock(status_code=200)
        resp.json.return_value = []
        with patch("xfetcher.requests.post", return_value=resp) as mock_post:
            xfetcher.get_x_posts("Ukraine", 30, max_items=5)
        assert mock_post.call_args.kwargs["json"]["maxItems"] == 20

    def test_range_is_split_into_windows(self, monkeypatch):
        monkeypatch.setenv("APIFY_TOKEN", "test-token")
        resp = MagicMock(status_code=200)
        resp.json.return_value = []
        with patch("xfetcher.requests.post", return_value=resp) as mock_post:
            xfetcher.get_x_posts("Ukraine", 30)
        assert mock_post.call_count == 4   # 30 days → 4 windows
        with patch("xfetcher.requests.post", return_value=resp) as mock_post:
            xfetcher.get_x_posts("Ukraine", 7)
        assert mock_post.call_count == 1   # short range → single window


class TestHasXToken:

    def test_true_when_set(self, monkeypatch):
        monkeypatch.setenv("APIFY_TOKEN", "real-token")
        assert xfetcher.has_x_token()

    def test_false_when_missing_or_placeholder(self, monkeypatch):
        monkeypatch.delenv("APIFY_TOKEN", raising=False)
        assert not xfetcher.has_x_token()
        monkeypatch.setenv("APIFY_TOKEN", "your_apify_token_here")
        assert not xfetcher.has_x_token()
