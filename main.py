import argparse
import sys
from collections import Counter

from analyzer import analyze_article
from fetcher import get_news
from mapper import build_map


def _bar(count: int, total: int, width: int = 10) -> str:
    filled = round((count / total) * width) if total else 0
    return "█" * filled + "░" * (width - filled)


def _print_summary(location: str, days: int, articles: list[dict], output: str) -> None:
    analyzed = [a for a in articles if a.get("analysis")]
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
    print(f"  Map saved to → {output}")
    print("═" * 43)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GeoWatch — Geospatial intelligence from live news"
    )
    parser.add_argument("--location", required=True, help="Location to query (e.g. 'Beirut')")
    parser.add_argument("--days", type=int, default=30, help="Number of past days to search (default: 30)")
    parser.add_argument(
        "--output",
        default=None,
        help="Output HTML filename (default: <location>_map.html)",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=20,
        metavar="N",
        help="Max articles to analyze (default: 20, max: 100)",
    )
    args = parser.parse_args()

    max_articles = max(1, min(args.max_articles, 100))
    output = args.output or f"{args.location.lower().replace(' ', '_')}_map.html"

    # ── Phase 1: Fetch ────────────────────────────────────────────────────────
    print(f'\nFetching news for "{args.location}" (last {args.days} days)...')
    try:
        raw_articles = get_news(args.location, args.days)
    except (EnvironmentError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    articles = raw_articles[:max_articles]
    print(f'Found {len(raw_articles)} articles for "{args.location}" (analyzing top {len(articles)})\n')

    for i, art in enumerate(articles, 1):
        print(f"  [{i:>2}] {art['date']}  {art['source']}")
        print(f"       {art['title']}")
        if art["description"]:
            desc = art["description"][:120] + ("…" if len(art["description"]) > 120 else "")
            print(f"       {desc}")
        print()

    # ── Phase 2: Analyze ─────────────────────────────────────────────────────
    print("─" * 43)
    print("Running Groq LLM analysis...")
    print("─" * 43)

    events: list[dict] = []
    for i, art in enumerate(articles, 1):
        print(f"  Analyzing article {i}/{len(articles)}: {art['title'][:60]}...")
        analysis = analyze_article(art)
        events.append({"article": art, "analysis": analysis})
        if analysis:
            sev = analysis.get("severity", "?").upper()
            etype = analysis.get("event_type", "?")
            summary = analysis.get("one_line_summary", "")[:80]
            print(f"    └─ [{sev}] {etype} — {summary}")
        else:
            print("    └─ [WARN] Could not parse analysis for this article")

    # ── Phase 3 & 4: Map + Summary ───────────────────────────────────────────
    print()
    print("Building map...")
    plotted = build_map(events, args.location, output)
    print(f"Map saved to → {output}  ({plotted} events plotted)")

    _print_summary(args.location, args.days, events, output)


if __name__ == "__main__":
    main()
