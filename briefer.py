import sys
from collections import Counter
from datetime import datetime, timedelta

from grading import assess_confidence, grade_event, source_reliability, RELIABILITY_DESC


_SEV_ORDER  = ["low", "medium", "high", "critical"]
_SEV_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _coverage_gaps(events: list[dict], days: int) -> list[str]:
    """Return formatted date strings for days in the window that have zero articles."""
    end   = datetime.utcnow().date()
    start = end - timedelta(days=days - 1)
    covered: set[str] = set()
    for ev in events:
        d = ev.get("article", {}).get("date", "")
        if d:
            covered.add(d)
    gaps = []
    cur = start
    while cur <= end:
        s = cur.strftime("%Y-%m-%d")
        if s not in covered:
            gaps.append(cur.strftime("%b %-d") if sys.platform != "win32"
                        else cur.strftime("%b ") + str(cur.day))
        cur += timedelta(days=1)
    return gaps


def _fmt_date(ds: str) -> str:
    """Format a YYYY-MM-DD date string as 'Mon D' (e.g. 'Jun 6')."""
    try:
        dt = datetime.strptime(ds, "%Y-%m-%d")
        return dt.strftime("%b ") + str(dt.day)
    except (ValueError, TypeError):
        return ds


def generate_brief(events: list[dict], location: str, days: int) -> str:
    """Return a markdown intelligence briefing for the given events."""
    now       = datetime.utcnow()
    start_dt  = now - timedelta(days=days)
    generated = now.strftime("%Y-%m-%d %H:%M UTC")
    period    = f"{_fmt_date(start_dt.strftime('%Y-%m-%d'))} – {_fmt_date(now.strftime('%Y-%m-%d'))}"

    analyzed = [e for e in events if e.get("analysis")]

    # ── Trend (one sentence) ─────────────────────────────────────────────────
    end_w = now
    start_w = end_w - timedelta(days=days)
    weeks: list = []
    cur = start_w
    while cur < end_w:
        nxt = min(cur + timedelta(days=7), end_w)
        weeks.append((cur, nxt))
        cur = nxt

    counts = {s: [0] * len(weeks) for s in _SEV_ORDER}
    for ev in analyzed:
        try:
            dt = datetime.strptime(ev["article"].get("date", ""), "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        sev = ev["analysis"].get("severity", "low").lower()
        if sev not in counts:
            sev = "low"
        for i, (ws, we) in enumerate(weeks):
            if ws <= dt < we or (i == len(weeks) - 1 and dt >= ws):
                counts[sev][i] += 1
                break

    mid    = max(1, len(weeks) // 2)
    first  = sum(_SEV_WEIGHT[s] * sum(counts[s][:mid]) for s in _SEV_ORDER)
    second = sum(_SEV_WEIGHT[s] * sum(counts[s][mid:]) for s in _SEV_ORDER)

    confidence, confidence_basis = assess_confidence(analyzed)
    conf_upper = confidence.upper()

    # Estimative language per ICD 203: probability bands accompany each outlook.
    if first == 0 and second == 0:
        trend_sentence = "Insufficient reporting to assess trend over the period; confidence in any trend judgment is low."
    elif first == 0:
        trend_sentence = (
            f"We assess with {conf_upper} confidence that activity emerged in the second half of the "
            "reporting period; with no baseline for comparison, near-term trajectory cannot be judged."
        )
    elif (second - first) / first > 0.20:
        pct = int(((second - first) / first) * 100)
        trend_sentence = (
            f"We assess with {conf_upper} confidence that the situation is escalating — the weighted "
            f"severity index increased {pct}% in the second half of the reporting period. "
            "Continued elevated activity over the near term is likely (55–80%)."
        )
    elif (first - second) / first > 0.20:
        pct = int(((first - second) / first) * 100)
        trend_sentence = (
            f"We assess with {conf_upper} confidence that the situation is stabilizing — the weighted "
            f"severity index decreased {pct}% in the second half of the reporting period. "
            "Renewed near-term escalation is unlikely (20–45%)."
        )
    else:
        trend_sentence = (
            f"We assess with {conf_upper} confidence that the situation is stable — no significant "
            "change in weighted severity across the reporting period. A significant near-term shift "
            "in tempo is unlikely (20–45%)."
        )

    # ── Top 3 events by severity ─────────────────────────────────────────────
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_events = sorted(
        analyzed,
        key=lambda e: sev_rank.get(e["analysis"].get("severity", "low").lower(), 3)
    )
    top3 = sorted_events[:3]

    top_md = ""
    for i, ev in enumerate(top3, 1):
        a    = ev["analysis"]
        art  = ev["article"]
        sev   = a.get("severity", "?").upper()
        summ  = a.get("one_line_summary", art.get("title", ""))
        date  = _fmt_date(art.get("date", ""))
        src   = art.get("source", "Unknown")
        grade = grade_event(ev)
        ents  = ", ".join(a.get("entities") or []) or "—"
        top_md += (
            f"\n**{i}. [{sev}]** {summ}\n"
            f"*{date} | {src} [{grade}]*\n"
            f"Key entities: {ents}\n"
        )

    # ── Key entities ─────────────────────────────────────────────────────────
    entity_counter: Counter = Counter()
    for ev in analyzed:
        for ent in (ev["analysis"].get("entities") or []):
            if ent and len(ent) > 1:
                entity_counter[ent] += 1

    entity_rows = ""
    for ent, cnt in entity_counter.most_common(8):
        entity_rows += f"| {ent} | {cnt} |\n"
    if not entity_rows:
        entity_rows = "| — | — |\n"

    # ── Sourcing & reliability ───────────────────────────────────────────────
    src_counter: Counter = Counter()
    for ev in analyzed:
        src = (ev["article"].get("source") or "Unknown").strip()
        src_counter[src] += 1

    source_rows = ""
    for src, cnt in src_counter.most_common(10):
        rel = source_reliability(src)
        source_rows += f"| {src} | {rel} — {RELIABILITY_DESC[rel]} | {cnt} |\n"
    if not source_rows:
        source_rows = "| — | — | — |\n"

    # ── Coverage gaps ────────────────────────────────────────────────────────
    gaps = _coverage_gaps(events, days)
    gap_line = (
        f"Coverage gaps: {', '.join(gaps)}" if gaps
        else "No coverage gaps — at least one article found for every day in the window."
    )

    dates = sorted(
        ev["article"]["date"] for ev in events
        if ev.get("article", {}).get("date")
    )
    date_range = (
        f"{_fmt_date(dates[0])} – {_fmt_date(dates[-1])}"
        if dates else "N/A"
    )

    return f"""\
# GeoWatch Intelligence Briefing
**Location:** {location} | **Period:** {period} | **Generated:** {generated}

---

## Situation Assessment
{trend_sentence}

*Confidence basis: {confidence_basis}.*

## Top Events
{top_md.strip()}

---

## Key Entities

| Entity | Appearances |
|--------|-------------|
{entity_rows.strip()}

---

## Sourcing & Reliability

| Source | Admiralty reliability | Reports |
|--------|-----------------------|---------|
{source_rows.strip()}

*Source grades follow the NATO Admiralty System — letter: source reliability (A–F); digit shown on individual events: information credibility (1–6). Estimative language and confidence levels conform to ICD 203.*

---

## Coverage Summary

- Articles analyzed: {len(analyzed)}
- Date range: {date_range} ({days} days)
- {gap_line}

---
*Generated by GeoWatch — open-source geospatial intelligence*
"""
