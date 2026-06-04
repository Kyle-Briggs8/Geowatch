# GeoWatch

GeoWatch is a CLI and web tool for open-source geospatial intelligence. It fetches recent news for any world location, uses a Groq-hosted LLM to classify each story by event type, involved entities, and severity, then renders the results as an interactive map you can open in any browser.

It was built to demonstrate how public news data can be transformed into structured, map-ready intelligence — the kind of triage workflow used in OSINT analysis and national security research — using only open APIs and a few hundred lines of Python.

---

## Installation

```bash
git clone <repo-url>
cd geowatch
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

## CLI Usage

```bash
# Basic — last 30 days
python main.py --location "Ukraine"

# Shorter window, more articles
python main.py --location "Gaza" --days 7 --max-articles 50

# Custom output filename
python main.py --location "Beirut" --days 14 --output beirut.html

# Flags
#   --location       Required. Location name to search (e.g. "Somalia")
#   --days           Days back to search (default: 30)
#   --max-articles   Max articles to analyze (default: 20, max: 100)
#   --output         Output HTML filename (default: <location>_map.html)
```

The map opens as a standalone HTML file — no server needed.

---

## Web UI

```bash
python app.py
# → open http://localhost:5000
```

Fill in a location and days slider, hit **Run Analysis**, and the map embeds inline in your browser.

---

## Screenshot

![GeoWatch Map](screenshot.png)

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.10+ |
| News data | NewsAPI `/v2/everything` |
| LLM | Groq API — `llama3-70b-8192` |
| Maps | Folium (Leaflet.js wrapper) |
| Web UI | Flask |
| Env | python-dotenv |

---

## Roadmap

- **Satellite imagery overlay** — Pull recent Sentinel-2 or Planet imagery tiles for the queried region and toggle them as a Folium layer
- **Entity relationship graph** — Use NetworkX to visualize connections between people and organizations extracted across all articles
- **Alert system** — Poll NewsAPI on a schedule and push a notification (email or webhook) when a new critical-severity event appears for a watched location
- **Multi-location comparison** — Accept a list of locations and generate a single combined map for regional trend analysis
