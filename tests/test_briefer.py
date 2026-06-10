"""Tests for briefer.py — pure Python, no external calls needed."""
import pytest

import briefer


class TestGenerateBrief:

    def test_returns_string(self, sample_events):
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        assert isinstance(result, str)

    def test_output_starts_with_markdown_heading(self, sample_events):
        """Output should start with a '#' markdown heading."""
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        assert result.strip().startswith("#"), "Expected output to start with a markdown heading (#)"

    def test_output_contains_location(self, sample_events):
        """Output contains the location name passed as argument."""
        location = "TestCountry"
        result = briefer.generate_brief(sample_events, location, 30)
        assert location in result, f"Expected '{location}' to appear in the briefing"

    def test_output_contains_date_range(self, sample_events):
        """Output contains a date range indicator."""
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        # The briefing contains 'Period:' with dates formatted like "May 10 – Jun 9"
        assert "Period:" in result or "–" in result or "—" in result, \
            "Expected a date range in the briefing output"

    def test_handles_empty_event_list_without_crash(self):
        """generate_brief with no events should not raise and should return valid markdown."""
        result = briefer.generate_brief([], "TestLocation", 7)
        assert isinstance(result, str)
        assert result.strip().startswith("#")

    def test_empty_event_list_contains_location(self):
        """generate_brief with empty list still includes the location."""
        result = briefer.generate_brief([], "EmptyCity", 7)
        assert "EmptyCity" in result

    def test_empty_event_list_returns_markdown(self):
        """generate_brief with empty list still returns markdown with headers."""
        result = briefer.generate_brief([], "TestLocation", 7)
        assert "#" in result

    def test_output_contains_period_section(self, sample_events):
        """Output should include a 'Period' label showing the time window."""
        result = briefer.generate_brief(sample_events, "Ukraine", 7)
        assert "Period" in result

    def test_output_has_situation_assessment_section(self, sample_events):
        """Output should include a '## Situation Assessment' section."""
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        assert "Situation Assessment" in result

    def test_output_has_top_events_section(self, sample_events):
        """Output should include a '## Top Events' section."""
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        assert "Top Events" in result

    def test_output_has_key_entities_section(self, sample_events):
        """Output should include a '## Key Entities' section."""
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        assert "Key Entities" in result

    def test_critical_events_appear_in_output(self, sample_events):
        """Critical severity events should be visible in the briefing."""
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        assert "CRITICAL" in result

    def test_days_parameter_reflected_in_output(self, sample_events):
        """The days count should appear in the Coverage Summary."""
        result = briefer.generate_brief(sample_events, "Ukraine", 14)
        assert "14 days" in result

    def test_generated_by_footer(self, sample_events):
        """Output ends with the GeoWatch attribution footer."""
        result = briefer.generate_brief(sample_events, "Ukraine", 30)
        assert "GeoWatch" in result
