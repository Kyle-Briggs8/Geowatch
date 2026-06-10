"""Shared pytest fixtures for GeoWatch tests."""
import pytest


@pytest.fixture
def sample_article():
    return {
        "title": "Military clashes reported near the border",
        "date": "2026-05-15",
        "source": "Reuters",
        "url": "https://reuters.com/article/border-clash",
        "description": "Armed forces exchanged fire along the disputed frontier.",
        "image_url": "https://reuters.com/image/border.jpg",
    }


@pytest.fixture
def sample_analysis():
    return {
        "event_type": "conflict",
        "entities": ["Armed Forces", "Border Region Command"],
        "severity": "high",
        "location_mentioned": "Northern Border",
        "one_line_summary": "Military units clashed near the disputed border region.",
    }


@pytest.fixture
def sample_event(sample_article, sample_analysis):
    return {"article": sample_article, "analysis": sample_analysis}


@pytest.fixture
def sample_events():
    """List of 10 events with mixed severities: 2 critical, 3 high, 3 medium, 2 low."""
    severities = ["critical", "critical", "high", "high", "high", "medium", "medium", "medium", "low", "low"]
    event_types = ["conflict", "terrorism", "conflict", "political", "protest", "economic", "political", "natural_disaster", "economic", "other"]

    events = []
    for i, (sev, etype) in enumerate(zip(severities, event_types)):
        article = {
            "title": f"Event {i + 1}: {etype} incident",
            "date": f"2026-05-{i + 1:02d}",
            "source": f"Source{i + 1}",
            "url": f"https://news.com/article-{i + 1}",
            "description": f"Description for event {i + 1} involving {etype}.",
            "image_url": None,
        }
        analysis = {
            "event_type": etype,
            "entities": [f"Entity{i + 1}A", f"Entity{i + 1}B"],
            "severity": sev,
            "location_mentioned": f"Location {i + 1}",
            "one_line_summary": f"Summary of event {i + 1}.",
        }
        events.append({"article": article, "analysis": analysis})
    return events
