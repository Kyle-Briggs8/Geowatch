"""Tests for the X-Mode pipeline: batched classification, grading, demo cache, dashboard."""
import json
from unittest.mock import patch, MagicMock

import pytest

import analyzer
import demo
import grading
from visualizer import build_dashboard, _fmt_count


def _groq_response(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


def _mock_client(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value = _groq_response(content)
    return client


def _posts(n: int) -> list[dict]:
    return [
        {"id": str(i), "text": f"post {i}", "date": "2026-08-01",
         "author": f"@u{i}", "followers": 100}
        for i in range(n)
    ]


class TestAnalyzePosts:

    def test_empty_input_no_client(self):
        assert analyzer.analyze_posts([], "Ukraine") == []

    def test_clean_array_aligned_by_index(self):
        content = json.dumps([
            {"index": 0, "relevant": True, "event_type": "conflict",
             "severity": "high", "credibility": 2},
            {"index": 1, "relevant": False},
        ])
        with patch("analyzer._get_client", return_value=_mock_client(content)):
            results = analyzer.analyze_posts(_posts(2), "Ukraine")
        assert results[0] == {"event_type": "conflict", "severity": "high", "credibility": 2}
        assert results[1] is None

    def test_fenced_json_is_stripped(self):
        content = "```json\n" + json.dumps(
            [{"index": 0, "relevant": True, "event_type": "political",
              "severity": "low", "credibility": 4}]) + "\n```"
        with patch("analyzer._get_client", return_value=_mock_client(content)):
            results = analyzer.analyze_posts(_posts(1), "Ukraine")
        assert results[0]["event_type"] == "political"

    def test_garbage_falls_back_to_default_analysis(self):
        with patch("analyzer._get_client", return_value=_mock_client("not json at all")):
            results = analyzer.analyze_posts(_posts(3), "Ukraine")
        assert all(r == {"event_type": "other", "severity": "low", "credibility": 6}
                   for r in results)

    def test_out_of_range_index_ignored(self):
        content = json.dumps([
            {"index": 0, "relevant": True, "event_type": "conflict",
             "severity": "high", "credibility": 2},
            {"index": 99, "relevant": True, "event_type": "conflict",
             "severity": "high", "credibility": 2},
        ])
        with patch("analyzer._get_client", return_value=_mock_client(content)):
            results = analyzer.analyze_posts(_posts(2), "Ukraine")
        assert results[0] is not None
        assert results[1] is None

    def test_chunking_makes_multiple_calls(self):
        content = json.dumps([
            {"index": i, "relevant": True, "event_type": "other",
             "severity": "low", "credibility": 5}
            for i in range(analyzer._POST_BATCH_SIZE)
        ])
        client = _mock_client(content)
        with patch("analyzer._get_client", return_value=client), \
             patch("analyzer.time.sleep"):
            results = analyzer.analyze_posts(_posts(analyzer._POST_BATCH_SIZE + 5), "Ukraine")
        assert client.chat.completions.create.call_count == 2
        assert len(results) == analyzer._POST_BATCH_SIZE + 5


class TestGradePost:

    def test_reliability_is_always_f(self):
        assert grading.grade_post({"analysis": {"credibility": 2}}) == "F2"

    def test_missing_or_invalid_credibility_is_6(self):
        assert grading.grade_post({"analysis": {}}) == "F6"
        assert grading.grade_post({"analysis": {"credibility": "n/a"}}) == "F6"
        assert grading.grade_post({}) == "F6"


class TestDemoXEvents:

    @pytest.fixture(autouse=True)
    def _tmp_demo_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(demo, "DEMO_DIR", str(tmp_path))

    def test_round_trip_with_x_events(self, sample_events, sample_x_events):
        demo.save_demo_events("Ukraine", 30, sample_events, x_events=sample_x_events)
        payload = demo.load_demo_events("Ukraine")
        assert payload["x_events"] == sample_x_events

    def test_payload_without_x_events_has_no_key(self, sample_events):
        demo.save_demo_events("Ukraine", 30, sample_events)
        payload = demo.load_demo_events("Ukraine")
        assert "x_events" not in payload
        assert payload.get("x_events") is None


class TestDashboardXTab:

    def test_no_x_args_means_no_tab_markup(self, sample_events):
        html = build_dashboard(sample_events, "Ukraine", 30)
        assert '<nav class="tabs">' not in html
        assert "pane-xpulse" not in html
        assert ">X Pulse<" not in html

    def test_x_events_render_tabs_and_feed(self, sample_events, sample_x_events):
        html = build_dashboard(sample_events, "Ukraine", 30,
                               x_events=sample_x_events, x_status="ok")
        assert 'class="tabs"' in html
        assert "pane-xpulse" in html
        assert "Social Tempo" in html
        assert "Post Feed" in html
        assert "@osint_user1" in html
        assert "F3" in html  # graded post badge
        # news pane untouched
        assert 'id="pane-news" class="tabpane open"' in html
        assert 'id="feed"' in html

    def test_no_token_status_renders_hint(self, sample_events):
        html = build_dashboard(sample_events, "Ukraine", 30,
                               x_events=None, x_status="no_token")
        assert "APIFY_TOKEN" in html

    def test_error_status_renders_notice(self, sample_events):
        html = build_dashboard(sample_events, "Ukraine", 30,
                               x_events=None, x_status="error")
        assert "unavailable" in html

    def test_empty_x_events_renders_empty_state(self, sample_events):
        html = build_dashboard(sample_events, "Ukraine", 30,
                               x_events=[], x_status="ok")
        assert "No relevant X posts" in html


class TestFmtCount:

    @pytest.mark.parametrize("n,expected", [
        (0, "0"), (999, "999"), (1000, "1K"), (1200, "1.2K"),
        (52000, "52K"), (1_000_000, "1M"), (2_400_000, "2.4M"),
    ])
    def test_formats(self, n, expected):
        assert _fmt_count(n) == expected
