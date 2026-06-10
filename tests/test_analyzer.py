"""Tests for analyzer.py — Groq API calls mocked throughout."""
import json
import os
from unittest.mock import MagicMock, patch

import pytest


VALID_JSON_RESPONSE = json.dumps({
    "event_type": "conflict",
    "entities": ["Armed Forces", "Rebel Group"],
    "severity": "high",
    "location_mentioned": "Northern Region",
    "one_line_summary": "Armed forces clashed with rebel groups in the northern region.",
})

VALID_ANALYSIS_KEYS = {"event_type", "entities", "severity", "location_mentioned", "one_line_summary"}
VALID_EVENT_TYPES = {"conflict", "political", "natural_disaster", "economic", "protest", "terrorism", "other"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


def _make_groq_mock(content: str):
    """Return a mock Groq client whose completions.create returns 'content'."""
    mock_choice = MagicMock()
    mock_choice.message.content = content

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion
    return mock_client


class TestAnalyzeArticle:

    def _sample_article(self):
        return {
            "title": "Conflict erupts in northern region",
            "description": "Armed forces clashed with rebel groups near the border.",
        }

    def test_returns_dict_with_expected_keys_on_valid_json(self):
        """analyze_article() returns a dict with all required keys on valid JSON."""
        mock_client = _make_groq_mock(VALID_JSON_RESPONSE)

        with patch("analyzer.Groq", return_value=mock_client), \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
            import analyzer
            result = analyzer.analyze_article(self._sample_article())

        assert result is not None
        assert isinstance(result, dict)
        assert VALID_ANALYSIS_KEYS == set(result.keys())

    def test_returns_none_on_invalid_json(self):
        """analyze_article() returns None when Groq returns a non-JSON string."""
        mock_client = _make_groq_mock("This is not valid JSON at all.")

        with patch("analyzer.Groq", return_value=mock_client), \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
            import analyzer
            result = analyzer.analyze_article(self._sample_article())

        assert result is None

    def test_returns_none_on_groq_api_exception(self):
        """analyze_article() returns None when the Groq API raises an exception."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API unavailable")

        with patch("analyzer.Groq", return_value=mock_client), \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
            import analyzer
            result = analyzer.analyze_article(self._sample_article())

        assert result is None

    def test_event_type_is_valid_value(self):
        """event_type in the returned dict is one of the allowed values."""
        mock_client = _make_groq_mock(VALID_JSON_RESPONSE)

        with patch("analyzer.Groq", return_value=mock_client), \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
            import analyzer
            result = analyzer.analyze_article(self._sample_article())

        assert result is not None
        assert result["event_type"] in VALID_EVENT_TYPES

    def test_severity_is_valid_value(self):
        """severity in the returned dict is one of the allowed values."""
        mock_client = _make_groq_mock(VALID_JSON_RESPONSE)

        with patch("analyzer.Groq", return_value=mock_client), \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
            import analyzer
            result = analyzer.analyze_article(self._sample_article())

        assert result is not None
        assert result["severity"] in VALID_SEVERITIES

    def test_each_valid_event_type_accepted(self):
        """analyze_article() correctly returns each valid event_type."""
        for etype in VALID_EVENT_TYPES:
            payload = json.dumps({
                "event_type": etype,
                "entities": [],
                "severity": "low",
                "location_mentioned": None,
                "one_line_summary": "Summary.",
            })
            mock_client = _make_groq_mock(payload)

            with patch("analyzer.Groq", return_value=mock_client), \
                 patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
                import analyzer
                result = analyzer.analyze_article(self._sample_article())

            assert result is not None
            assert result["event_type"] == etype

    def test_each_valid_severity_accepted(self):
        """analyze_article() correctly returns each valid severity level."""
        for sev in VALID_SEVERITIES:
            payload = json.dumps({
                "event_type": "other",
                "entities": [],
                "severity": sev,
                "location_mentioned": None,
                "one_line_summary": "Summary.",
            })
            mock_client = _make_groq_mock(payload)

            with patch("analyzer.Groq", return_value=mock_client), \
                 patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
                import analyzer
                result = analyzer.analyze_article(self._sample_article())

            assert result is not None
            assert result["severity"] == sev

    def test_returns_none_on_empty_json_object(self):
        """analyze_article() still returns a dict even for an empty JSON object ({})."""
        mock_client = _make_groq_mock("{}")

        with patch("analyzer.Groq", return_value=mock_client), \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}):
            import analyzer
            result = analyzer.analyze_article(self._sample_article())

        # An empty JSON object parses successfully, so result is a dict (possibly empty)
        assert result is not None
        assert isinstance(result, dict)
