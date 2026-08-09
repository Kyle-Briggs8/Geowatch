"""Tests for grading.py — Admiralty codes and ICD 203 confidence, pure Python."""
import pytest

import grading


class TestSourceReliability:

    def test_known_wire_service_is_b(self):
        assert grading.source_reliability("Reuters") == "B"

    def test_lookup_is_case_insensitive(self):
        assert grading.source_reliability("REUTERS") == "B"

    def test_unknown_outlet_is_f(self):
        assert grading.source_reliability("Random Blog 9000") == "F"

    def test_none_is_f(self):
        assert grading.source_reliability(None) == "F"


class TestGradeEvent:

    def test_combines_letter_and_digit(self, sample_event):
        sample_event["analysis"]["credibility"] = 2
        assert grading.grade_event(sample_event) == "B2"

    def test_missing_credibility_defaults_to_6(self, sample_event):
        assert grading.grade_event(sample_event) == "B6"

    def test_invalid_credibility_defaults_to_6(self, sample_event):
        sample_event["analysis"]["credibility"] = "banana"
        assert grading.grade_event(sample_event) == "B6"

    def test_out_of_range_credibility_defaults_to_6(self, sample_event):
        sample_event["analysis"]["credibility"] = 9
        assert grading.grade_event(sample_event) == "B6"

    def test_no_analysis_grades_f6(self):
        event = {"article": {"source": "Nowhere Gazette"}, "analysis": None}
        assert grading.grade_event(event) == "F6"


class TestDescribeGrade:

    def test_known_grade_describes_both_parts(self):
        desc = grading.describe_grade("B2")
        assert "usually reliable" in desc
        assert "probably true" in desc

    def test_malformed_grade_returns_empty(self):
        assert grading.describe_grade("XYZ") == ""


class TestAssessConfidence:

    def test_empty_events_is_low(self):
        level, rationale = grading.assess_confidence([])
        assert level == "low"
        assert "0" in rationale

    def test_few_unknown_sources_is_low(self):
        events = [
            {"article": {"source": "Blog A"}, "analysis": {"severity": "high"}},
            {"article": {"source": "Blog B"}, "analysis": {"severity": "high"}},
        ]
        level, _ = grading.assess_confidence(events)
        assert level == "low"

    def test_broad_reliable_sourcing_is_high(self):
        outlets = ["Reuters", "BBC News", "AFP", "Bloomberg", "The Guardian"]
        events = [
            {"article": {"source": outlets[i % 5]}, "analysis": {"severity": "high"}}
            for i in range(10)
        ]
        level, rationale = grading.assess_confidence(events)
        assert level == "high"
        assert "10 independently analyzed reports" in rationale

    def test_moderate_band(self):
        events = [
            {"article": {"source": s}, "analysis": {"severity": "low"}}
            for s in ["Reuters", "BBC News", "Blog A", "Blog B", "Reuters"]
        ]
        level, _ = grading.assess_confidence(events)
        assert level == "moderate"

    def test_unanalyzed_events_are_excluded(self):
        events = [{"article": {"source": "Reuters"}, "analysis": None}] * 20
        level, _ = grading.assess_confidence(events)
        assert level == "low"


class TestGradeDistribution:

    def test_counts_codes(self, sample_events):
        dist = grading.grade_distribution(sample_events)
        # conftest sources are Source1..Source10 (unknown → F) with no credibility → 6
        assert dist == {"F6": 10}
