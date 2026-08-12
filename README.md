# GeoWatch

Open-source geospatial intelligence from live news. GeoWatch fetches recent news for any world location, uses a Groq-hosted LLM to classify each story by event type, severity, and key entities, then renders the results as an interactive dashboard with maps, charts, and a scrollable event timeline.

**Live demo**: https://geowatch-ej66.onrender.com

---

## Features

- **Interactive Folium map** — every event geocoded to real coordinates (Nominatim, from the LLM-extracted location per article) with severity-colored markers, cluster expansion, and article popups
- **Cross-INT corroboration** — news events corroborated by independent X posts naming the same entities within 48h get a clickable badge that expands the matching posts inline; social posts that preceded the news reporting are flagged as early signals
- **Satellite thermal layer (VIIRS/FIRMS)** — NASA FIRMS active-fire detections over the AOI as a toggleable map overlay (filtered to confident, high-radiative-power signal); news events with detections within 20km/±1 day get a 🔥 tri-INT badge — news + social + remote sensing corroborating each other
- **Interactive event timeline** — weekly severity-stacked bars; click a week to expand its daily breakdown and filter the chronological event log
- **Situation at a glance** — headline stats (events, high/critical count, outlets, best source grade) and event-type breakdown
- **Comparison mode** — run two locations in parallel on a single combined map with side-by-side charts and event logs
- **Daily brief** (`--brief`) — generates a one-page markdown intelligence report
- **Alert threshold** (`--alert-threshold`) — prints a terminal alert and injects a dashboard banner if >30% of recent events hit the threshold
- **IC tradecraft grading** — every event carries a NATO Admiralty System code (source reliability A–F from a curated outlet table, information credibility 1–6 assessed per-article by the LLM); briefings and the dashboard assessment strip use ICD 203 estimative language, with analytic confidence derived from breadth and quality of sourcing
- **X Pulse** (`--x` / web checkbox) — social-signal tab alongside the news analysis: X/Twitter posts fetched via an Apify actor, triaged by a single batched LLM call (relevance, severity, type, credibility), shown as a posts-per-day tempo strip and a graded post feed. Social posts are deliberately kept out of the news event log and graded F on the Admiralty reliability scale — leads, not confirmation
- **Demo mode** (`--demo` / web checkbox) — renders instantly from a cached dataset in `demo_data/`, no API calls; capture a dataset from any live run with `--save-demo`

---

## Installation

```bash
git clone https://github.com/Kyle-Briggs8/Geowatch.git
cd Geowatch
pip install -r requirements.txt
```

Create a `.env` file with your API keys:

```
NEWSAPI_KEY=your_key_here
GROQ_API_KEY=your_key_here
APIFY_TOKEN=your_apify_token_here     # optional — enables the X Pulse tab
FIRMS_MAP_KEY=your_firms_map_key_here # optional — enables the satellite thermal layer
```

- Free NewsAPI key: https://newsapi.org/register
- Free Groq key: https://console.groq.com
- Free Apify token: https://apify.com (no card; the free plan's $5/month credit covers ~150 X fetches at $0.25 per 1,000 posts via the [pay-per-result tweet scraper](https://apify.com/kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest))
- Free NASA FIRMS key: https://firms.modaps.eosdis.nasa.gov/api/map_key/ (email only; 5,000 requests per 10 minutes)

---

## Web UI

```bash
python app.py
# → open http://localhost:5000
```

Select **Single** or **Compare** mode, enter a location, adjust the days slider and article count, then click **Run Analysis**. A loading page shows elapsed time while the pipeline runs, then redirects to the dashboard automatically.

---

## CLI Usage

```bash
# Single location — last 30 days
python main.py --location "Ukraine"

# Custom window and article count
python main.py --location "Gaza" --days 7 --max-articles 30

# Compare two locations
python main.py --compare "Ukraine" "Taiwan" --days 14

# Generate a markdown intelligence brief alongside the dashboard
python main.py --location "Syria" --days 7 --brief

# Alert if >30% of last-7-day events are HIGH or above
python main.py --location "Yemen" --days 14 --alert-threshold high

# Include the X Pulse social-signal tab (requires APIFY_TOKEN)
python main.py --location "Ukraine" --days 30 --x

# Capture a live run as a reusable demo dataset, then replay it offline
python main.py --location "Ukraine" --days 30 --x --save-demo
python main.py --location "Ukraine" --demo --x --brief
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--location` | — | Location to query (mutually exclusive with `--compare`) |
| `--compare LOC_A LOC_B` | — | Two locations to compare in parallel |
| `--days` | 30 | Days back to search (max 90) |
| `--max-articles` | 20 | Articles to analyze per location (max 100) |
| `--output` | auto | Output HTML filename |
| `--brief` | off | Write a markdown intelligence briefing |
| `--alert-threshold` | off | `low` / `medium` / `high` / `critical` |
| `--x` | off | Add the X Pulse social-signal tab (requires `APIFY_TOKEN`) |
| `--demo` | off | Render from the cached dataset in `demo_data/` — no API calls |
| `--save-demo` | off | Save this run's analyzed events (and X posts with `--x`) to `demo_data/` |

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| News data | NewsAPI + GDELT (dual-source, parallel fetch) |
| LLM | Groq API — `llama-3.3-70b-versatile` |
| Maps | Folium (Leaflet.js) |
| Charts | Matplotlib |
| Web UI | Flask + background thread polling |
| Deployment | Render (gunicorn) |
| Env | python-dotenv |

---

## Deployment

The app is configured for one-click deploy on [Render](https://render.com) via `render.yaml`.

Set the following environment variables in the Render dashboard:

| Key | Description |
|---|---|
| `NEWSAPI_KEY` | From https://newsapi.org/register |
| `GROQ_API_KEY` | From https://console.groq.com |

The analysis pipeline runs in a background thread so long-running requests never hit gunicorn's timeout.
