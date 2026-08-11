import argparse
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

# Force UTF-8 output on Windows terminals (avoids cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analyzer import analyze_article, analyze_posts
from briefer import generate_brief
from demo import load_demo_events, save_demo_events
from entities import build_entity_cooccurrence
from fetcher import get_news, rank_articles
from geocoder import geocode_events
from visualizer import build_dashboard, build_comparison_dashboard, _compute_trend
from xfetcher import get_x_posts, has_x_token

_SEV_VALUE = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _bar(count: int, total: int, width: int = 10) -> str:
    """Return a block-character progress bar string for count out of total."""
    filled = round((count / total) * width) if total else 0
    return "█" * filled + "░" * (width - filled)


def _check_alert(events: list[dict], threshold: str) -> dict | None:
    """Return alert dict if >30% of last-7-day events meet or exceed threshold, else None."""
    thr_val  = _SEV_VALUE.get(threshold.lower(), 3)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent   = []
    for ev in events:
        if not ev.get("analysis"):
            continue
        try:
            dt = datetime.strptime(ev["article"].get("date", ""), "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if dt >= week_ago:
            recent.append(ev)

    if not recent:
        return None

    above = sum(
        1 for ev in recent
        if _SEV_VALUE.get(ev["analysis"].get("severity", "low").lower(), 1) >= thr_val
    )
    pct = above / len(recent)
    if pct > 0.30:
        return {"threshold": threshold, "pct": pct, "count": above, "total": len(recent)}
    return None


def _print_alert_box(alert: dict, location: str) -> None:
    """Print a formatted terminal alert box for elevated activity."""
    pct_str = f"{alert['pct'] * 100:.0f}%"
    thr     = alert["threshold"].upper()
    width   = 58
    print()
    print("╔" + "═" * width + "╗")
    print(f"║  ⚠  ALERT: ELEVATED ACTIVITY DETECTED{' ' * (width - 39)}║")
    line2 = f"  {pct_str} of last-7-day events rated {thr} or above"
    print(f"║{line2:<{width}}║")
    line3 = f"  Threshold: {thr}  |  Location: {location}"
    print(f"║{line3:<{width}}║")
    print("╚" + "═" * width + "╝")
    print()


def _print_summary(location: str, days: int, events: list[dict], output: str) -> None:
    """Print a terminal summary table of event counts, severity, and output path."""
    analyzed = [a for a in events if a.get("analysis")]
    event_counts: Counter = Counter(
        a["analysis"]["event_type"] for a in analyzed if a["analysis"].get("event_type")
    )
    severity_counts: Counter = Counter(
        a["analysis"]["severity"] for a in analyzed if a["analysis"].get("severity")
    )
    total_events = sum(event_counts.values())

    print()
    print("═" * 43)
    print(f"  GeoWatch Report: {location} (last {days} days)")
    print("═" * 43)
    print(f"  Articles analyzed: {len(analyzed)}")
    if event_counts:
        print("  Event breakdown:")
        for etype, count in sorted(event_counts.items(), key=lambda x: -x[1]):
            bar = _bar(count, total_events)
            print(f"    {etype:<18} {bar}  {count}")
    if severity_counts:
        parts = []
        for sev in ("critical", "high", "medium", "low"):
            n = severity_counts.get(sev, 0)
            if n:
                parts.append(f"{n} {sev}")
        print(f"  Severity: {', '.join(parts)}")
    print(f"  Dashboard saved to → {output}")

    cooc = build_entity_cooccurrence(analyzed)
    if cooc["nodes"]:
        print()
        print("  Top entities:")
        for node in cooc["nodes"][:8]:
            print(f"    {node['name']:<24} {node['freq']} mentions")
    if cooc["edges"]:
        print()
        print("  Co-occurrences:")
        for edge in sorted(cooc["edges"], key=lambda e: -e["weight"])[:6]:
            label = f"  {edge['source']} — {edge['target']}"
            print(f"    {label:<40} {edge['weight']} articles")
    print("═" * 43)


def _run_single(args: argparse.Namespace) -> None:
    """Run the full single-location pipeline: fetch, analyze, build dashboard, optional brief."""
    max_articles    = max(1, min(args.max_articles, 100))
    alert_threshold = args.alert_threshold
    output = args.output or f"{args.location.lower().replace(' ', '_')}_dashboard.html"

    # ── Demo mode: render entirely from the cached dataset, no API calls ─────
    if args.demo:
        try:
            payload = load_demo_events(args.location)
        except FileNotFoundError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)
        events   = payload["events"]
        days     = payload.get("days", args.days)
        x_events = payload.get("x_events") if args.x else None
        x_status = "ok" if x_events is not None else None
        print(f'\n[DEMO] Using cached dataset for "{args.location}" '
              f'(captured {payload.get("captured_at", "unknown")}, '
              f'{len(events)} events'
              + (f', {len(x_events)} X posts' if x_events else '') + ')')
        if args.x and x_events is None:
            print("  [WARN] Demo cache has no X posts — re-capture with --x --save-demo",
                  file=sys.stderr)
        alert = _check_alert(events, alert_threshold) if alert_threshold else None
        if alert:
            _print_alert_box(alert, args.location)
        dashboard_html = build_dashboard(events, args.location, days, alert=alert,
                                         x_events=x_events, x_status=x_status)
        with open(output, "w", encoding="utf-8") as f:
            f.write(dashboard_html)
        _print_summary(args.location, days, events, output)
        if args.brief:
            brief_path = output.replace(".html", "_brief.md")
            with open(brief_path, "w", encoding="utf-8") as f:
                f.write(generate_brief(events, args.location, days))
            print(f"\n  Brief saved to → {brief_path}")
        return

    # ── X fetch runs in the background while news is fetched and analyzed ────
    x_fut = None
    x_status = None
    x_executor = None
    if args.x:
        if not has_x_token():
            print("\n  [WARN] --x requested but APIFY_TOKEN is not set — "
                  "continuing without X data. Get a free token at apify.com.",
                  file=sys.stderr)
            x_status = "no_token"
        else:
            x_executor = ThreadPoolExecutor(max_workers=1)
            x_fut = x_executor.submit(get_x_posts, args.location, args.days)

    print(f'\nFetching news for "{args.location}" (last {args.days} days)...')
    try:
        raw_articles = get_news(args.location, args.days)
    except (EnvironmentError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    ranked = rank_articles(raw_articles)
    print(
        f"Found {len(raw_articles)} articles — "
        f"analyzing best-graded candidates until {max_articles} relevant events\n"
    )

    print("─" * 43)
    print("Running Groq LLM analysis...")
    print("─" * 43)

    # Walk the quality ranking until enough RELEVANT events are collected —
    # articles the LLM screens out get backfilled by the next-best candidates.
    # Analysis budget capped at 2x the target so a noisy pool can't run away.
    budget = min(len(ranked), max_articles * 2)
    events: list[dict] = []
    for i, art in enumerate(ranked[:budget], 1):
        if len(events) >= max_articles:
            break
        print(f"  [{len(events) + 1:>3}/{max_articles}] {art['date']}  "
              f"{art['source']}: {art['title'][:60]}...")
        analysis = analyze_article(art, args.location)
        if analysis and analysis.get("relevant") is False:
            print(f"    └─ [SKIP] Not primarily about {args.location} — trying next candidate")
            continue
        events.append({"article": art, "analysis": analysis})
        if analysis:
            sev     = analysis.get("severity", "?").upper()
            etype   = analysis.get("event_type", "?")
            summary = analysis.get("one_line_summary", "")[:80]
            print(f"    └─ [{sev}] {etype} — {summary}")
        else:
            print("    └─ [WARN] Could not parse analysis for this article")

    events.sort(key=lambda e: e["article"].get("date") or "")
    if len(events) < max_articles:
        print(f"\n  [NOTE] {len(events)} relevant events found "
              f"(requested {max_articles}) — pool exhausted after screening")

    # ── Geocode events from their extracted locations ────────────────────────
    print("\nGeocoding event locations (Nominatim, cached)...")
    placed = geocode_events(events, args.location)
    print(f"  Placed {placed}/{len(events)} events at real coordinates "
          "(rest fall back to region centroid)")

    # ── Collect + classify X posts (fetch has been running in the background) ─
    x_events: list[dict] | None = None
    if x_fut is not None:
        posts, _ = x_fut.result()
        x_executor.shutdown(wait=False)
        if posts:
            print(f"\n  Classifying {len(posts)} X posts (batched)...")
            analyses = analyze_posts(posts, args.location)
            x_events = [{"post": p, "analysis": a}
                        for p, a in zip(posts, analyses) if a]
            print(f"  X Pulse: {len(posts)} posts fetched, {len(x_events)} relevant")
            x_status = "ok"
        else:
            x_events = None
            x_status = "error"

    if args.save_demo:
        demo_path = save_demo_events(args.location, args.days, events, x_events=x_events)
        print(f"\n  Demo dataset saved to → {demo_path}")

    # ── Alert threshold check ─────────────────────────────────────────────────
    alert = None
    if alert_threshold:
        alert = _check_alert(events, alert_threshold)
        if alert:
            _print_alert_box(alert, args.location)
        else:
            print(f"\n  [OK] Alert threshold ({alert_threshold.upper()}) not exceeded in last 7 days.")

    # ── Dashboard ─────────────────────────────────────────────────────────────
    print()
    print("Building dashboard (map + charts)...")
    dashboard_html = build_dashboard(events, args.location, args.days, alert=alert,
                                     x_events=x_events, x_status=x_status)
    with open(output, "w", encoding="utf-8") as f:
        f.write(dashboard_html)

    _print_summary(args.location, args.days, events, output)

    # ── Daily brief ──────────────────────────────────────────────────────────
    if args.brief:
        brief_path = output.replace(".html", "_brief.md")
        brief_md   = generate_brief(events, args.location, args.days)
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(brief_md)
        print(f"\n  Brief saved to → {brief_path}")
        print()
        print(brief_md)


def _run_compare(args: argparse.Namespace) -> None:
    """Run the two-location comparison pipeline in parallel and build the comparison dashboard."""
    loc_a, loc_b = args.compare
    max_articles = max(1, min(args.max_articles, 100))
    output = args.output or "comparison_dashboard.html"

    print(f'\nComparing "{loc_a}" vs "{loc_b}" (last {args.days} days)...\n')

    all_events: dict[str, list[dict]] = {}

    def _pipeline(location: str):
        try:
            raw = get_news(location, args.days)
            ranked = rank_articles(raw)
            print(f"[{location}] Analyzing candidates for {max_articles} relevant events...")
            evts = []
            for art in ranked[:max_articles * 2]:
                if len(evts) >= max_articles:
                    break
                a = analyze_article(art, location)
                if a and a.get("relevant") is False:
                    continue
                evts.append({"article": art, "analysis": a})
            evts.sort(key=lambda e: e["article"].get("date") or "")
            geocode_events(evts, location)
            return location, evts
        except Exception as exc:  # broad: one location failing must not cancel the other
            return location, exc

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_a = ex.submit(_pipeline, loc_a)
        fut_b = ex.submit(_pipeline, loc_b)
        for fut in (fut_a, fut_b):
            loc, result = fut.result()
            if isinstance(result, Exception):
                print(f"[ERROR] [{loc}] {result}", file=sys.stderr)
                all_events[loc] = []
            else:
                all_events[loc] = result

    events_a = all_events.get(loc_a, [])
    events_b = all_events.get(loc_b, [])

    print("\nBuilding comparison dashboard...")
    html = build_comparison_dashboard(loc_a, events_a, loc_b, events_b, args.days)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    # ── Terminal summary table ────────────────────────────────────────────────
    def _sev_counts(events):
        return Counter(
            e["analysis"]["severity"]
            for e in events
            if e.get("analysis") and e["analysis"].get("severity")
        )

    def _trend_sym(t: str) -> str:
        if "escalat"  in t.lower(): return "Escalating ▲"
        if "stabiliz" in t.lower(): return "Stabilizing ▼"
        return "Stable ●"

    sc_a    = _sev_counts(events_a)
    sc_b    = _sev_counts(events_b)
    trend_a = _trend_sym(_compute_trend(events_a, args.days))
    trend_b = _trend_sym(_compute_trend(events_b, args.days))

    col = max(len(loc_a), len(loc_b), 14) + 2
    sep = "═" * (col * 2 + 24)

    print()
    print(sep)
    print(f"  GeoWatch Comparative Report: {loc_a} vs {loc_b} ({args.days} days)")
    print(sep)
    print(f"  {'':22}  {loc_a:<{col}}  {loc_b}")
    print(f"  {'Articles:':<22}  {len(events_a):<{col}}  {len(events_b)}")
    for sev in ("critical", "high", "medium", "low"):
        n_a, n_b = sc_a.get(sev, 0), sc_b.get(sev, 0)
        print(f"  {sev.capitalize() + ':':<22}  {n_a:<{col}}  {n_b}")
    print(f"  {'Trend:':<22}  {trend_a:<{col}}  {trend_b}")
    print()
    print(f"  Dashboard saved to → {output}")
    print(sep)


def main() -> None:
    """Parse CLI arguments and dispatch to the single or comparison pipeline."""
    parser = argparse.ArgumentParser(
        description="GeoWatch — Geospatial intelligence from live news"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--location",
        help="Location to query (e.g. 'Beirut')",
    )
    group.add_argument(
        "--compare", nargs=2, metavar=("LOC_A", "LOC_B"),
        help="Two locations to compare side-by-side (e.g. 'Ukraine' 'Taiwan')",
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Number of past days to search (default: 30)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output HTML filename (default: auto-named)",
    )
    parser.add_argument(
        "--max-articles", type=int, default=20, metavar="N",
        help="Max articles per location to analyze (default: 20, max: 100)",
    )
    parser.add_argument(
        "--brief", action="store_true",
        help="Generate a one-page markdown intelligence briefing alongside the dashboard",
    )
    parser.add_argument(
        "--x", action="store_true",
        help="Include X/Twitter social signal as an 'X Pulse' tab (requires APIFY_TOKEN)",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Render from the cached demo dataset for this location — no API calls",
    )
    parser.add_argument(
        "--save-demo", action="store_true",
        help="After a live run, save the analyzed events to demo_data/ for later --demo use",
    )
    parser.add_argument(
        "--alert-threshold",
        choices=["low", "medium", "high", "critical"],
        metavar="LEVEL",
        help="Alert if >30%% of last-7-day events meet or exceed this severity (low/medium/high/critical)",
    )
    args = parser.parse_args()

    if args.compare and (args.demo or args.save_demo):
        parser.error("--demo/--save-demo are only supported with --location (single mode)")

    if args.compare and args.x:
        parser.error("--x is only supported with --location (single mode)")

    if args.compare:
        _run_compare(args)
    else:
        _run_single(args)


if __name__ == "__main__":
    main()
