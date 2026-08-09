"""Tests for demo.py — cache round-trip using a temp directory."""
import pytest

import demo


@pytest.fixture(autouse=True)
def _tmp_demo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEMO_DIR", str(tmp_path))


class TestDemoCache:

    def test_round_trip(self, sample_events):
        demo.save_demo_events("Ukraine", 30, sample_events)
        payload = demo.load_demo_events("Ukraine")
        assert payload["location"] == "Ukraine"
        assert payload["days"] == 30
        assert payload["events"] == sample_events

    def test_slug_normalizes_case_and_spaces(self, sample_events):
        demo.save_demo_events("South Sudan", 14, sample_events)
        assert demo.has_demo("south sudan")
        assert demo.load_demo_events("SOUTH SUDAN")["days"] == 14

    def test_missing_location_raises_with_hint(self):
        with pytest.raises(FileNotFoundError, match="--save-demo"):
            demo.load_demo_events("Atlantis")

    def test_has_demo_false_when_absent(self):
        assert not demo.has_demo("Atlantis")

    def test_list_demo_locations(self, sample_events):
        assert demo.list_demo_locations() == []
        demo.save_demo_events("Ukraine", 30, sample_events)
        assert demo.list_demo_locations() == ["ukraine"]
