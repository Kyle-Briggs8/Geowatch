"""Tests for thermal.py (FIRMS ingestion) and fusion.correlate_fires — no live calls."""
from unittest.mock import patch, MagicMock

import pytest

import thermal
from fusion import correlate_fires
from visualizer import build_dashboard


_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
50.4500,30.5200,340.1,0.4,0.4,2026-08-05,0130,N,VIIRS,h,2.0NRT,295.0,120.5,N
50.4510,30.5210,330.0,0.4,0.4,2026-08-05,0130,N,VIIRS,n,2.0NRT,290.0,15.2,N
49.0000,32.0000,310.0,0.4,0.4,2026-08-04,1200,N,VIIRS,l,2.0NRT,285.0,50.0,D
48.5000,31.0000,305.0,0.4,0.4,2026-08-03,1200,N,VIIRS,n,2.0NRT,280.0,2.1,D
"""


def _resp(text):
    r = MagicMock(status_code=200)
    r.text = text
    r.raise_for_status.return_value = None
    return r


class TestGetFires:

    def test_missing_key_returns_empty_without_http(self, monkeypatch):
        monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
        with patch("thermal.requests.get") as g:
            assert thermal.get_fires((22, 44, 40, 52), 30) == []
        g.assert_not_called()

    def test_parses_filters_and_sorts_by_frp(self, monkeypatch):
        monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
        with patch("thermal.requests.get", return_value=_resp(_CSV)):
            fires = thermal.get_fires((22, 44, 40, 52), 5)
        # low-confidence row and sub-threshold FRP row dropped
        assert [f["frp"] for f in fires] == [120.5, 15.2]
        assert fires[0]["confidence"] == "high"
        assert fires[0]["date"] == "2026-08-05"
        assert fires[0]["daynight"] == "N"

    def test_dedupes_across_window_seams(self, monkeypatch):
        monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
        with patch("thermal.requests.get", return_value=_resp(_CSV)):
            fires = thermal.get_fires((22, 44, 40, 52), 12)  # 3 windows, same rows
        assert len(fires) == 2

    def test_http_failure_is_nonfatal(self, monkeypatch):
        monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
        with patch("thermal.requests.get", side_effect=ConnectionError("boom")):
            assert thermal.get_fires((22, 44, 40, 52), 5) == []

    def test_invalid_key_response_returns_empty(self, monkeypatch):
        monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
        with patch("thermal.requests.get", return_value=_resp("Invalid MAP_KEY.")):
            assert thermal.get_fires((22, 44, 40, 52), 5) == []

    def test_cap_at_max_fires(self, monkeypatch):
        monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
        header = _CSV.splitlines()[0]
        rows = "\n".join(
            f"50.{i:04d},30.5,340,0.4,0.4,2026-08-05,{i:04d},N,VIIRS,h,2.0NRT,295,{10 + i},N"
            for i in range(500)
        )
        with patch("thermal.requests.get", return_value=_resp(header + "\n" + rows)):
            fires = thermal.get_fires((22, 44, 40, 52), 5)
        assert len(fires) == thermal._MAX_FIRES

    def test_stratified_fill_represents_quiet_regions(self):
        # one cell packed with huge fires, another cell with a few small ones —
        # a plain FRP sort would drop the quiet cell entirely
        big   = [{"lat": 45.5, "lon": 23.5, "frp": 1000 + i, "date": "2026-08-05"}
                 for i in range(50)]
        small = [{"lat": 51.5, "lon": 39.5, "frp": 6, "date": "2026-08-05"},
                 {"lat": 51.6, "lon": 39.6, "frp": 7, "date": "2026-08-05"}]
        picked = thermal._stratified_fill(big + small, (22, 44, 40, 52), 10)
        assert any(f["frp"] < 10 for f in picked)   # quiet region survives
        assert len(picked) == 10

    def test_cross_border_events_get_mini_bbox_queries(self, monkeypatch):
        monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
        with patch("thermal.requests.get", return_value=_resp(_CSV)) as g:
            thermal.get_fires((22, 44, 40, 52), 5,
                              focus_points=[[55.75, 37.61]])  # Moscow, outside bbox
        called_bboxes = [c.args[0].split("/")[-3] for c in g.call_args_list]
        assert any(b.startswith("37.2") for b in called_bboxes)  # mini-box around Moscow

    def test_nearby_outside_points_share_one_mini_bbox(self, monkeypatch):
        monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
        with patch("thermal.requests.get", return_value=_resp(_CSV)) as g:
            thermal.get_fires((22, 44, 40, 52), 5,
                              focus_points=[[55.75, 37.61], [55.76, 37.62]])
        # 2 AOI windows + 2 windows for ONE shared mini-box (not two boxes = 6)
        assert g.call_count == 4


def _event(url, date, coords, precision="point"):
    return {"article": {"url": url, "date": date},
            "analysis": {"severity": "high"},
            "coords": coords, "loc_precision": precision}


class TestCorrelateFires:

    FIRES = [{"lat": 50.46, "lon": 30.53, "date": "2026-08-05", "frp": 120.0},
             {"lat": 50.45, "lon": 30.52, "date": "2026-08-06", "frp": 40.0},
             {"lat": 46.48, "lon": 30.74, "date": "2026-08-05", "frp": 60.0}]

    def test_matches_within_radius_and_window(self):
        events = [_event("u1", "2026-08-05", [50.45, 30.52])]
        fc = correlate_fires(events, self.FIRES)
        assert fc["u1"]["count"] == 2          # Kyiv detections on Aug 5 + 6
        assert fc["u1"]["peak_frp"] == 120.0

    def test_outside_radius_no_match(self):
        events = [_event("u1", "2026-08-05", [55.75, 37.61])]  # Moscow vs Kyiv fires
        assert correlate_fires(events, self.FIRES) == {}

    def test_outside_day_window_no_match(self):
        events = [_event("u1", "2026-08-01", [50.45, 30.52])]
        assert correlate_fires(events, self.FIRES) == {}

    def test_country_precision_excluded(self):
        events = [_event("u1", "2026-08-05", [50.45, 30.52], precision="country")]
        assert correlate_fires(events, self.FIRES) == {}

    def test_no_fires(self):
        assert correlate_fires([_event("u1", "2026-08-05", [50.45, 30.52])], []) == {}


class TestDashboardThermal:

    def test_fires_render_layer_and_badge(self, sample_events):
        events = [_event("u1", "2026-08-05", [50.45, 30.52])]
        events[0]["analysis"] = {"event_type": "conflict", "severity": "high",
                                 "entities": [], "one_line_summary": "strike",
                                 "credibility": 2}
        html = build_dashboard(events, "Ukraine", 30, fires=self.FIRES)
        assert "fire-badge" in html
        assert "thermal</span>" in html
        import re, base64
        inner = base64.b64decode(
            re.search(r"base64,([A-Za-z0-9+/=]+)", html).group(1)).decode()
        assert "Thermal anomalies (VIIRS)" in inner
        assert "VIIRS thermal detections" in inner  # count note

    FIRES = TestCorrelateFires.FIRES

    def test_no_fires_no_thermal_markup(self, sample_events):
        html = build_dashboard(sample_events, "Ukraine", 30)
        assert "fire-badge" not in html.replace(".fire-badge", "")
