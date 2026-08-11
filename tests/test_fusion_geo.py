"""Tests for fusion.py (cross-INT correlation) and geocoder.py — no live calls."""
from unittest.mock import patch, MagicMock

import pytest

import geocoder
from fusion import correlate
from visualizer import build_dashboard, _marker_location


def _news_event(url, date, entities, etype="conflict"):
    return {
        "article": {"url": url, "date": date, "source": "Reuters", "title": "t"},
        "analysis": {"event_type": etype, "severity": "high",
                     "entities": entities, "one_line_summary": "s"},
    }


def _x_event(pid, date, text):
    return {
        "post": {"id": pid, "date": date, "text": text, "author": "@a",
                 "followers": 10, "url": "https://x.com/a/status/" + pid,
                 "likes": 1, "retweets": 1, "replies": 0, "views": 5},
        "analysis": {"event_type": "conflict", "severity": "high", "credibility": 3},
    }


class TestCorrelate:

    def test_entity_match_within_window(self):
        events = [
            _news_event("u1", "2026-08-05", ["Kharkiv Oblast", "Russia"]),
            _news_event("u2", "2026-08-05", ["Zelensky", "Russia"]),
        ]
        x = [_x_event("p1", "2026-08-06", "strikes reported across kharkiv oblast tonight")]
        corr = correlate(events, x, "Ukraine")
        assert corr["by_event"]["u1"]["post_ids"] == ["p1"]
        assert "u2" not in corr["by_event"]
        assert corr["n_corroborated"] == 1

    def test_outside_window_no_match(self):
        events = [_news_event("u1", "2026-08-01", ["Kharkiv Oblast"])]
        x = [_x_event("p1", "2026-08-06", "kharkiv oblast under fire")]
        assert correlate(events, x, "Ukraine")["by_event"] == {}

    def test_generic_entities_excluded(self):
        # "Russia" appears in >50% of events → too generic to corroborate
        events = [
            _news_event("u1", "2026-08-05", ["Russia"]),
            _news_event("u2", "2026-08-05", ["Russia"]),
            _news_event("u3", "2026-08-05", ["Russia", "Wildberries"]),
        ]
        x = [_x_event("p1", "2026-08-05", "russia launches more attacks")]
        corr = correlate(events, x, "Ukraine")
        assert corr["by_event"] == {}

    def test_aoi_location_excluded(self):
        events = [_news_event("u1", "2026-08-05", ["Ukraine"])]
        x = [_x_event("p1", "2026-08-05", "thoughts on ukraine today")]
        assert correlate(events, x, "Ukraine")["by_event"] == {}

    def test_early_signal_flagged(self):
        events = [_news_event("u1", "2026-08-05", ["Taneco Refinery"])]
        x = [_x_event("p1", "2026-08-04", "fire at the taneco refinery confirmed")]
        corr = correlate(events, x, "Ukraine")
        assert corr["by_event"]["u1"]["early"] is True
        assert "p1" in corr["early_ids"]

    def test_same_day_not_early(self):
        events = [_news_event("u1", "2026-08-05", ["Taneco Refinery"])]
        x = [_x_event("p1", "2026-08-05", "taneco refinery burning")]
        corr = correlate(events, x, "Ukraine")
        assert corr["by_event"]["u1"]["early"] is False
        assert corr["early_ids"] == set()

    def test_no_x_events(self):
        events = [_news_event("u1", "2026-08-05", ["Kharkiv"])]
        corr = correlate(events, [], "Ukraine")
        assert corr["by_event"] == {}
        assert corr["n_corroborated"] == 0


class TestCorrelationUI:

    def test_badge_dropdown_and_early_pill_render(self, sample_events):
        events = [_news_event("u1", "2026-08-05", ["Taneco Refinery"])]
        x = [_x_event("p1", "2026-08-04", "fire at the taneco refinery confirmed")]
        x[0]["post"]["media"] = [
            {"type": "video", "thumb": "https://pbs.twimg.com/amplify_video_thumb/9/img/z.jpg"}]
        html = build_dashboard(events, "Ukraine", 30, x_events=x, x_status="ok")
        assert "cp-thumb" in html and "cp-play" in html   # media thumb in dropdown
        assert "corr-badge" in html
        assert 'data-target="corr-0"' in html          # badge toggles the panel
        assert 'id="corr-0"' in html                   # inline dropdown panel
        assert "taneco refinery confirmed" in html     # post text inside panel
        assert 'class="corr-jump" data-ids="p1"' in html  # jump link to X tab
        assert "led by social" in html
        assert "EARLY SIGNAL" in html
        assert 'data-xid="p1"' in html
        assert "Cross-INT: 1 of 1" in html

    def test_no_badges_without_matches(self, sample_events, sample_x_events):
        html = build_dashboard(sample_events, "Ukraine", 30,
                               x_events=sample_x_events, x_status="ok")
        assert "corr-badge" not in html.replace(".corr-badge", "")


class TestMarkerLocation:

    def test_uses_real_coords_when_present(self):
        ev = {"article": {"url": "u"}, "coords": [49.99, 36.23]}
        assert _marker_location(ev, (48.0, 31.0)) == (49.99, 36.23)

    def test_no_coords_falls_back_to_exact_aoi_centroid(self):
        ev = {"article": {"url": "https://a.com/1", "title": "t"}}
        assert _marker_location(ev, (48.0, 31.0)) == (48.0, 31.0)

    def test_country_precision_sits_on_its_own_coords(self):
        # no synthetic jitter — co-located markers are the cluster's job
        ev = {"article": {"url": "u", "title": "t"},
              "coords": [49.48, 31.27], "loc_precision": "country"}
        assert _marker_location(ev, (48.0, 31.0)) == (49.48, 31.27)

    def test_approx_marker_rendered_dashed(self, sample_events):
        from visualizer import _map_iframe
        import base64, re
        ev = dict(sample_events[0])
        ev["coords"] = [49.48, 31.27]
        ev["loc_precision"] = "country"
        html = _map_iframe([ev], "Ukraine")
        inner = base64.b64decode(
            re.search(r"base64,([A-Za-z0-9+/=]+)", html).group(1)).decode("utf-8")
        assert "dashed" in inner
        assert "data-approx" in inner


class TestGeocoder:

    @pytest.fixture(autouse=True)
    def _fresh_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(geocoder, "_CACHE_PATH", str(tmp_path / "geo.json"))
        monkeypatch.setattr(geocoder, "_cache", None)
        monkeypatch.setattr(geocoder, "_last_request", 0.0)
        monkeypatch.setattr(geocoder.time, "sleep", lambda s: None)

    def _resp(self, results):
        r = MagicMock()
        r.json.return_value = results
        r.raise_for_status.return_value = None
        return r

    def test_bare_query_first(self):
        # bare name first: importance ranking resolves prominent places correctly
        with patch("geocoder.requests.get",
                   return_value=self._resp([{"lat": "50.06", "lon": "19.94",
                                            "addresstype": "city"}])) as g:
            hit = geocoder.geocode_place("Krakow", "Ukraine")
        assert hit == {"coords": [50.06, 19.94], "precision": "point"}
        assert g.call_args_list[0].kwargs["params"]["q"] == "Krakow"

    def test_falls_back_to_region_hint(self):
        empty, hit = self._resp([]), self._resp([{"lat": "48.71", "lon": "37.53"}])
        with patch("geocoder.requests.get", side_effect=[empty, hit]) as g:
            result = geocoder.geocode_place("Mykolaivka", "Ukraine")
        assert result["coords"] == [48.71, 37.53]
        assert g.call_count == 2
        assert g.call_args_list[1].kwargs["params"]["q"] == "Mykolaivka, Ukraine"

    def test_country_and_region_precision(self):
        with patch("geocoder.requests.get",
                   return_value=self._resp([{"lat": "49.48", "lon": "31.27",
                                            "addresstype": "country"}])):
            assert geocoder.geocode_place("Ukraine")["precision"] == "country"
        with patch("geocoder.requests.get",
                   return_value=self._resp([{"lat": "47.5", "lon": "34.6",
                                            "addresstype": "state"}])):
            assert geocoder.geocode_place("Zaporizhzhia oblast")["precision"] == "region"

    def test_legacy_list_cache_entry_upgraded(self):
        geocoder._load_cache()["kyiv|ukraine"] = [50.45, 30.52]
        hit = geocoder.geocode_place("Kyiv", "Ukraine")
        assert hit == {"coords": [50.45, 30.52], "precision": "point"}

    def test_cache_prevents_second_request(self):
        with patch("geocoder.requests.get",
                   return_value=self._resp([{"lat": "1", "lon": "2"}])) as g:
            geocoder.geocode_place("Kyiv", "Ukraine")
            geocoder.geocode_place("Kyiv", "Ukraine")
        assert g.call_count == 1

    def test_misses_are_cached_too(self):
        with patch("geocoder.requests.get", return_value=self._resp([])) as g:
            assert geocoder.geocode_place("Nowhereville", "Ukraine") is None
            assert geocoder.geocode_place("Nowhereville", "Ukraine") is None
        assert g.call_count == 2  # two query variants, once each — not four

    def test_network_error_returns_none_and_is_not_cached(self):
        with patch("geocoder.requests.get", side_effect=ConnectionError("boom")) as g:
            assert geocoder.geocode_place("Kyiv", "Ukraine") is None
        assert g.call_count == 2  # bare query + one retry, no hinted fallback
        # a later attempt retries — the failure was not cached
        with patch("geocoder.requests.get",
                   return_value=self._resp([{"lat": "50.45", "lon": "30.52"}])) as g2:
            assert geocoder.geocode_place("Kyiv", "Ukraine")["coords"] == [50.45, 30.52]
        assert g2.call_count == 1

    def test_geocode_events_assigns_coords_and_precision(self):
        events = [
            {"article": {"url": "u1"}, "analysis": {"location_mentioned": "Kharkiv"}},
            {"article": {"url": "u2"}, "analysis": {"location_mentioned": None}},
            {"article": {"url": "u3"}, "analysis": None},
        ]
        with patch("geocoder.requests.get",
                   return_value=self._resp([{"lat": "49.99", "lon": "36.23",
                                            "addresstype": "city"}])):
            placed = geocoder.geocode_events(events, "Ukraine")
        assert placed == 1
        assert events[0]["coords"] == [49.99, 36.23]
        assert events[0]["loc_precision"] == "point"
        assert events[1]["coords"] is None
        assert "coords" not in events[2]
