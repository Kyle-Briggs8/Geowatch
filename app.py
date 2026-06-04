import os
import sys

from flask import Flask, render_template_string, request

from analyzer import analyze_article
from fetcher import get_news
from mapper import REGION_COORDS, _SEVERITY_COLOR, build_map

app = Flask(__name__)

_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GeoWatch</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0a0c10;
      color: #c8d6e5;
      font-family: 'Courier New', Courier, monospace;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 48px 16px;
    }
    header {
      text-align: center;
      margin-bottom: 40px;
    }
    h1 {
      font-size: 2.2rem;
      letter-spacing: 6px;
      color: #4af;
      text-transform: uppercase;
    }
    .subtitle {
      margin-top: 6px;
      font-size: 0.82rem;
      color: #556;
      letter-spacing: 2px;
    }
    form {
      background: #11151c;
      border: 1px solid #1e2535;
      border-radius: 8px;
      padding: 32px 36px;
      width: 100%;
      max-width: 520px;
    }
    label {
      display: block;
      font-size: 0.78rem;
      letter-spacing: 1.5px;
      color: #7a90aa;
      text-transform: uppercase;
      margin-bottom: 8px;
    }
    input[type="text"] {
      width: 100%;
      background: #0d1117;
      border: 1px solid #263040;
      border-radius: 4px;
      color: #e0eaf5;
      font-family: inherit;
      font-size: 1rem;
      padding: 10px 14px;
      outline: none;
      transition: border-color 0.2s;
    }
    input[type="text"]:focus { border-color: #4af; }
    .slider-row {
      margin-top: 24px;
    }
    .slider-label-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 8px;
    }
    .slider-val {
      color: #4af;
      font-size: 0.95rem;
    }
    input[type="range"] {
      width: 100%;
      accent-color: #4af;
    }
    .max-row {
      margin-top: 24px;
    }
    input[type="number"] {
      width: 100%;
      background: #0d1117;
      border: 1px solid #263040;
      border-radius: 4px;
      color: #e0eaf5;
      font-family: inherit;
      font-size: 1rem;
      padding: 10px 14px;
      outline: none;
    }
    button {
      margin-top: 28px;
      width: 100%;
      background: #1a3a5c;
      border: 1px solid #4af;
      border-radius: 4px;
      color: #4af;
      cursor: pointer;
      font-family: inherit;
      font-size: 0.9rem;
      letter-spacing: 2px;
      padding: 12px;
      text-transform: uppercase;
      transition: background 0.2s, color 0.2s;
    }
    button:hover { background: #4af; color: #000; }
    .known {
      margin-top: 14px;
      font-size: 0.72rem;
      color: #3a4a5a;
      text-align: center;
    }
    .error {
      margin-top: 20px;
      background: #1c0a0a;
      border: 1px solid #7a2020;
      border-radius: 6px;
      color: #e05050;
      font-size: 0.85rem;
      padding: 14px 18px;
      width: 100%;
      max-width: 520px;
    }
  </style>
  <script>
    function updateSlider(val) {
      document.getElementById('daysVal').textContent = val + ' days';
    }
  </script>
</head>
<body>
  <header>
    <h1>GeoWatch</h1>
    <div class="subtitle">open-source geospatial intelligence</div>
  </header>

  {% if error %}
  <div class="error">&#9888; {{ error }}</div>
  {% endif %}

  <form method="POST" action="/analyze">
    <label for="location">Location</label>
    <input type="text" id="location" name="location"
           placeholder="e.g. Beirut, Ukraine, Gaza"
           value="{{ location or '' }}" required autofocus>

    <div class="slider-row">
      <div class="slider-label-row">
        <label for="days" style="margin:0;">Days back</label>
        <span class="slider-val" id="daysVal">{{ days or 30 }} days</span>
      </div>
      <input type="range" id="days" name="days"
             min="7" max="90" value="{{ days or 30 }}"
             oninput="updateSlider(this.value)">
    </div>

    <div class="max-row">
      <label for="max_articles">Max articles</label>
      <input type="number" id="max_articles" name="max_articles"
             min="1" max="100" value="{{ max_articles or 20 }}">
    </div>

    <button type="submit">&#9654; Run Analysis</button>

    <div class="known">
      Pre-mapped regions: {{ regions }}
    </div>
  </form>
</body>
</html>
"""

_RESULT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GeoWatch — {{ location }}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0a0c10;
      color: #c8d6e5;
      font-family: 'Courier New', Courier, monospace;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    nav {
      background: #11151c;
      border-bottom: 1px solid #1e2535;
      display: flex;
      align-items: center;
      gap: 24px;
      padding: 12px 24px;
    }
    nav a {
      color: #4af;
      font-size: 0.8rem;
      letter-spacing: 2px;
      text-decoration: none;
      text-transform: uppercase;
    }
    nav a:hover { text-decoration: underline; }
    .title { color: #e0eaf5; font-size: 1rem; letter-spacing: 3px; }
    .stats {
      background: #11151c;
      border-bottom: 1px solid #1e2535;
      display: flex;
      flex-wrap: wrap;
      gap: 0;
      padding: 0;
    }
    .stat {
      border-right: 1px solid #1e2535;
      padding: 14px 28px;
      min-width: 150px;
    }
    .stat-label {
      color: #4a6080;
      font-size: 0.68rem;
      letter-spacing: 2px;
      text-transform: uppercase;
    }
    .stat-value {
      color: #4af;
      font-size: 1.4rem;
      margin-top: 4px;
    }
    .map-container {
      flex: 1;
      position: relative;
    }
    iframe {
      border: none;
      display: block;
      height: calc(100vh - 130px);
      width: 100%;
    }
  </style>
</head>
<body>
  <nav>
    <span class="title">GeoWatch</span>
    <a href="/">&#8592; New Query</a>
  </nav>
  <div class="stats">
    <div class="stat">
      <div class="stat-label">Location</div>
      <div class="stat-value" style="font-size:1rem;letter-spacing:2px;">{{ location }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Articles</div>
      <div class="stat-value">{{ total }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Critical</div>
      <div class="stat-value" style="color:red;">{{ critical }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">High</div>
      <div class="stat-value" style="color:orange;">{{ high }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Medium</div>
      <div class="stat-value" style="color:gold;">{{ medium }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Low</div>
      <div class="stat-value" style="color:green;">{{ low }}</div>
    </div>
  </div>
  <div class="map-container">
    <iframe srcdoc="{{ map_html | e }}"></iframe>
  </div>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    regions = ", ".join(sorted(REGION_COORDS.keys()))
    return render_template_string(_INDEX_HTML, regions=regions)


@app.route("/analyze", methods=["POST"])
def analyze():
    location = (request.form.get("location") or "").strip()
    days = int(request.form.get("days") or 30)
    max_articles = max(1, min(int(request.form.get("max_articles") or 20), 100))
    regions = ", ".join(sorted(REGION_COORDS.keys()))

    if not location:
        return render_template_string(
            _INDEX_HTML, error="Please enter a location.", regions=regions
        )

    try:
        raw_articles = get_news(location, days)
    except (EnvironmentError, RuntimeError) as exc:
        return render_template_string(
            _INDEX_HTML, error=str(exc), location=location, days=days,
            max_articles=max_articles, regions=regions
        )

    articles = raw_articles[:max_articles]

    events: list[dict] = []
    for art in articles:
        analysis = analyze_article(art)
        events.append({"article": art, "analysis": analysis})

    from mapper import REGION_COORDS as RC, _SEVERITY_COLOR as SC
    import folium
    from folium import Element
    from mapper import _LEGEND_HTML

    center = RC.get(location, (20.0, 0.0))
    zoom = 6 if location in RC else 2
    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB dark_matter")

    for event in events:
        analysis = event.get("analysis")
        article = event.get("article", {})
        if not analysis:
            continue
        severity = analysis.get("severity", "low").lower()
        color = SC.get(severity, "blue")
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

    m.get_root().html.add_child(Element(_LEGEND_HTML))
    map_html = m._repr_html_()

    from collections import Counter
    analyzed = [e for e in events if e.get("analysis")]
    sev_counts: Counter = Counter(
        e["analysis"]["severity"] for e in analyzed if e["analysis"].get("severity")
    )

    return render_template_string(
        _RESULT_HTML,
        location=location,
        total=len(analyzed),
        critical=sev_counts.get("critical", 0),
        high=sev_counts.get("high", 0),
        medium=sev_counts.get("medium", 0),
        low=sev_counts.get("low", 0),
        map_html=map_html,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
