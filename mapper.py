import folium
from folium import Element

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
    "low": "green",
    "medium": "yellow",
    "high": "orange",
    "critical": "red",
}

_LEGEND_HTML = """
<div style="
    position: fixed;
    bottom: 30px;
    left: 30px;
    z-index: 1000;
    background: rgba(15, 15, 20, 0.88);
    border: 1px solid #444;
    border-radius: 6px;
    padding: 12px 16px;
    font-family: monospace;
    font-size: 13px;
    color: #e0e0e0;
    min-width: 160px;
">
  <b style="color:#fff;letter-spacing:1px;">SEVERITY</b><br><br>
  <span style="color:red;">&#9679;</span>&nbsp; Critical<br>
  <span style="color:orange;">&#9679;</span>&nbsp; High<br>
  <span style="color:gold;">&#9679;</span>&nbsp; Medium<br>
  <span style="color:green;">&#9679;</span>&nbsp; Low
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
        tiles="CartoDB dark_matter",
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
