# GeoWatch

Open-source geospatial intelligence dashboard. Fetches news from NewsAPI and GDELT, classifies events via Groq LLM, and visualizes escalation patterns on interactive maps and charts.

## Architecture

```
main.py          CLI entry point (argparse)
app.py           Flask web UI, background-thread job runner, status polling
fetcher.py       Dual-source news ingestion (NewsAPI + GDELT), synonym filtering, date-windowed parallel fetch
analyzer.py      Groq LLM article classification (event type, severity, entities, summary)
mapper.py        Folium map generation, marker clustering, popup cards with images
visualizer.py    Matplotlib severity escalation chart + interactive HTML swimlane timeline
briefer.py       Markdown intelligence briefing generator
gunicorn.conf.py Render deployment config
render.yaml      Render service definition
```

## Key design decisions

- **Dual-source ingestion:** NewsAPI (30-day cap, free tier) + GDELT (90-day cap, no key needed). Both fetched in parallel via ThreadPoolExecutor. GDELT is unreliable on shared IPs so NewsAPI carries primary load.
- **Date-windowed fetching:** Date range split into 7-day windows queried separately to prevent clustering all results in the most recent 1-2 days.
- **Synonym filtering:** LLM generates ~20 location synonyms on first run to filter irrelevant articles without losing niche city-specific coverage.
- **Background thread pipeline:** Flask routes return immediately, pipeline runs in a background thread, frontend polls /status/<job_id> every 2s. Prevents gunicorn timeout kills on Render.
- **Single-file dashboard:** All charts embedded as base64 images in a single HTML file. Swimlane is interactive HTML/JS. No external dependencies at render time.

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
