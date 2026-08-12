import os
import threading
import uuid
from typing import Any

from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, jsonify, render_template_string, request

from analyzer import analyze_article, analyze_posts
from demo import load_demo_events
from fetcher import get_news, rank_articles
from geocoder import geocode_events, get_bbox
from mapper import REGION_COORDS
from thermal import get_fires, has_firms_key
from visualizer import build_dashboard, build_comparison_dashboard
from xfetcher import get_x_posts, has_x_token

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
      background: #faf9f7;
      color: #1c2024;
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 56px 16px;
    }
    header { text-align: center; margin-bottom: 36px; }
    h1 {
      font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      font-size: 2.6rem;
      font-weight: 700;
      color: #16365c;
    }
    h1 em { font-style: normal; color: #2563eb; }
    .subtitle {
      margin-top: 6px;
      font-size: 0.85rem;
      color: #98a1ab;
      letter-spacing: 1px;
    }
    form {
      background: #fff;
      border: 1px solid #e7e5e0;
      border-radius: 12px;
      box-shadow: 0 1px 3px rgba(28,32,36,0.05), 0 8px 24px rgba(28,32,36,0.05);
      padding: 30px 34px;
      width: 100%;
      max-width: 520px;
    }
    label {
      display: block;
      font-size: 0.72rem;
      letter-spacing: 1px;
      color: #55606c;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 7px;
    }
    input[type="text"], input[type="number"] {
      width: 100%;
      background: #fff;
      border: 1px solid #d8d5cf;
      border-radius: 8px;
      color: #1c2024;
      font-family: inherit;
      font-size: 1rem;
      padding: 10px 14px;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    input[type="text"]:focus, input[type="number"]:focus {
      border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.12); }
    .slider-row { margin-top: 22px; }
    .slider-label-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 8px;
      align-items: baseline;
    }
    .slider-val { color: #2563eb; font-size: 0.85rem; font-weight: 700; }
    input[type="range"] { width: 100%; accent-color: #2563eb; }
    .mode-toggle {
      display: inline-flex;
      margin-bottom: 22px;
      background: #f0efec;
      border-radius: 8px;
      padding: 3px;
      gap: 3px;
    }
    .mode-btn {
      background: transparent;
      border: none;
      color: #55606c;
      cursor: pointer;
      font-family: inherit;
      font-size: 0.82rem;
      font-weight: 600;
      margin-top: 0;
      padding: 7px 20px;
      border-radius: 6px;
      transition: background 0.15s, color 0.15s;
      width: auto;
    }
    .mode-btn.active { background: #fff; color: #16365c; box-shadow: 0 1px 3px rgba(28,32,36,0.12); }
    .max-row { margin-top: 22px; }
    .demo-row {
      margin-top: 20px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .demo-row input { accent-color: #2563eb; cursor: pointer; width: 15px; height: 15px; }
    .demo-row label { margin: 0; cursor: pointer; text-transform: none; font-size: 0.85rem;
      font-weight: 500; letter-spacing: 0; color: #55606c; }
    #submitBtn {
      margin-top: 26px;
      width: 100%;
      background: #16365c;
      border: none;
      border-radius: 8px;
      color: #fff;
      cursor: pointer;
      font-family: inherit;
      font-size: 0.92rem;
      font-weight: 600;
      letter-spacing: 0.5px;
      padding: 13px;
      transition: background 0.15s, transform 0.1s;
    }
    #submitBtn:hover { background: #1d4675; transform: translateY(-1px); }
    .known {
      margin-top: 16px;
      font-size: 0.75rem;
      color: #98a1ab;
      text-align: center;
      line-height: 1.6;
    }
    .error {
      margin-top: 20px;
      background: #fef2f2;
      border: 1px solid #fecaca;
      border-left: 4px solid #dc2626;
      border-radius: 8px;
      color: #b91c1c;
      font-size: 0.85rem;
      padding: 14px 18px;
      width: 100%;
      max-width: 520px;
    }

    /* Loading overlay */
    #loader {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(250, 249, 247, 0.96);
      z-index: 9999;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 22px;
    }
    .spinner {
      width: 52px;
      height: 52px;
      border: 3px solid #e7e5e0;
      border-top-color: #2563eb;
      border-radius: 50%;
      animation: spin 0.85s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    #loader-title {
      font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      color: #16365c;
      font-size: 1.3rem;
      font-weight: 700;
    }
    #loader-sub {
      color: #98a1ab;
      font-size: 0.78rem;
    }
  </style>
</head>
<body>

  <!-- Loading overlay: shown by JS before form submit -->
  <div id="loader">
    <div class="spinner"></div>
    <div id="loader-title">Analyzing...</div>
    <div id="loader-sub">fetching articles &middot; running llm &middot; building dashboard</div>
  </div>

  <header>
    <h1>Geo<em>Watch</em></h1>
    <div class="subtitle">open-source geospatial intelligence</div>
  </header>

  {% if error %}
  <div class="error">&#9888; {{ error }}</div>
  {% endif %}

  <form id="watchForm" method="POST" action="/analyze">
    <!-- Mode toggle -->
    <div class="mode-toggle">
      <button type="button" class="mode-btn active" id="btnSingle"
              onclick="setMode('single')">Single</button>
      <button type="button" class="mode-btn" id="btnCompare"
              onclick="setMode('compare')">Compare</button>
    </div>
    <input type="hidden" id="mode" name="mode" value="single">

    <label for="location">Location</label>
    <input type="text" id="location" name="location"
           placeholder="e.g. Beirut, Ukraine, Gaza"
           value="{{ location or '' }}" required autofocus>

    <div id="loc2row" style="display:none;margin-top:16px;">
      <label for="location2">Second Location</label>
      <input type="text" id="location2" name="location2"
             placeholder="e.g. Taiwan, Gaza, Yemen"
             value="{{ location2 or '' }}">
    </div>

    <div class="slider-row">
      <div class="slider-label-row">
        <label for="days" style="margin:0;">Days back</label>
        <span class="slider-val" id="daysVal">{{ days or 30 }} days</span>
      </div>
      <input type="range" id="days" name="days"
             min="7" max="90" value="{{ days or 30 }}"
             oninput="document.getElementById('daysVal').textContent=this.value+' days'">
    </div>

    <div class="max-row">
      <label for="max_articles">Max articles</label>
      <input type="number" id="max_articles" name="max_articles"
             min="1" max="100" value="{{ max_articles or 5 }}">
    </div>

    <div class="demo-row">
      <input type="checkbox" id="demo" name="demo" value="1">
      <label for="demo">Cached demo data &mdash; no live API calls</label>
    </div>

    <div class="demo-row">
      <input type="checkbox" id="include_x" name="include_x" value="1">
      <label for="include_x">Include X (social) data &mdash; adds an X Pulse tab</label>
    </div>

    <button type="button" id="submitBtn" onclick="submitWithLoader()">Run Analysis</button>

    <div class="known">Pre-mapped regions: {{ regions }}</div>
  </form>

  <script>
    function setMode(m) {
      document.getElementById('mode').value = m;
      var isCmp = m === 'compare';
      document.getElementById('loc2row').style.display  = isCmp ? 'block' : 'none';
      document.getElementById('btnSingle').classList.toggle('active', !isCmp);
      document.getElementById('btnCompare').classList.toggle('active',  isCmp);
      document.getElementById('submitBtn').textContent =
        isCmp ? 'Run Comparison' : 'Run Analysis';
      document.getElementById('location2').required = isCmp;
    }

    function submitWithLoader() {
      var loc  = document.getElementById('location').value.trim();
      var loc2 = document.getElementById('location2').value.trim();
      var mode = document.getElementById('mode').value;
      var arts = document.getElementById('max_articles').value || '20';
      if (!loc) { document.getElementById('location').focus(); return; }
      if (mode === 'compare' && !loc2) { document.getElementById('location2').focus(); return; }

      var title = mode === 'compare' ? loc + ' vs ' + loc2 : loc;
      var sub = mode === 'compare'
        ? 'fetching both regions \u00b7 running llm analysis \u00b7 building comparison dashboard'
        : 'fetching up to ' + arts + ' articles \u00b7 running llm analysis \u00b7 building dashboard';

      document.getElementById('loader-title').textContent = title;
      document.getElementById('loader-sub').textContent   = sub;
      document.getElementById('loader').style.display     = 'flex';
      document.getElementById('watchForm').action = mode === 'compare' ? '/compare' : '/analyze';
      setTimeout(function() { document.getElementById('watchForm').submit(); }, 60);
    }
  </script>
</body>
</html>
"""


# ── Background job store ──────────────────────────────────────────────────────
# Each job: {"status": "running"|"done"|"error", "html": str, "error": str}
_jobs: dict[str, dict] = {}


def _start_job(fn: Any, *args: Any) -> str:
    """Spawn fn(*args) in a daemon thread. Returns job_id immediately."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}

    def _run():
        try:
            _jobs[job_id]["html"]   = fn(*args)
            _jobs[job_id]["status"] = "done"
        except Exception as exc:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"]  = str(exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return job_id


_WAITING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>GeoWatch &mdash; Analyzing {{ title }}...</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #faf9f7;
      color: #1c2024;
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 26px;
    }
    .spinner {
      width: 56px; height: 56px;
      border: 3px solid #e7e5e0;
      border-top-color: #2563eb;
      border-radius: 50%;
      animation: spin 0.85s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .title {
      font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      color: #16365c; font-size: 1.4rem; font-weight: 700; text-align: center;
    }
    .sub   { color: #98a1ab; font-size: 0.78rem; text-align: center; }
    .elapsed { color: #98a1ab; font-size: 0.72rem; margin-top: 6px; text-align: center; }
    .error-box {
      background: #fef2f2; border: 1px solid #fecaca; border-left: 4px solid #dc2626;
      border-radius: 8px; color: #b91c1c; font-size: 0.85rem; padding: 14px 18px;
      max-width: 480px; text-align: center;
    }
  </style>
</head>
<body>
  <div class="spinner" id="spinner"></div>
  <div>
    <div class="title" id="msg">Analyzing {{ title }}</div>
    <div class="sub">fetching articles &middot; running llm &middot; building dashboard</div>
    <div class="elapsed" id="elapsed"></div>
  </div>
  <script>
    var start = Date.now();
    var jobId = "{{ job_id }}";

    var timer = setInterval(function() {
      var s = Math.round((Date.now() - start) / 1000);
      document.getElementById('elapsed').textContent = s + 's elapsed';
    }, 1000);

    function poll() {
      fetch('/status/' + jobId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (data.status === 'done') {
            clearInterval(timer);
            window.location.href = '/result/' + jobId;
          } else if (data.status === 'error') {
            clearInterval(timer);
            document.getElementById('spinner').style.display = 'none';
            document.getElementById('msg').textContent = 'Analysis failed';
            var el = document.createElement('div');
            el.className = 'error-box';
            el.textContent = data.error || 'Unknown error';
            document.body.appendChild(el);
          } else {
            setTimeout(poll, 2000);
          }
        })
        .catch(function() { setTimeout(poll, 3000); });
    }
    setTimeout(poll, 2000);
  </script>
</body>
</html>"""


# ── Pipeline helpers ──────────────────────────────────────────────────────────

def _do_analyze(location: str, days: int, max_articles: int, demo: bool = False,
                include_x: bool = False) -> str:
    """Fetch, analyze, and render a single-location dashboard. Returns HTML string.

    With demo=True, renders from the cached dataset in demo_data/ — no API calls.
    With include_x=True, adds an X Pulse tab (live Apify fetch, or cached posts in demo).
    """
    if demo:
        payload  = load_demo_events(location)
        x_events = payload.get("x_events") if include_x else None
        x_status = "ok" if x_events is not None else ("error" if include_x else None)
        return build_dashboard(payload["events"], location, payload.get("days", days),
                               x_events=x_events, x_status=x_status,
                               fires=payload.get("fires"))

    x_fut = None
    x_executor = None
    x_status = None
    if include_x:
        if not has_x_token():
            x_status = "no_token"
        else:
            x_executor = ThreadPoolExecutor(max_workers=1)
            x_fut = x_executor.submit(get_x_posts, location, days)

    raw    = get_news(location, days)
    ranked = rank_articles(raw)
    events: list = []
    for art in ranked[:max_articles * 2]:
        if len(events) >= max_articles:
            break
        a = analyze_article(art, location)
        if a and a.get("relevant") is False:
            continue
        events.append({"article": art, "analysis": a})
    events.sort(key=lambda e: e["article"].get("date") or "")
    geocode_events(events, location)

    fires = None
    if has_firms_key():
        bbox = get_bbox(location)
        if bbox:
            focus = [e["coords"] for e in events
                     if e.get("coords") and e.get("loc_precision") in ("point", "region")]
            fires = get_fires(bbox, days, focus_points=focus) or None

    x_events = None
    if x_fut is not None:
        posts, _ = x_fut.result()
        x_executor.shutdown(wait=False)
        if posts:
            analyses = analyze_posts(posts, location)
            x_events = [{"post": p, "analysis": a}
                        for p, a in zip(posts, analyses) if a]
            x_status = "ok"
        else:
            x_status = "error"

    return build_dashboard(events, location, days,
                           x_events=x_events, x_status=x_status, fires=fires)


def _do_compare(loc_a: str, loc_b: str, days: int, max_articles: int) -> str:
    """Fetch, analyze, and render a two-location comparison dashboard. Returns HTML string."""
    def _pipeline(loc: str) -> list:
        raw = get_news(loc, days)
        ranked = rank_articles(raw)
        evts: list = []
        for art in ranked[:max_articles * 2]:
            if len(evts) >= max_articles:
                break
            a = analyze_article(art, loc)
            if a and a.get("relevant") is False:
                continue
            evts.append({"article": art, "analysis": a})
        evts.sort(key=lambda e: e["article"].get("date") or "")
        geocode_events(evts, loc)
        return evts

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_a = ex.submit(_pipeline, loc_a)
        fut_b = ex.submit(_pipeline, loc_b)
        events_a = fut_a.result()
        events_b = fut_b.result()

    return build_comparison_dashboard(loc_a, events_a, loc_b, events_b, days)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index() -> str:
    """Render the GeoWatch home page."""
    regions = ", ".join(sorted(REGION_COORDS.keys()))
    return render_template_string(_INDEX_HTML, regions=regions)


@app.route("/analyze", methods=["POST"])
def analyze() -> str:
    """Start a single-location analysis job and return the waiting page."""
    location     = (request.form.get("location") or "").strip()
    days         = int(request.form.get("days") or 30)
    max_articles = max(1, min(int(request.form.get("max_articles") or 5), 100))
    demo         = request.form.get("demo") == "1"
    include_x    = request.form.get("include_x") == "1"
    regions      = ", ".join(sorted(REGION_COORDS.keys()))

    if not location:
        return render_template_string(
            _INDEX_HTML, error="Please enter a location.", regions=regions
        )

    job_id = _start_job(_do_analyze, location, days, max_articles, demo, include_x)
    return render_template_string(_WAITING_HTML, job_id=job_id, title=location)


@app.route("/compare", methods=["POST"])
def compare() -> str:
    """Start a two-location comparison job and return the waiting page."""
    loc_a        = (request.form.get("location")  or "").strip()
    loc_b        = (request.form.get("location2") or "").strip()
    days         = int(request.form.get("days") or 30)
    max_articles = max(1, min(int(request.form.get("max_articles") or 5), 100))
    regions      = ", ".join(sorted(REGION_COORDS.keys()))

    if not loc_a or not loc_b:
        return render_template_string(
            _INDEX_HTML, error="Please enter both locations for comparison.", regions=regions
        )

    job_id = _start_job(_do_compare, loc_a, loc_b, days, max_articles)
    return render_template_string(_WAITING_HTML, job_id=job_id,
                                  title=f"{loc_a} vs {loc_b}")


@app.route("/status/<job_id>")
def job_status(job_id: str) -> Response:
    """Return JSON job status for polling: {status, error?}."""
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"status": "error", "error": "Job not found"}), 404
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job.get("error", "Unknown error")})
    return jsonify({"status": job["status"]})


@app.route("/result/<job_id>")
def job_result(job_id: str) -> str | tuple[str, int]:
    """Return the completed dashboard HTML, or a 404 error string if not ready."""
    job = _jobs.pop(job_id, None)
    if not job or job["status"] != "done":
        return "Result not ready or expired. Please run the analysis again.", 404
    return job["html"]


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
