"""Tests for entities.py — no external calls needed."""
import pytest
from entities import build_entity_cooccurrence, render_entity_graph_html


def _make_event(entities: list[str], severity: str = "medium") -> dict:
    return {
        "article": {"title": "test", "date": "2026-06-01", "source": "BBC",
                    "url": "https://x.com", "description": "", "image_url": None},
        "analysis": {"event_type": "conflict", "entities": entities,
                     "severity": severity, "location_mentioned": "X",
                     "one_line_summary": "test"},
    }


class TestBuildEntityCooccurrence:
    def test_empty_events_returns_empty(self):
        result = build_entity_cooccurrence([])
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_single_entity_article_produces_no_edges(self):
        events = [_make_event(["NATO"]), _make_event(["NATO"])]
        result = build_entity_cooccurrence(events)
        assert result["edges"] == []

    def test_two_entities_in_same_article_produce_edge(self):
        events = [_make_event(["Ukraine", "NATO"]) for _ in range(3)]
        result = build_entity_cooccurrence(events)
        edge_pairs = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("NATO", "Ukraine") in edge_pairs or ("Ukraine", "NATO") in edge_pairs

    def test_cooccurrence_count_is_correct(self):
        events = [_make_event(["Putin", "Wagner"]) for _ in range(4)]
        result = build_entity_cooccurrence(events)
        edges = {(e["source"], e["target"]): e["weight"] for e in result["edges"]}
        key = ("Putin", "Wagner") if ("Putin", "Wagner") in edges else ("Wagner", "Putin")
        assert edges[key] == 4

    def test_low_frequency_nodes_filtered_out(self):
        # "RareEntity" appears only once — should be filtered (min freq = 2)
        events = (
            [_make_event(["Ukraine", "NATO"]) for _ in range(3)]
            + [_make_event(["RareEntity"])]
        )
        result = build_entity_cooccurrence(events)
        node_names = {n["name"] for n in result["nodes"]}
        assert "RareEntity" not in node_names

    def test_low_weight_edges_filtered_out(self):
        # Pair appears only once — should be filtered (min weight = 2)
        events = [_make_event(["Alpha", "Beta"])]
        result = build_entity_cooccurrence(events)
        assert result["edges"] == []

    def test_nodes_capped_at_30(self):
        # Create 40 distinct entities each appearing 3 times
        events = []
        for i in range(40):
            events += [_make_event([f"Entity{i}"]) for _ in range(3)]
        result = build_entity_cooccurrence(events)
        assert len(result["nodes"]) <= 30

    def test_node_color_reflects_dominant_severity(self):
        # critical events → node color should be red (#ef4444)
        events = [_make_event(["Leader"], severity="critical") for _ in range(3)]
        result = build_entity_cooccurrence(events)
        node = next((n for n in result["nodes"] if n["name"] == "Leader"), None)
        assert node is not None
        assert node["color"] == "#ef4444"

    def test_node_has_required_keys(self):
        events = [_make_event(["Ukraine", "NATO"]) for _ in range(3)]
        result = build_entity_cooccurrence(events)
        for node in result["nodes"]:
            assert "name" in node
            assert "freq" in node
            assert "color" in node

    def test_edge_has_required_keys(self):
        events = [_make_event(["Ukraine", "NATO"]) for _ in range(3)]
        result = build_entity_cooccurrence(events)
        for edge in result["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "weight" in edge

    def test_events_without_analysis_are_skipped(self):
        events = [
            {"article": {}, "analysis": None},
            _make_event(["Ukraine", "NATO"]),
            _make_event(["Ukraine", "NATO"]),
        ]
        result = build_entity_cooccurrence(events)
        assert any(n["name"] == "Ukraine" for n in result["nodes"])


class TestRenderEntityGraphHtml:
    def test_returns_empty_string_for_empty_cooccurrence(self):
        assert render_entity_graph_html({"nodes": [], "edges": []}) == ""

    def test_returns_html_string(self):
        cooc = build_entity_cooccurrence(
            [_make_event(["A", "B"]) for _ in range(3)]
            + [_make_event(["A", "C"]) for _ in range(3)]
            + [_make_event(["B", "C"]) for _ in range(3)]
        )
        html = render_entity_graph_html(cooc)
        assert isinstance(html, str)
        assert "<svg" in html

    def test_html_contains_script_tag(self):
        cooc = build_entity_cooccurrence(
            [_make_event(["X", "Y"]) for _ in range(3)]
            + [_make_event(["X", "Z"]) for _ in range(3)]
            + [_make_event(["Y", "Z"]) for _ in range(3)]
        )
        html = render_entity_graph_html(cooc)
        assert "<script>" in html

    def test_optional_title_appears_in_output(self):
        cooc = build_entity_cooccurrence(
            [_make_event(["P", "Q"]) for _ in range(3)]
            + [_make_event(["P", "R"]) for _ in range(3)]
            + [_make_event(["Q", "R"]) for _ in range(3)]
        )
        html = render_entity_graph_html(cooc, title="Ukraine Network")
        assert "Ukraine Network" in html
