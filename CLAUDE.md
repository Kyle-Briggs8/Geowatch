# GeoWatch

Open-source geospatial intelligence dashboard. Fetches news from NewsAPI and GDELT, classifies events via Groq LLM, and visualizes escalation patterns on interactive maps and charts.

## Architecture

```
main.py          CLI entry point (argparse)
app.py           Flask web UI, background-thread job runner, status polling
fetcher.py       Dual-source news ingestion (NewsAPI + GDELT), synonym filtering, date-windowed parallel fetch
analyzer.py      Groq LLM article classification (event type, severity, entities, summary, Admiralty credibility)
grading.py       IC tradecraft: NATO Admiralty source grading (A–F/1–6), ICD 203 confidence assessment
demo.py          Demo-mode cache: save/load analyzed event sets as JSON in demo_data/
mapper.py        Folium map generation, marker clustering, popup cards with images
visualizer.py    Dashboard assembly: interactive weekly/daily timeline + event log, glance panel, sourcing table, comparison chart
briefer.py       Markdown intelligence briefing generator
gunicorn.conf.py Render deployment config
render.yaml      Render service definition
```

## Key design decisions

- **Dual-source ingestion:** NewsAPI (30-day cap, free tier) + GDELT (90-day cap, no key needed). Both fetched in parallel via ThreadPoolExecutor. GDELT is unreliable on shared IPs so NewsAPI carries primary load.
- **Date-windowed fetching:** Date range split into 7-day windows queried separately to prevent clustering all results in the most recent 1-2 days.
- **Synonym filtering:** LLM generates ~20 location synonyms on first run to filter irrelevant articles without losing niche city-specific coverage.
- **Background thread pipeline:** Flask routes return immediately, pipeline runs in a background thread, frontend polls /status/<job_id> every 2s. Prevents gunicorn timeout kills on Render.
- **Single-file dashboard:** Everything in one self-contained HTML file (map embedded as a base64 data-URI iframe). No external dependencies at render time.
- **Light editorial theme:** Paper background (#faf9f7), white cards, serif display (Iowan Old Style/Georgia), navy #16365c + blue #2563eb accents, pill badges. Severity palette for light backgrounds: low #1a7f37, medium #d4a72c, high #ea7317, critical #dc2626. Theme constants live at the top of visualizer.py.
- **Timeline component:** Weekly severity-stacked bars (solid contiguous segments, green bottom → red top); clicking a week expands an inline daily breakdown and filters the event log to that week. This one component replaced both the old matplotlib severity chart and the dot swimlane.
- **Tradecraft grading:** Source reliability (A–F) comes from a curated outlet table in grading.py; information credibility (1–6) is judged per-article by the LLM. Analytic confidence (ICD 203) is derived deterministically from sourcing breadth/quality, never from model self-assessment.
- **Demo mode:** `--save-demo` caches a live run's analyzed events to demo_data/ (committed); `--demo` (CLI) or the web checkbox replays it with zero API calls. Use for live demos so NewsAPI/GDELT/Groq flakiness can't break a presentation.

## Conventions

- API keys in `.env` via python-dotenv. Never hardcode secrets.
- `.env` is gitignored. Use environment variables on Render.
- All functions have docstrings.
- Print progress to terminal during pipeline execution.
- Severity colors: green=low, yellow=medium, orange=high, red=critical.
- Event types: conflict, political, natural_disaster, economic, protest, terrorism, other.

## Running locally

```bash
pip install -r requirements.txt
# CLI
python main.py --location "Ukraine" --days 30
# Web UI
python app.py  # localhost:5000
```

## Testing

```bash
pytest tests/ -v
```

## Deployment

Deployed on Render via render.yaml. Push to master triggers auto-redeploy. Environment variables set in Render dashboard: NEWSAPI_KEY, GROQ_API_KEY.

## Known limitations

- NewsAPI free tier: 100 requests/day, 30-day history max
- GDELT: rate-limited on shared IPs (Render), unreliable in production
- Groq free tier: rate-limited, 0.5s sleep between calls
- Comparison mode with high article counts can take 60-90s
