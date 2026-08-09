import folium
from folium import Element

from grading import describe_grade, grade_event

REGION_COORDS: dict[str, tuple[float, float]] = {
    "Syria": (34.8021, 38.9968),
    "Ukraine": (48.3794, 31.1656),
    "Beirut": (33.8938, 35.5018),
    "Lebanon": (33.8547, 35.8623),
    "Gaza": (31.3547, 34.3088),
    "Somalia": (5.1521, 46.1996),
    "Yemen": (15.5527, 48.5164),
    "Iran": (32.4279, 53.6880),
    "Iraq": (33.2232, 43.6793),
    "Sudan": (12.8628, 30.2176),
    "Afghanistan": (33.9391, 67.7100),
    "Libya": (26.3351, 17.2283),
    "Pakistan": (30.3753, 69.3451),
    "Myanmar": (21.9162, 95.9560),
    "Ethiopia": (9.1450, 40.4897),
}

_SEVERITY_COLOR = {
    "low": "#1a7f37",
    "medium": "#d4a72c",
    "high": "#ea7317",
    "critical": "#dc2626",
}

_LEGEND_HTML = """
<div style="
    position: fixed;
    bottom: 24px;
    left: 24px;
    z-index: 1000;
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid #e7e5e0;
    border-radius: 8px;
    padding: 10px 14px;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 12px;
    color: #55606c;
    box-shadow: 0 2px 8px rgba(28,32,36,0.1);
">
  <b style="color:#16365c;font-size:10.5px;letter-spacing:1.5px;">SEVERITY</b><br>
  <span style="color:#dc2626;">&#9679;</span>&nbsp; Critical<br>
  <span style="color:#ea7317;">&#9679;</span>&nbsp; High<br>
  <span style="color:#d4a72c;">&#9679;</span>&nbsp; Medium<br>
  <span style="color:#1a7f37;">&#9679;</span>&nbsp; Low
</div>
"""


def build_map(events: list[dict], location: str, output: str = "map.html") -> int:
    """Build a Folium map of analyzed events and save it to disk.

    Each event dict must have keys: article (the original article dict) and
    analysis (the dict returned by analyzer.analyze_article, or None).
    """
    center = REGION_COORDS.get(location, (20.0, 0.0))
    zoom = 6 if location in REGION_COORDS else 2

    m = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles="CartoDB positron",
    )

    plotted = 0
    for event in events:
        analysis = event.get("analysis")
        article = event.get("article", {})
        if not analysis:
            continue

        severity = analysis.get("severity", "low").lower()
        color = _SEVERITY_COLOR.get(severity, "blue")

        entities = analysis.get("entities") or []
        entity_str = ", ".join(entities) if entities else "—"

        popup_html = f"""
        <div style="font-family:monospace;font-size:12px;max-width:320px;line-height:1.6;">
          <b>{analysis.get('one_line_summary', '')}</b><br><br>
          <b>Type:</b> {analysis.get('event_type', '—')}<br>
          <b>Severity:</b> <span style="color:{color};font-weight:bold;">{severity.upper()}</span><br>
          <b>Entities:</b> {entity_str}<br>
          <b>Source:</b> {article.get('source', '—')}<br>
          <b>Grade:</b> {grade_event(event)} <span style="color:#888;">({describe_grade(grade_event(event))})</span><br>
          <b>Date:</b> {article.get('date', '—')}<br><br>
          <a href="{article.get('url', '#')}" target="_blank"
             style="color:#4af;text-decoration:none;">&#x1F517; Read article</a>
        </div>
        """

        folium.CircleMarker(
            location=center,
            radius=8,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=analysis.get("one_line_summary", article.get("title", "")),
        ).add_to(m)
        plotted += 1

    m.get_root().html.add_child(Element(_LEGEND_HTML))
    m.save(output)
    return plotted
