import os
import threading
import uuid

from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template_string, request

from analyzer import analyze_article
from fetcher import get_news
from mapper import REGION_COORDS
from visualizer import build_dashboard, build_comparison_dashboard

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
    header { text-align: center; margin-bottom: 40px; }
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
    .slider-row { margin-top: 24px; }
    .slider-label-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 8px;
    }
    .slider-val { color: #4af; font-size: 0.95rem; }
    input[type="range"] { width: 100%; accent-color: #4af; }
    .mode-toggle {
      display: flex;
      margin-bottom: 20px;
      border: 1px solid #263040;
      border-radius: 3px;
      overflow: hidden;
    }
    .mode-btn {
      flex: 1;
      background: #0d1117;
      border: none;
      color: #556;
      cursor: pointer;
      font-family: inherit;
      font-size: 0.72rem;
      letter-spacing: 1.5px;
      margin-top: 0;
      padding: 7px 0;
      text-transform: uppercase;
      transition: background 0.15s, color 0.15s;
      width: auto;
    }
    .mode-btn.active { background: #1a3a5c; color: #4af; }
    .max-row { margin-top: 24px; }
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

    /* ── Loading overlay ──────────────────────────── */
    #loader {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(10, 12, 16, 0.96);
      z-index: 9999;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 22px;
    }
    .spinner {
      width: 52px;
      height: 52px;
      border: 3px solid #1e2535;
      border-top-color: #4af;
      border-radius: 50%;
      animation: spin 0.85s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    #loader-title {
      color: #4af;
      font-size: 1rem;
      letter-spacing: 4px;
      text-transform: uppercase;
    }
    #loader-sub {
      color: #3a4a5a;
      font-size: 0.72rem;
      letter-spacing: 1px;
    }
  </style>
</head>
<body>

  <!-- Loading overlay — shown by JS before form submit -->
  <div id="loader">
    <div class="spinner"></div>
    <div id="loader-title">Analyzing...</div>
    <div id="loader-sub">fetching articles &middot; running llm &middot; building dashboard</div>
  </div>

  <header>
    <h1>GeoWatch</h1>
    <div class="subtitle">open-source geospatial intelligence</div>
  </header>

  {% if error %}
  <div class="error">&#9888; {{ error }}</div>
  {% endif %}

  <form id="watchForm" method="POST" action="/analyze">
    <!-- Mode toggle -->
    <div class="mode-toggle">
      <button type="button" class="mode-btn active" id="btnSingle"
              onclick="setMode('single')">&#9632; Single</button>
      <button type="button" class="mode-btn" id="btnCompare"
              onclick="setMode('compare')">&#9707; Compare</button>
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

    <button type="button" id="submitBtn" onclick="submitWithLoader()">&#9654; Run Analysis</button>

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
        isCmp ? '▷ Run Comparison' : '▶ Run Analysis';
      document.getElementById('location2').required = isCmp;
    }

    function submitWithLoader() {
      var loc  = document.getElementById('location').value.trim();
      var loc2 = document.getElementById('location2').value.trim();
      var mode = document.getElementById('mode').value;
      var arts = document.getElementById('max_articles').value || '20';
      if (!loc) { document.getElementById('location').focus(); return; }
      if (mode === 'compare' && !loc2) { document.getElementById('location2').focus(); return; }

      var title = mode === 'compare'
        ? loc.toUpperCase() + ' vs ' + loc2.toUpperCase()
        : loc.toUpperCase();
      var sub = mode === 'compare'
        ? 'fetching both regions · running llm analysis · building comparison dashboard'
        : 'fetching up to ' + arts + ' articles · running llm analysis · building dashboard';

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


def _start_job(fn, *args) -> str:
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
  <title>GeoWatch — Analyzing {{ title }}...</title>
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
      justify-content: center;
      gap: 28px;
    }
    .spinner {
      width: 56px; height: 56px;
      border: 3px solid #1e2535;
      border-top-color: #4af;
      border-radius: 50%;
      animation: spin 0.85s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .title { color: #4af; font-size: 1rem; letter-spacing: 4px; text-transform: uppercase; }
    .sub   { color: #3a4a5a; font-size: 0.72rem; letter-spacing: 1px; }
    .elapsed { color: #556; font-size: 0.68rem; margin-top: 6px; letter-spacing: 1px; }
    .error-box {
      background: #1c0a0a; border: 1px solid #7a2020; border-radius: 6px;
      color: #e05050; font-size: 0.85rem; padding: 14px 18px;
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

def _subsample(raw: list, max_n: int) -> list:
    if len(raw) <= max_n:
        return raw
    step = len(raw) / max_n
    return [raw[int(i * step)] for i in range(max_n)]


def _do_analyze(location: str, days: int, max_articles: int) -> str:
    raw      = get_news(location, days)
    articles = _subsample(raw, max_articles)
    events   = [{"article": art, "analysis": analyze_article(art)} for art in articles]
    return build_dashboard(events, location, days)


def _do_compare(loc_a: str, loc_b: str, days: int, max_articles: int) -> str:
    def _pipeline(loc: str) -> list:
        raw = get_news(loc, days)
        return [{"article": art, "analysis": analyze_article(art)}
                for art in _subsample(raw, max_articles)]

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_a = ex.submit(_pipeline, loc_a)
        fut_b = ex.submit(_pipeline, loc_b)
        events_a = fut_a.result()
        events_b = fut_b.result()

    return build_comparison_dashboard(loc_a, events_a, loc_b, events_b, days)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    regions = ", ".join(sorted(REGION_COORDS.keys()))
    return render_template_string(_INDEX_HTML, regions=regions)


@app.route("/analyze", methods=["POST"])
def analyze():
    location     = (request.form.get("location") or "").strip()
    days         = int(request.form.get("days") or 30)
    max_articles = max(1, min(int(request.form.get("max_articles") or 5), 100))
    regions      = ", ".join(sorted(REGION_COORDS.keys()))

    if not location:
        return render_template_string(
            _INDEX_HTML, error="Please enter a location.", regions=regions
        )

    job_id = _start_job(_do_analyze, location, days, max_articles)
    return render_template_string(_WAITING_HTML, job_id=job_id, title=location)


@app.route("/compare", methods=["POST"])
def compare():
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
def job_status(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"status": "error", "error": "Job not found"}), 404
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job.get("error", "Unknown error")})
    return jsonify({"status": job["status"]})


@app.route("/result/<job_id>")
def job_result(job_id):
    job = _jobs.pop(job_id, None)
    if not job or job["status"] != "done":
        return "Result not ready or expired. Please run the analysis again.", 404
    return job["html"]


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
