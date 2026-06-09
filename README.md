# GeoWatch

Open-source geospatial intelligence from live news. GeoWatch fetches recent news for any world location, uses a Groq-hosted LLM to classify each story by event type, severity, and key entities, then renders the results as an interactive dashboard with maps, charts, and a scrollable event timeline.

**Live demo**: https://geowatch-ej66.onrender.com

---

## Features

- **Interactive Folium map** — severity-colored markers with cluster expansion and article popups
- **Severity escalation chart** — weekly stacked bar chart (green → red) with trend label
- **Event swimlane** — scrollable timeline by event type, click any dot for article details
- **Comparison mode** — run two locations in parallel on a single combined map with side-by-side charts and swimlanes
- **Daily brief** (`--brief`) — generates a one-page markdown intelligence report
- **Alert threshold** (`--alert-threshold`) — prints a terminal alert and injects a dashboard banner if >30% of recent events hit the threshold

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
```

- Free NewsAPI key: https://newsapi.org/register
- Free Groq key: https://console.groq.com

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
