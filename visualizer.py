import base64
import html as _html
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import folium
from folium import Element
from folium.plugins import MarkerCluster

from mapper import REGION_COORDS, _LEGEND_HTML
from entities import build_entity_cooccurrence, render_entity_graph_html
from grading import assess_confidence, describe_grade, grade_event, grade_post

_SEV_ORDER = ["low", "medium", "high", "critical"]
_SEV_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
# Light editorial theme — severity fills tuned for white backgrounds
_SEV_MPL = {
    "low": "#1a7f37",
    "medium": "#d4a72c",
    "high": "#ea7317",
    "critical": "#dc2626",
}
_SEV_CSS = {
    "low": "#1a7f37",
    "medium": "#d4a72c",
    "high": "#ea7317",
    "critical": "#dc2626",
}
# Severity pill colors: (text, background)
_SEV_PILL = {
    "low":      ("#1a7f37", "#d3f2dd"),
    "medium":   ("#9a6700", "#fbedc0"),
    "high":     ("#c2410c", "#ffe0cc"),
    "critical": ("#b91c1c", "#fcd9d9"),
}
_EVENT_TYPES = [
    "conflict", "political", "natural_disaster", "economic",
    "protest", "terrorism", "other",
]
_TYPE_COLOR = {
    "conflict": "#ea7317", "terrorism": "#dc2626", "political": "#d4a72c",
    "protest": "#0e7490", "natural_disaster": "#2563eb",
    "economic": "#1a7f37", "other": "#c9c6c0",
}
_BG    = "#ffffff"
_PAPER = "#faf9f7"
_TEXT  = "#55606c"
_INK   = "#1c2024"
_MUTED = "#98a1ab"
_RULE  = "#e7e5e0"
_NAVY  = "#16365c"
_BLUE  = "#2563eb"
_SERIF = "'Iowan Old Style','Palatino Linotype',Georgia,serif"
_SANS  = "'Segoe UI',system-ui,-apple-system,sans-serif"
_MONO  = "'Cascadia Mono',Consolas,monospace"


def _fig_to_b64(fig: plt.Figure) -> str:
    """Serialize a Matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150, facecolor=_BG)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


# ── Timeline: weekly stacked bars → daily drill-down → filtered event log ────

def _fmt_day(d) -> str:
    """Format a date as 'Aug 8' (no zero-padding)."""
    return f"{d.strftime('%b')} {d.day}"


def _parse_event_date(ev: dict):
    """Return the event's article date as a date, or None."""
    try:
        return datetime.strptime(ev.get("article", {}).get("date", ""), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _week_day_lists(days: int) -> list[list]:
    """Split the reporting window into weeks; return a list of per-week day lists."""
    end   = datetime.utcnow()
    start = end - timedelta(days=days)
    weeks = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=7), end)
        weeks.append((cur, nxt))
        cur = nxt

    day_lists = []
    for i, (ws, we) in enumerate(weeks):
        if i < len(weeks) - 1:
            day_lists.append([(ws + timedelta(days=j)).date()
                              for j in range(max(1, (we - ws).days))])
        else:
            lst, d = [], ws.date()
            while d <= end.date():
                lst.append(d)
                d += timedelta(days=1)
            day_lists.append(lst)
    return day_lists


def _event_log_rows(events: list[dict], day_to_week: dict) -> str:
    """Render the chronological event log rows (newest first), tagged by week id."""
    analyzed = [(e, _parse_event_date(e)) for e in events if e.get("analysis")]
    analyzed.sort(key=lambda t: (t[1] is None, t[1]), reverse=True)

    rows = ""
    for ev, d in analyzed:
        a     = ev["analysis"]
        art   = ev["article"]
        sev   = (a.get("severity") or "low").lower()
        if sev not in _SEV_PILL:
            sev = "low"
        pt, pb = _SEV_PILL[sev]
        etype  = (a.get("event_type") or "other").replace("_", " ").capitalize()
        title  = _html.escape(a.get("one_line_summary") or art.get("title", ""))
        src    = _html.escape(art.get("source") or "Unknown")
        url    = _html.escape(art.get("url") or "#")
        grade  = grade_event(ev)
        gdesc  = _html.escape(describe_grade(grade))
        wk     = day_to_week.get(d, "none")
        date_s = _fmt_day(d) if d else "—"
        rows += f"""
      <a class="ev" data-wk="{wk}" href="{url}" target="_blank" rel="noopener">
        <span class="ev-date">{date_s}</span>
        <span class="ev-mark" style="background:{_SEV_CSS[sev]}"></span>
        <span class="ev-main">
          <span class="ev-title">{title}</span>
          <span class="ev-tags"><span class="sev-pill" style="color:{pt};background:{pb}">{sev.upper()}</span><span class="type-tag">{etype}</span></span>
        </span>
        <span class="ev-meta">{src} <span class="grade" title="{gdesc}">{grade}</span></span>
      </a>"""
    return rows


def _timeline_html(events: list[dict], days: int) -> str:
    """Weekly stacked-severity bars with click-to-expand daily breakdown and a
    chronological event log that filters to the selected week. Self-contained HTML/JS."""
    day_lists = _week_day_lists(days)
    day_to_week = {d: f"w{i}" for i, lst in enumerate(day_lists) for d in lst}

    # Per-day severity counts
    day_counts: dict = defaultdict(Counter)
    for ev in events:
        if not ev.get("analysis"):
            continue
        d = _parse_event_date(ev)
        if d in day_to_week:
            sev = (ev["analysis"].get("severity") or "low").lower()
            day_counts[d][sev if sev in _SEV_CSS else "low"] += 1

    week_counts = []
    for lst in day_lists:
        c = Counter()
        for d in lst:
            c.update(day_counts[d])
        week_counts.append(c)

    max_total = max((sum(c.values()) for c in week_counts), default=0) or 1
    unit = max(6, min(16, round(112 / max_total)))

    bars_html, labels_html, panels_html = "", "", ""
    for i, (lst, wc) in enumerate(zip(day_lists, week_counts)):
        wid   = f"w{i}"
        total = sum(wc.values())
        label = f"{_fmt_day(lst[0])}–{lst[-1].day}" if len(lst) > 1 else _fmt_day(lst[0])
        crit  = wc.get("critical", 0)
        sub   = f"{total} event{'s' if total != 1 else ''}" + (f" · {crit} critical" if crit else "")
        segs  = "".join(
            f'<i style="background:{_SEV_CSS[s]};height:{wc[s] * unit}px"></i>'
            for s in _SEV_ORDER if wc.get(s)
        ) or '<i style="background:#e7e5e0;height:3px"></i>'
        tip   = ", ".join(f"{wc[s]} {s}" for s in _SEV_ORDER if wc.get(s)) or "no coverage"
        bars_html   += f'<div class="wk" data-wk="{wid}" title="{label} · {tip}">{segs}</div>'
        labels_html += f'<div class="wk-label"><b>{label}</b><span>{sub}</span></div>'

        day_bars, day_axis = "", ""
        for d in lst:
            dc = day_counts[d]
            if dc:
                dsegs = "".join(
                    f'<i style="background:{_SEV_CSS[s]};height:{dc[s] * 12 + (dc[s] - 1)}px"></i>'
                    for s in _SEV_ORDER if dc.get(s)
                )
                dtip = _fmt_day(d) + " · " + ", ".join(f"{dc[s]} {s}" for s in _SEV_ORDER if dc.get(s))
                day_bars += f'<div class="day" title="{dtip}">{dsegs}</div>'
            else:
                day_bars += f'<div class="day empty" title="{_fmt_day(d)} · no coverage"><i></i></div>'
            day_axis += f"<span>{d.day}</span>"
        panels_html += f"""
      <div class="wk-days" id="days-{wid}">
        <div class="wk-days-title">Week of {label} — daily breakdown <a data-close>&#x2715; close</a></div>
        <div class="day-strip">{day_bars}</div>
        <div class="day-axis">{day_axis}</div>
      </div>"""

    log_rows = _event_log_rows(events, day_to_week)
    if not log_rows:
        log_rows = '<div style="padding:18px 22px;color:#98a1ab;font-size:12px;">No analyzed events in this window.</div>'

    return f"""
    <div class="density">
      <div class="weeks">{bars_html}</div>
      <div class="wk-labels">{labels_html}</div>
      {panels_html}
      <div class="density-legend">
        <span><i style="background:{_SEV_CSS['low']}"></i>Low</span>
        <span><i style="background:{_SEV_CSS['medium']}"></i>Medium</span>
        <span><i style="background:{_SEV_CSS['high']}"></i>High</span>
        <span><i style="background:{_SEV_CSS['critical']}"></i>Critical</span>
        <span style="margin-left:auto;color:#98a1ab">Gray stubs = days with no coverage</span>
      </div>
    </div>
    <div class="feed" id="feed">{log_rows}</div>
    <script>
    (function(){{
      var current = null;
      var weeks = document.querySelectorAll('.wk');
      var feed  = document.getElementById('feed');
      function close(){{
        document.querySelectorAll('.wk-days.open').forEach(function(p){{ p.classList.remove('open'); }});
        weeks.forEach(function(w){{ w.classList.remove('sel'); }});
        feed.classList.remove('filtered');
        feed.querySelectorAll('.ev').forEach(function(e){{ e.classList.remove('show'); }});
        current = null;
      }}
      function open(id, wkEl){{
        close();
        current = id;
        wkEl.classList.add('sel');
        var panel = document.getElementById('days-' + id);
        if (panel) panel.classList.add('open');
        feed.classList.add('filtered');
        feed.querySelectorAll('.ev[data-wk="' + id + '"]').forEach(function(e){{ e.classList.add('show'); }});
      }}
      weeks.forEach(function(w){{
        w.addEventListener('click', function(){{
          var id = w.getAttribute('data-wk');
          if (current === id) {{ close(); }} else {{ open(id, w); }}
        }});
      }});
      document.querySelectorAll('[data-close]').forEach(function(a){{
        a.addEventListener('click', function(ev){{ ev.stopPropagation(); ev.preventDefault(); close(); }});
      }});
    }})();
    </script>"""


def _event_log_html(events: list[dict], days: int) -> str:
    """Standalone (unfiltered) chronological event log — used in comparison mode."""
    day_lists = _week_day_lists(days)
    day_to_week = {d: f"w{i}" for i, lst in enumerate(day_lists) for d in lst}
    rows = _event_log_rows(events, day_to_week)
    if not rows:
        return '<div style="padding:18px 22px;color:#98a1ab;font-size:12px;">No analyzed events.</div>'
    return f'<div class="feed">{rows}</div>'


# ── Situation at a glance ────────────────────────────────────────────────────

def _glance_html(events: list[dict]) -> str:
    """Headline stats plus event-type breakdown bars for the reporting period."""
    analyzed = [e for e in events if e.get("analysis")]
    sev_c = Counter((e["analysis"].get("severity") or "low").lower() for e in analyzed)
    high_crit = sev_c.get("high", 0) + sev_c.get("critical", 0)
    sources = {
        (e.get("article", {}).get("source") or "").strip()
        for e in analyzed if e.get("article", {}).get("source")
    }
    from grading import source_reliability
    best = min((source_reliability(s) for s in sources), default="F")

    evt_c = Counter(
        (e["analysis"].get("event_type") or "other") for e in analyzed
    )
    total = sum(evt_c.values()) or 1
    type_rows = ""
    for etype, cnt in evt_c.most_common(7):
        color = _TYPE_COLOR.get(etype, _TYPE_COLOR["other"])
        label = etype.replace("_", " ").capitalize()
        pct   = max(4, round(cnt / total * 100))
        type_rows += (
            f'<div class="type-row"><span class="type-name">{label}</span>'
            f'<div class="type-bar"><i style="width:{pct}%;background:{color}"></i></div>'
            f'<span class="type-n">{cnt}</span></div>'
        )

    return f"""
    <div class="stats">
      <div class="stat"><div class="stat-num">{len(analyzed)}</div><div class="stat-label">Events analyzed</div></div>
      <div class="stat"><div class="stat-num" style="color:#c2410c">{high_crit}</div><div class="stat-label">High or critical</div></div>
      <div class="stat"><div class="stat-num">{len(sources)}</div><div class="stat-label">Distinct outlets</div></div>
      <div class="stat"><div class="stat-num" style="color:#1a7f37">{best}</div><div class="stat-label">Best sourcing grade</div></div>
    </div>
    <div class="types">{type_rows or '<div style="color:#98a1ab;font-size:12px;">No data</div>'}</div>"""


# ── Sourcing & reliability table ─────────────────────────────────────────────

_REL_PILL = {
    "A": ("#1a7f37", "#d3f2dd"), "B": ("#1a7f37", "#d3f2dd"),
    "C": ("#9a6700", "#fbedc0"), "D": ("#c2410c", "#ffe0cc"),
    "E": ("#b91c1c", "#fcd9d9"), "F": ("#55606c", "#f0efec"),
}


def _sourcing_table_html(events: list[dict]) -> str:
    """Admiralty source-reliability table for all analyzed events."""
    from grading import source_reliability, RELIABILITY_DESC
    analyzed = [e for e in events if e.get("analysis")]
    src_c: Counter = Counter(
        (e["article"].get("source") or "Unknown").strip() for e in analyzed
    )
    rows = ""
    for src, cnt in src_c.most_common(10):
        rel = source_reliability(src)
        pt, pb = _REL_PILL[rel]
        rows += (
            f'<tr><td>{_html.escape(src)}</td>'
            f'<td><span class="rel" style="color:{pt};background:{pb}">{rel}</span> {RELIABILITY_DESC[rel]}</td>'
            f'<td class="num">{cnt}</td></tr>'
        )
    if not rows:
        rows = '<tr><td colspan="3" style="color:#98a1ab">No data</td></tr>'
    return f"""
    <table>
      <tr><th>SOURCE</th><th>RELIABILITY</th><th style="text-align:right">REPORTS</th></tr>
      {rows}
    </table>
    <div class="table-note">Grades follow the NATO Admiralty System — letter: source reliability (A–F);
    digit on individual events: information credibility (1–6). Estimative language per ICD 203.</div>"""


# ── X Pulse tab components ───────────────────────────────────────────────────

def _fmt_count(n: int) -> str:
    """Format an engagement count: 999 → '999', 1200 → '1.2K', 2400000 → '2.4M'."""
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return str(n)


def _x_stats_html(x_events: list[dict]) -> str:
    """Headline stats row for the X Pulse tab."""
    authors = {e["post"].get("author") for e in x_events if e["post"].get("author")}
    engagement = sum(
        (e["post"].get("likes") or 0) + (e["post"].get("retweets") or 0)
        + (e["post"].get("replies") or 0)
        for e in x_events
    )
    high_crit = sum(
        1 for e in x_events
        if (e["analysis"].get("severity") or "").lower() in ("high", "critical")
    )
    return f"""
    <div class="stats">
      <div class="stat"><div class="stat-num">{len(x_events)}</div><div class="stat-label">Relevant posts</div></div>
      <div class="stat"><div class="stat-num">{len(authors)}</div><div class="stat-label">Unique accounts</div></div>
      <div class="stat"><div class="stat-num">{_fmt_count(engagement)}</div><div class="stat-label">Total engagement</div></div>
      <div class="stat"><div class="stat-num" style="color:#c2410c">{high_crit}</div><div class="stat-label">High or critical</div></div>
    </div>"""


def _x_volume_html(x_events: list[dict], days: int) -> str:
    """Posts-per-day strip: bar height = post count, color = dominant severity."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=days - 1)

    day_counts: dict = defaultdict(Counter)
    for e in x_events:
        try:
            d = datetime.strptime(e["post"].get("date", ""), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if start <= d <= end:
            sev = (e["analysis"].get("severity") or "low").lower()
            day_counts[d][sev if sev in _SEV_CSS else "low"] += 1

    max_total = max((sum(c.values()) for c in day_counts.values()), default=0) or 1
    unit = max(4, min(14, round(52 / max_total)))

    bars = ""
    cur = start
    while cur <= end:
        dc = day_counts.get(cur)
        label = f"{cur.strftime('%b')} {cur.day}"
        if dc:
            total = sum(dc.values())
            dominant = max(dc, key=lambda s: (dc[s], _SEV_WEIGHT[s]))
            tip = f"{label} · " + ", ".join(f"{dc[s]} {s}" for s in _SEV_ORDER if dc.get(s))
            bars += (f'<div class="xp-day" title="{tip}">'
                     f'<i style="background:{_SEV_CSS[dominant]};height:{total * unit}px"></i></div>')
        else:
            bars += (f'<div class="xp-day" title="{label} · no posts">'
                     f'<i style="background:#e7e5e0;height:3px"></i></div>')
        cur += timedelta(days=1)

    def _fmt(d):
        return f"{d.strftime('%b')} {d.day}"
    mid = start + (end - start) / 2

    return f"""
    <div class="density">
      <div class="xp-strip">{bars}</div>
      <div class="density-axis"><span>{_fmt(start)}</span><span>{_fmt(mid)}</span><span>{_fmt(end)}</span></div>
      <div class="density-legend">
        <span><i style="background:{_SEV_CSS['low']}"></i>Low</span>
        <span><i style="background:{_SEV_CSS['medium']}"></i>Medium</span>
        <span><i style="background:{_SEV_CSS['high']}"></i>High</span>
        <span><i style="background:{_SEV_CSS['critical']}"></i>Critical</span>
        <span style="margin-left:auto;color:#98a1ab">Bar height = posts that day · color = dominant severity</span>
      </div>
    </div>"""


def _x_feed_html(x_events: list[dict]) -> str:
    """Post feed styled like the news event log (newest first)."""
    def _key(e):
        return e["post"].get("date") or ""
    rows = ""
    for e in sorted(x_events, key=_key, reverse=True):
        p, a  = e["post"], e["analysis"]
        sev   = (a.get("severity") or "low").lower()
        if sev not in _SEV_PILL:
            sev = "low"
        pt, pb = _SEV_PILL[sev]
        etype = (a.get("event_type") or "other").replace("_", " ").capitalize()
        text  = _html.escape(p.get("text") or "")
        url   = _html.escape(p.get("url") or "#")
        grade = grade_post(e)
        gdesc = _html.escape(describe_grade(grade))
        date_s = "—"
        try:
            d = datetime.strptime(p.get("date", ""), "%Y-%m-%d")
            date_s = f"{d.strftime('%b')} {d.day}"
        except (ValueError, TypeError):
            pass
        author = _html.escape(p.get("author") or "@unknown")
        vbadge = ' <span class="xp-verified" title="Verified account">&#10004;</span>' if p.get("verified") else ""
        meta = (f"{author}{vbadge} &middot; {_fmt_count(p.get('followers', 0))} followers &middot; "
                f"&#9829; {_fmt_count(p.get('likes', 0))} &middot; "
                f"&#10561; {_fmt_count(p.get('retweets', 0))}")
        rows += f"""
      <a class="ev xp-post" href="{url}" target="_blank" rel="noopener">
        <span class="ev-date">{date_s}</span>
        <span class="ev-mark" style="background:{_SEV_CSS[sev]}"></span>
        <span class="ev-main">
          <span class="ev-title xp-text">{text}</span>
          <span class="ev-tags"><span class="sev-pill" style="color:{pt};background:{pb}">{sev.upper()}</span><span class="type-tag">{etype}</span></span>
        </span>
        <span class="ev-meta">{meta} <span class="grade" title="{gdesc}">{grade}</span></span>
      </a>"""
    return f'<div class="feed">{rows}</div>'


def _x_empty_html(message: str) -> str:
    """A single card with an empty-state message for the X Pulse pane."""
    return (f'<div class="card full"><div style="padding:40px 22px;text-align:center;'
            f'color:#98a1ab;font-size:13.5px;">{message}</div></div>')


def _x_tab_html(x_events: list[dict] | None, days: int, x_status: str | None) -> str:
    """Assemble the X Pulse pane content (cards inside a <main> grid)."""
    if x_status == "no_token":
        return _x_empty_html(
            "X data is not configured — add APIFY_TOKEN to your .env "
            "(free at apify.com) to enable X Pulse.")
    if x_status == "error":
        return _x_empty_html("X data was unavailable this run — see terminal warnings. "
                             "The news analysis is unaffected.")
    if not x_events:
        return _x_empty_html("No relevant X posts found in this window.")

    return f"""
    <div class="card full">
      <div class="card-head"><span class="card-title">Social Tempo</span><span class="card-sub">Posts per day &middot; classified by LLM triage</span></div>
      {_x_volume_html(x_events, days)}
    </div>
    <div class="card full">
      <div class="card-head"><span class="card-title">Signal Summary</span><span class="card-sub">This reporting period</span></div>
      {_x_stats_html(x_events)}
      <div class="table-note">Social posts are graded F on the Admiralty reliability scale —
      individual account reliability cannot be judged. The digit (1–6) is per-post information
      credibility assessed by LLM triage. Treat as leads, not confirmation.</div>
    </div>
    <div class="card full">
      <div class="card-head"><span class="card-title">Post Feed</span><span class="card-sub">Newest first &middot; click a post to open on X</span></div>
      {_x_feed_html(x_events)}
    </div>"""


def _map_iframe(events: list[dict], location: str) -> str:
    """Build a Folium map with MarkerCluster. Returns a self-contained <iframe> string."""
    center = REGION_COORDS.get(location, (20.0, 0.0))
    zoom   = 6 if location in REGION_COORDS else 2

    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB positron")
    cluster = MarkerCluster().add_to(m)

    for ev in events:
        analysis = ev.get("analysis")
        article  = ev.get("article", {})
        if not analysis:
            continue

        sev   = analysis.get("severity", "low").lower()
        color = _SEV_CSS.get(sev, _BLUE)

        # All article data stored as data-* on the icon div so the injected JS can read them
        data_attrs = " ".join(
            f'data-{k}="{_html.escape(str(v))}"'
            for k, v in {
                "title":  analysis.get("one_line_summary", ""),
                "source": article.get("source", ""),
                "date":   article.get("date", ""),
                "url":    article.get("url", ""),
                "image":  article.get("image_url") or "",
                "sev":    sev,
                "etype":  analysis.get("event_type", ""),
                "grade":  grade_event(ev),
                "gradedesc": describe_grade(grade_event(ev)),
            }.items()
        )
        icon_html = (
            f'<div class="gw-marker" {data_attrs} '
            f'style="width:14px;height:14px;border-radius:50%;cursor:pointer;'
            f'background:{color};border:2px solid #fff;'
            f'box-shadow:0 1px 4px rgba(28,32,36,0.35);"></div>'
        )
        folium.Marker(
            location=center,
            icon=folium.DivIcon(html=icon_html, icon_size=(14, 14), icon_anchor=(7, 7)),
            tooltip=analysis.get("one_line_summary", article.get("title", "")),
        ).add_to(cluster)

    m.get_root().html.add_child(Element(_LEGEND_HTML))

    # Inject pull-out card + SVG line + JS — same interaction pattern as the swimlane
    m.get_root().html.add_child(Element("""
<style>
.marker-cluster-small, .marker-cluster-medium, .marker-cluster-large { background: rgba(22,54,92,0.25) !important; }
.marker-cluster-small div, .marker-cluster-medium div, .marker-cluster-large div {
  background: rgba(22,54,92,0.9) !important; color: #fff !important;
  font-family: 'Segoe UI', system-ui, sans-serif !important; font-weight: 600;
}
.marker-cluster span { color: #fff !important; }
.leaflet-container { font-family: 'Segoe UI', system-ui, sans-serif; }
</style>
<svg id="gw-svg" style="position:fixed;top:0;left:0;width:100vw;height:100vh;
  pointer-events:none;z-index:9997;overflow:visible;">
  <line id="gw-line" x1="0" y1="0" x2="0" y2="0"
    stroke-width="1.5" stroke-opacity="0.7" display="none"/>
</svg>
<div id="gw-card" style="display:none;position:fixed;z-index:9999;width:200px;
  background:#fff;border-radius:8px;
  box-shadow:0 4px 20px rgba(0,0,0,0.22),0 0 0 1px rgba(0,0,0,0.07);
  overflow:hidden;font-family:'Segoe UI',system-ui,sans-serif;" onclick="event.stopPropagation()">
  <div style="position:relative;width:100%;height:100px;">
    <div style="position:absolute;top:0;left:0;right:0;bottom:0;background:#f0f2f5;
      display:flex;align-items:center;justify-content:center;
      color:#aaa;font-size:9px;letter-spacing:1px;">NO IMAGE AVAILABLE</div>
    <img id="gw-img" alt="" referrerpolicy="no-referrer"
      onerror="this.style.display='none'"
      style="position:absolute;top:0;left:0;width:100%;height:100%;
      object-fit:cover;display:none;z-index:1;">
    <div id="gw-badge" style="position:absolute;top:6px;left:6px;z-index:2;
      border-radius:3px;padding:2px 5px;font-size:8px;letter-spacing:1px;
      text-transform:uppercase;background:rgba(0,0,0,0.65);color:#fff;"></div>
  </div>
  <div style="padding:8px 10px 10px;cursor:pointer;" onclick="gwOpen()">
    <div id="gw-title" style="color:#111;font-weight:bold;font-size:10.5px;
      line-height:1.4;margin-bottom:4px;"></div>
    <div id="gw-meta" style="color:#999;font-size:9px;margin-bottom:6px;"></div>
    <span style="color:#1a6ef5;font-size:9px;">&#x1F517; Read article</span>
  </div>
</div>
<script>
(function(){
  var SEV={low:'#1a7f37',medium:'#d4a72c',high:'#ea7317',critical:'#dc2626'};
  var PW=200,M=12,GAP=14,curUrl='',activeEl=null;

  function hide(){
    document.getElementById('gw-card').style.display='none';
    document.getElementById('gw-line').setAttribute('display','none');
    activeEl=null;
  }

  window.gwOpen=function(){if(curUrl)window.open(curUrl,'_blank');};

  /* Auto-close when the marker leaves the viewport (map pan / zoom) */
  var obs=new IntersectionObserver(function(entries){
    entries.forEach(function(e){ if(!e.isIntersecting && e.target===activeEl) hide(); });
  },{threshold:0.1});

  /* Pick the card position that overlaps the fewest other markers */
  function bestPos(cx,cy,dotR,popH){
    var candidates=[
      {left:cx+dotR+GAP,       top:cy-popH/2},
      {left:cx-dotR-GAP-PW,    top:cy-popH/2},
      {left:cx-PW/2,            top:cy+dotR+GAP},
      {left:cx-PW/2,            top:cy-dotR-GAP-popH},
    ];
    var dots=document.querySelectorAll('.gw-marker');
    function pen(c){
      var p=0;
      if(c.left<M||c.left+PW>window.innerWidth-M)  p+=40;
      if(c.top<M ||c.top+popH>window.innerHeight-M) p+=40;
      dots.forEach(function(d){
        if(d===activeEl) return;
        var r=d.getBoundingClientRect();
        var dx=r.left+r.width/2,dy=r.top+r.height/2;
        if(dx>c.left&&dx<c.left+PW&&dy>c.top&&dy<c.top+popH) p+=6;
      });
      return p;
    }
    var best=candidates.reduce(function(a,b){return pen(a)<=pen(b)?a:b;});
    best.left=Math.max(M,Math.min(best.left,window.innerWidth-PW-M));
    best.top =Math.max(M,Math.min(best.top, window.innerHeight-popH-M));
    return best;
  }

  function show(el){
    if(el===activeEl){hide();return;}   /* same dot → toggle off */
    if(activeEl) obs.unobserve(activeEl);
    activeEl=el;
    obs.observe(el);

    var d=el.dataset,card=document.getElementById('gw-card'),
        ln=document.getElementById('gw-line');
    curUrl=d.url||'';
    var img=document.getElementById('gw-img');
    if(d.image){img.style.display='block';img.src=d.image;}
    else{img.style.display='none';}
    var badge=document.getElementById('gw-badge');
    badge.textContent=(d.etype||'').replace(/_/g,' ');
    badge.style.color=SEV[d.sev]||'#888';
    document.getElementById('gw-title').textContent=d.title||'';
    var meta=document.getElementById('gw-meta');
    meta.textContent=(d.source||'')+(d.date?' · '+d.date:'')+(d.grade?' · '+d.grade:'');
    meta.title=d.gradedesc||'';
    var col=SEV[d.sev]||'#888';

    card.style.display='block';card.style.visibility='hidden';
    var popH=card.offsetHeight;
    var mr=el.getBoundingClientRect();
    var cx=mr.left+mr.width/2,cy=mr.top+mr.height/2,dotR=mr.width/2;

    var pos=bestPos(cx,cy,dotR,popH);
    var lineX2=(cx>pos.left+PW/2)?pos.left:pos.left+PW;
    card.style.top=pos.top+'px';card.style.left=pos.left+'px';
    card.style.visibility='visible';
    ln.setAttribute('stroke',col);
    ln.setAttribute('x1',cx);ln.setAttribute('y1',cy);
    ln.setAttribute('x2',lineX2);ln.setAttribute('y2',pos.top+popH/2);
    ln.setAttribute('display','block');
  }

  document.addEventListener('click',function(e){
    var m=e.target.closest('.gw-marker');
    if(m){e.stopPropagation();show(m);}
    else if(!e.target.closest('#gw-card')){hide();}
  });

  /* Close card when map is panned (marker moves, card stays — confusing).
     Find the Leaflet map instance by scanning window after it initialises. */
  setTimeout(function(){
    var container=document.querySelector('.leaflet-container');
    if(!container) return;
    for(var k in window){
      try{
        var v=window[k];
        if(v&&v._container===container&&typeof v.on==='function'){
          v.on('movestart',hide);
          break;
        }
      }catch(e){}
    }
  },1200);
})();
</script>"""))

    # Encode full map HTML as a data URI so the iframe is self-contained
    map_full = m.get_root().render()
    map_b64  = base64.b64encode(map_full.encode("utf-8")).decode("ascii")
    return (
        f'<iframe src="data:text/html;base64,{map_b64}" '
        f'width="100%" height="500" style="border:none;display:block;"></iframe>'
    )


# ── Dashboard assembly ────────────────────────────────────────────────────────

# Shared light-editorial stylesheet used by both dashboard templates
_SHARED_CSS = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #faf9f7; color: #1c2024; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; font-size: 14px; }
    a { color: #2563eb; text-decoration: none; }
    header { background: #fff; border-bottom: 3px solid #16365c; padding: 20px 32px 16px;
      display: flex; align-items: baseline; gap: 20px; flex-wrap: wrap; }
    .brand { font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      font-size: 24px; font-weight: 700; color: #16365c; }
    .brand em { font-style: normal; color: #2563eb; }
    .loc { font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      font-size: 20px; color: #1c2024; font-style: italic; }
    .head-meta { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
    .chip { font-size: 11px; letter-spacing: 0.5px; padding: 4px 11px; border-radius: 999px;
      background: #f0efec; color: #55606c; font-weight: 600; white-space: nowrap; }
    .chip.blue { background: #e4edfb; color: #2563eb; }
    .alert-strip { background: #fef2f2; border-left: 4px solid #dc2626; border-bottom: 1px solid #e7e5e0;
      padding: 12px 32px; }
    .alert-strip b { color: #b91c1c; font-size: 12px; letter-spacing: 1.5px; text-transform: uppercase; }
    .alert-strip span { color: #55606c; font-size: 12.5px; margin-left: 10px; }
    .assess { background: #fff; border-bottom: 1px solid #e7e5e0; padding: 15px 32px;
      display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
      box-shadow: 0 1px 2px rgba(28,32,36,0.03); }
    .assess-label { font-size: 10.5px; letter-spacing: 2.5px; color: #98a1ab; font-weight: 700; }
    .conf-badge { font-size: 10.5px; font-weight: 700; letter-spacing: 1px;
      padding: 4px 11px; border-radius: 999px; }
    .assess-text { font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      font-size: 15.5px; color: #1c2024; }
    .assess-basis { font-size: 11.5px; color: #98a1ab; }
    main { padding: 24px 32px; display: grid; grid-template-columns: 1.55fr 1fr; gap: 20px;
      max-width: 1280px; margin: 0 auto; }
    .card { background: #fff; border: 1px solid #e7e5e0; border-radius: 10px;
      box-shadow: 0 1px 3px rgba(28,32,36,0.05), 0 8px 24px rgba(28,32,36,0.04); overflow: hidden; }
    .card-head { padding: 13px 18px; display: flex; align-items: baseline;
      justify-content: space-between; gap: 12px; border-bottom: 1px solid #e7e5e0; }
    .card-title { font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      font-size: 15.5px; font-weight: 700; color: #16365c; }
    .card-sub { font-size: 11.5px; color: #98a1ab; text-align: right; }
    .full { grid-column: 1 / -1; }
    /* timeline */
    .density { padding: 16px 22px 6px; }
    .weeks { display: flex; gap: 16px; align-items: flex-end; height: 136px; padding: 0 6px; }
    .wk { flex: 1; display: flex; flex-direction: column-reverse; gap: 2px; cursor: pointer;
      border-radius: 6px; padding: 5px 26px; transition: background .15s, box-shadow .15s; }
    .wk:hover { background: #f5f4f1; }
    .wk.sel { background: #eef3fa; box-shadow: inset 0 0 0 1.5px #2563eb; }
    .wk i { display: block; border-radius: 2px; }
    .wk-labels { display: flex; gap: 16px; padding: 7px 6px 0; }
    .wk-label { flex: 1; text-align: center; }
    .wk-label b { display: block; font-size: 11px; color: #55606c; font-weight: 600; }
    .wk-label span { font-size: 10px; color: #98a1ab; }
    .wk-days { display: none; margin-top: 12px; background: #fafbfc; border: 1px solid #e7e5e0;
      border-radius: 8px; padding: 12px 16px 8px; }
    .wk-days.open { display: block; animation: openup .2s ease; }
    @keyframes openup { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
    .wk-days-title { font-size: 11px; font-weight: 700; color: #16365c; margin-bottom: 8px; }
    .wk-days-title a { float: right; font-size: 11px; font-weight: 600; cursor: pointer; }
    .day-strip { display: flex; gap: 8px; align-items: flex-end; height: 52px; }
    .day { flex: 1; display: flex; flex-direction: column-reverse; gap: 1px; }
    .day i { display: block; border-radius: 1.5px; }
    .day.empty i { height: 3px; background: #e7e5e0; }
    .day-axis { display: flex; gap: 8px; padding-top: 5px; }
    .day-axis span { flex: 1; text-align: center; font-size: 9.5px; color: #98a1ab; }
    .density-legend { display: flex; gap: 13px; padding: 10px 6px 8px; font-size: 10.5px; color: #55606c; }
    .density-legend i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; margin-right: 4px; }
    /* event log */
    .feed { border-top: 1px solid #e7e5e0; }
    .feed.filtered .ev { display: none; }
    .feed.filtered .ev.show { display: grid; }
    .ev { display: grid; grid-template-columns: 76px 12px 1fr auto; gap: 0 14px; align-items: center;
      padding: 11px 22px; border-bottom: 1px solid #f1efeb; transition: background .1s; color: inherit; }
    .ev:last-child { border-bottom: none; }
    .ev:hover { background: #fafbfc; }
    .ev-date { font-size: 11px; color: #98a1ab; font-weight: 600; white-space: nowrap; }
    .ev-mark { width: 10px; height: 10px; border-radius: 50%; border: 2px solid #fff;
      box-shadow: 0 1px 3px rgba(28,32,36,.25); }
    .ev-main { min-width: 0; }
    .ev-title { display: block; font-size: 13px; color: #1c2024; font-weight: 500; line-height: 1.35;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ev-tags { display: flex; gap: 6px; margin-top: 3px; align-items: center; }
    .sev-pill { font-size: 9.5px; letter-spacing: 1px; font-weight: 700; padding: 1px 8px; border-radius: 999px; }
    .type-tag { font-size: 10.5px; color: #55606c; background: #f0efec; padding: 1px 9px;
      border-radius: 999px; font-weight: 600; }
    .ev-meta { font-size: 11px; color: #98a1ab; white-space: nowrap; display: flex; gap: 8px; align-items: center; }
    .grade { font-family: 'Cascadia Mono', Consolas, monospace; font-weight: 700; font-size: 10.5px;
      color: #16365c; background: #e8eef5; border-radius: 4px; padding: 1px 6px; }
    /* glance */
    .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: #e7e5e0;
      border-bottom: 1px solid #e7e5e0; }
    .stat { background: #fff; padding: 16px 18px; }
    .stat-num { font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, serif;
      font-size: 30px; font-weight: 700; color: #16365c; line-height: 1.1; }
    .stat-label { font-size: 11px; color: #98a1ab; margin-top: 3px; }
    .types { padding: 14px 18px 16px; display: flex; flex-direction: column; gap: 9px; }
    .type-row { display: grid; grid-template-columns: 96px 1fr 22px; gap: 12px; align-items: center; }
    .type-name { font-size: 12px; color: #55606c; font-weight: 600; }
    .type-bar { height: 7px; background: #f0efec; border-radius: 999px; overflow: hidden; }
    .type-bar i { display: block; height: 100%; border-radius: 999px; }
    .type-n { font-size: 11.5px; color: #98a1ab; text-align: right; font-weight: 600; }
    /* tables */
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; font-size: 10.5px; letter-spacing: 1.5px; color: #98a1ab; font-weight: 700;
      padding: 10px 18px; border-bottom: 2px solid #e7e5e0; }
    td { padding: 9px 18px; border-bottom: 1px solid #f1efeb; color: #55606c; }
    td:first-child { color: #1c2024; font-weight: 500; }
    tr:hover td { background: #fafbfc; }
    .rel { font-family: 'Cascadia Mono', Consolas, monospace; font-weight: 700; font-size: 11px;
      padding: 2px 8px; border-radius: 999px; }
    td.num { font-family: 'Cascadia Mono', Consolas, monospace; text-align: right; font-size: 12px; }
    .table-note { padding: 12px 18px 14px; font-size: 10.5px; color: #98a1ab; line-height: 1.5; }
    footer { color: #98a1ab; font-size: 11px; padding: 10px 32px 26px; text-align: center; }
    /* tabs (X Pulse) */
    .tabs { background: #fff; border-bottom: 1px solid #e7e5e0; padding: 10px 32px 0;
      display: flex; gap: 4px; }
    .tab { background: transparent; border: none; border-bottom: 2.5px solid transparent;
      color: #55606c; cursor: pointer; font-family: inherit; font-size: 13.5px; font-weight: 600;
      padding: 8px 18px 10px; transition: color .15s, border-color .15s; }
    .tab:hover { color: #16365c; }
    .tab.active { color: #16365c; border-bottom-color: #2563eb; }
    .tab-n { font-size: 10.5px; font-weight: 700; color: #2563eb; background: #e4edfb;
      border-radius: 999px; padding: 1px 8px; margin-left: 6px; vertical-align: 1px; }
    .tabpane { display: none; }
    .tabpane.open { display: block; }
    /* X Pulse pane */
    .xp-strip { display: flex; gap: 2px; align-items: flex-end; height: 64px;
      border-bottom: 1px solid #e7e5e0; padding: 0 2px 1px; }
    .xp-day { flex: 1; display: flex; flex-direction: column-reverse; }
    .xp-day i { display: block; border-radius: 1.5px 1.5px 0 0; }
    .xp-post .ev-title.xp-text { white-space: normal; line-height: 1.45; }
    .xp-verified { color: #2563eb; font-size: 10px; }
"""

_DASH_TMPL = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GeoWatch — __LOCATION__</title>
  <style>""" + _SHARED_CSS + """</style>
</head>
<body>
  __ALERT__
  <header>
    <div class="brand">Geo<em>Watch</em></div>
    <div class="loc">__LOCATION__ &mdash; last __DAYS__ days</div>
    <div class="head-meta">
      <span class="chip">__NREPORTS__ reports</span>
      <span class="chip">__NOUTLETS__ outlets</span>
      <span class="chip blue">Generated __TIMESTAMP__</span>
    </div>
  </header>

  __ASSESSMENT__

  __TABS__

  <div id="pane-news" class="tabpane open">
  <main>
    <div class="card">
      <div class="card-head"><span class="card-title">Operational Map</span><span class="card-sub">Clustered &middot; click a marker for the article</span></div>
      __MAP__
    </div>

    <div class="card">
      <div class="card-head"><span class="card-title">Situation at a Glance</span><span class="card-sub">This reporting period</span></div>
      __GLANCE__
    </div>

    <div class="card full">
      <div class="card-head"><span class="card-title">Event Timeline</span><span class="card-sub">One bar per week, stacked by severity &middot; click a week to see its days and events</span></div>
      __TIMELINE__
    </div>

    __ENTITY_SECTION__

    <div class="card full">
      <div class="card-head"><span class="card-title">Sourcing &amp; Reliability</span><span class="card-sub">NATO Admiralty System</span></div>
      __SOURCING__
    </div>
  </main>
  </div>

  __XPANE__

  <footer>Generated by GeoWatch &mdash; open-source geospatial intelligence &mdash; __TIMESTAMP__</footer>
</body>
</html>"""


def _entity_section_html(events: list[dict], title: str = "",
                         graph_id: str = "eg") -> str:
    """Return the entity graph section HTML, or empty string if too few entities."""
    cooc = build_entity_cooccurrence(events)
    if len(cooc["nodes"]) < 3:
        return ""
    graph = render_entity_graph_html(cooc, title, graph_id=graph_id)
    return (
        '<div class="card full">'
        '<div class="card-head"><span class="card-title">Entity Co-occurrence Network</span>'
        '<span class="card-sub">Node size = mentions &middot; color = worst associated severity</span></div>'
        f'<div style="background:#fff;">{graph}</div>'
        '</div>'
    )


def _entity_grid_html(
    events_a: list[dict], loc_a: str,
    events_b: list[dict], loc_b: str,
) -> str:
    """Return a two-column entity graph grid for comparison mode, or empty string if
    neither location has enough entities to render a graph."""
    cooc_a = build_entity_cooccurrence(events_a)
    cooc_b = build_entity_cooccurrence(events_b)
    has_a  = len(cooc_a["nodes"]) >= 3
    has_b  = len(cooc_b["nodes"]) >= 3

    if not has_a and not has_b:
        return ""

    graph_a = render_entity_graph_html(cooc_a, loc_a, graph_id="ega") if has_a else (
        f'<div style="color:#98a1ab;font-size:12px;padding:24px;text-align:center;">'
        f'Not enough entity data for {loc_a}</div>'
    )
    graph_b = render_entity_graph_html(cooc_b, loc_b, graph_id="egb") if has_b else (
        f'<div style="color:#98a1ab;font-size:12px;padding:24px;text-align:center;">'
        f'Not enough entity data for {loc_b}</div>'
    )

    return (
        '<div class="card full">'
        '<div class="card-head"><span class="card-title">Entity Co-occurrence Networks</span>'
        '<span class="card-sub">Node size = mentions &middot; color = worst associated severity</span></div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1px;background:#e7e5e0;">'
        f'<div style="background:#fff;">{graph_a}</div>'
        f'<div style="background:#fff;">{graph_b}</div>'
        '</div></div>'
    )


_TREND_OUTLOOK = {
    "Situation escalating":  "Continued elevated activity over the near term is likely (55–80%).",
    "Situation stabilizing": "Renewed near-term escalation is unlikely (20–45%).",
    "Situation stable":      "A significant near-term shift in tempo is unlikely (20–45%).",
    "No data":               "Insufficient reporting to assess trend.",
}

_CONF_PILL = {
    "high":     ("#1a7f37", "#d3f2dd"),
    "moderate": ("#9a6700", "#fbedc0"),
    "low":      ("#b91c1c", "#fcd9d9"),
}


def _assessment_html(events: list[dict], days: int) -> str:
    """Return the ICD 203 analytic assessment strip for the dashboard header."""
    trend = _compute_trend(events, days)
    outlook = _TREND_OUTLOOK.get(trend, _TREND_OUTLOOK["No data"])
    confidence, basis = assess_confidence(events)
    pt, pb = _CONF_PILL.get(confidence, _CONF_PILL["low"])

    if trend == "No data":
        assessment = outlook
        badge = ""
    else:
        assessment = f"{trend}. {outlook}"
        badge = (f'<span class="conf-badge" style="color:{pt};background:{pb}">'
                 f'{confidence.upper()} CONFIDENCE</span>')

    return (
        '<div class="assess">'
        '<span class="assess-label">ANALYTIC ASSESSMENT</span>'
        f'{badge}'
        f'<span class="assess-text">{assessment}</span>'
        f'<span class="assess-basis">Basis: {basis}. '
        'Estimative language per ICD 203; source grades per NATO Admiralty System.</span>'
        '</div>'
    )


def build_dashboard(events: list[dict], location: str, days: int,
                    alert: dict | None = None,
                    x_events: list[dict] | None = None,
                    x_status: str | None = None) -> str:
    """Return a fully self-contained dashboard HTML string (no external dependencies).

    When x_events/x_status are provided, the dashboard gains a tab bar with an
    "X Pulse" social-signal pane; when both are None, output is unchanged.
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    tabs_html, xpane_html = "", ""
    if x_events is not None or x_status is not None:
        n_posts = len(x_events or [])
        tabs_html = (
            '<nav class="tabs">'
            '<button class="tab active" data-pane="pane-news">News Analysis</button>'
            f'<button class="tab" data-pane="pane-xpulse">X Pulse'
            f'<span class="tab-n">{n_posts}</span></button>'
            '</nav>'
        )
        xpane_html = (
            '<div id="pane-xpulse" class="tabpane">'
            f'<main>{_x_tab_html(x_events, days, x_status)}</main>'
            '</div>'
            '<script>'
            'document.querySelectorAll(".tab").forEach(function(t){'
            't.addEventListener("click",function(){'
            'document.querySelectorAll(".tab").forEach(function(o){o.classList.remove("active");});'
            'document.querySelectorAll(".tabpane").forEach(function(p){p.classList.remove("open");});'
            't.classList.add("active");'
            'document.getElementById(t.dataset.pane).classList.add("open");'
            '});});'
            '</script>'
        )

    alert_html = ""
    if alert:
        pct_str = f"{alert['pct'] * 100:.0f}%"
        thr     = alert["threshold"].upper()
        alert_html = (
            '<div class="alert-strip">'
            f'<b>&#9888; Alert: Elevated Activity — {location}</b>'
            f'<span>{pct_str} of events in the last 7 days rated {thr} or above '
            f'({alert["count"]}/{alert["total"]} events)</span>'
            '</div>'
        )

    analyzed = [e for e in events if e.get("analysis")]
    outlets  = {
        (e.get("article", {}).get("source") or "").strip()
        for e in analyzed if e.get("article", {}).get("source")
    }

    return (
        _DASH_TMPL
        .replace("__ALERT__",      alert_html)
        .replace("__ASSESSMENT__", _assessment_html(events, days))
        .replace("__TABS__",       tabs_html)
        .replace("__XPANE__",      xpane_html)
        .replace("__LOCATION__",   location)
        .replace("__DAYS__",       str(days))
        .replace("__NREPORTS__",   str(len(analyzed)))
        .replace("__NOUTLETS__",   str(len(outlets)))
        .replace("__MAP__",             _map_iframe(events, location))
        .replace("__GLANCE__",          _glance_html(events))
        .replace("__TIMELINE__",        _timeline_html(events, days))
        .replace("__SOURCING__",        _sourcing_table_html(events))
        .replace("__ENTITY_SECTION__",  _entity_section_html(events))
        .replace("__TIMESTAMP__",       timestamp)
    )


# ── Comparison mode ───────────────────────────────────────────────────────────

_COLOR_A = "#0e7490"   # teal  — location A accent in summary/CSS
_COLOR_B = "#c2410c"   # burnt orange — location B accent in summary/CSS


def _compute_trend(events: list[dict], days: int) -> str:
    """Return 'Situation escalating / stabilizing / stable / No data' for events over days."""
    end   = datetime.utcnow()
    start = end - timedelta(days=days)
    weeks: list = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=7), end)
        weeks.append((cur, nxt))
        cur = nxt

    counts = {s: [0] * len(weeks) for s in _SEV_ORDER}
    for ev in events:
        analysis = ev.get("analysis")
        if not analysis:
            continue
        try:
            dt = datetime.strptime(ev.get("article", {}).get("date", ""), "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        sev = analysis.get("severity", "low").lower()
        if sev not in counts:
            sev = "low"
        for i, (ws, we) in enumerate(weeks):
            if ws <= dt < we or (i == len(weeks) - 1 and dt >= ws):
                counts[sev][i] += 1
                break

    mid    = max(1, len(weeks) // 2)
    first  = sum(_SEV_WEIGHT[s] * sum(counts[s][:mid]) for s in _SEV_ORDER)
    second = sum(_SEV_WEIGHT[s] * sum(counts[s][mid:]) for s in _SEV_ORDER)

    if first == 0 and second == 0:
        return "No data"
    if first == 0:
        return "Situation escalating"
    if (second - first) / first > 0.20:
        return "Situation escalating"
    if (first - second) / first > 0.20:
        return "Situation stabilizing"
    return "Situation stable"


def _comparison_severity_b64(
    events_a: list[dict], events_b: list[dict],
    loc_a: str, loc_b: str, days: int,
) -> str:
    """Two stacked-bar subplots sharing x-axis — same green→red severity palette for both."""
    end   = datetime.utcnow()
    start = end - timedelta(days=days)
    weeks: list = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=7), end)
        weeks.append((cur, nxt))
        cur = nxt
    week_labels = [w[0].strftime("%b %d") for w in weeks]

    def _count(events):
        c = {s: [0] * len(weeks) for s in _SEV_ORDER}
        for ev in events:
            a = ev.get("analysis")
            if not a:
                continue
            try:
                dt = datetime.strptime(ev.get("article", {}).get("date", ""), "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            sev = a.get("severity", "low").lower()
            if sev not in c:
                sev = "low"
            for i, (ws, we) in enumerate(weeks):
                if ws <= dt < we or (i == len(weeks) - 1 and dt >= ws):
                    c[sev][i] += 1
                    break
        return c

    ca, cb = _count(events_a), _count(events_b)
    n = len(weeks)
    x = np.arange(n)

    fig, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(14, 7), sharex=True,
                                      gridspec_kw={"hspace": 0.08})
    fig.patch.set_facecolor(_BG)

    for ax, counts, title in [(ax_a, ca, loc_a), (ax_b, cb, loc_b)]:
        ax.set_facecolor(_BG)
        bot = np.zeros(n)
        for sev in _SEV_ORDER:
            v = np.array(counts[sev], dtype=float)
            if v.sum() > 0:
                ax.bar(x, v, bottom=bot, color=_SEV_MPL[sev],
                       label=sev.capitalize(), width=0.65, zorder=2)
            bot += v
        ax.set_ylabel("Events", color=_TEXT, fontsize=9)
        ax.yaxis.set_tick_params(labelcolor=_TEXT, length=0)
        ax.tick_params(axis="x", colors=_TEXT, length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.spines["bottom"].set_visible(True)
        ax.spines["bottom"].set_color(_RULE)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color=_RULE, linewidth=0.8)
        ax.text(0.01, 0.94, title, transform=ax.transAxes,
                color=_TEXT, fontsize=11, fontweight="bold",
                va="top", ha="left")

    ax_a.legend(loc="upper right", framealpha=0.9, facecolor="#ffffff",
                edgecolor=_RULE, labelcolor=_TEXT, fontsize=9)
    ax_b.set_xticks(x)
    ax_b.set_xticklabels(week_labels, color=_TEXT, fontsize=8)

    fig.subplots_adjust(left=0.06, right=0.99, top=0.97, bottom=0.08, hspace=0.08)
    return _fig_to_b64(fig)


def _combined_map_iframe(
    events_a: list[dict], loc_a: str,
    events_b: list[dict], loc_b: str,
) -> str:
    """Single Folium map with both locations.
    loc_a markers: solid filled dot (standard style).
    loc_b markers: ring/hollow dot (same severity color, transparent fill).
    Severity color (green→red) is preserved for both.
    """
    # Pick map center: midpoint of the two known region centers
    center_a = REGION_COORDS.get(loc_a, (20.0, 0.0))
    center_b = REGION_COORDS.get(loc_b, (20.0, 0.0))
    mid_lat  = (center_a[0] + center_b[0]) / 2
    mid_lon  = (center_a[1] + center_b[1]) / 2

    # Auto-zoom: if centers are far apart zoom out, else closer in
    lat_d = abs(center_a[0] - center_b[0])
    lon_d = abs(center_a[1] - center_b[1])
    span  = max(lat_d, lon_d)
    if span < 10:
        zoom = 6
    elif span < 30:
        zoom = 4
    elif span < 80:
        zoom = 3
    else:
        zoom = 2

    m = folium.Map(location=(mid_lat, mid_lon), zoom_start=zoom,
                   tiles="CartoDB positron")

    cluster_a = MarkerCluster(name=loc_a).add_to(m)
    cluster_b = MarkerCluster(name=loc_b).add_to(m)

    def _add_markers(events, center, cluster, style: str):
        for ev in events:
            analysis = ev.get("analysis")
            article  = ev.get("article", {})
            if not analysis:
                continue
            sev   = analysis.get("severity", "low").lower()
            color = _SEV_CSS.get(sev, _BLUE)
            data_attrs = " ".join(
                f'data-{k}="{_html.escape(str(v))}"'
                for k, v in {
                    "title":  analysis.get("one_line_summary", ""),
                    "source": article.get("source", ""),
                    "date":   article.get("date", ""),
                    "url":    article.get("url", ""),
                    "image":  article.get("image_url") or "",
                    "sev":    sev,
                    "etype":  analysis.get("event_type", ""),
                    "grade":  grade_event(ev),
                    "gradedesc": describe_grade(grade_event(ev)),
                }.items()
            )
            if style == "solid":
                icon_html = (
                    f'<div class="gw-marker" {data_attrs} '
                    f'style="width:13px;height:13px;border-radius:50%;cursor:pointer;'
                    f'background:{color};border:2px solid #fff;'
                    f'box-shadow:0 1px 4px rgba(28,32,36,0.35);"></div>'
                )
            else:  # ring
                icon_html = (
                    f'<div class="gw-marker" {data_attrs} '
                    f'style="width:15px;height:15px;border-radius:50%;cursor:pointer;'
                    f'background:#fff;border:3px solid {color};'
                    f'box-shadow:0 1px 4px rgba(28,32,36,0.35);"></div>'
                )
            folium.Marker(
                location=center,
                icon=folium.DivIcon(html=icon_html, icon_size=(15, 15), icon_anchor=(7, 7)),
                tooltip=analysis.get("one_line_summary", article.get("title", "")),
            ).add_to(cluster)

    _add_markers(events_a, center_a, cluster_a, "solid")
    _add_markers(events_b, center_b, cluster_b, "ring")

    # Legend: severity + location identity key
    legend_html = (
        '<div style="position:fixed;bottom:20px;left:20px;z-index:9998;'
        'background:rgba(255,255,255,0.94);border:1px solid #e7e5e0;border-radius:8px;'
        'padding:10px 14px;font-family:\'Segoe UI\',system-ui,sans-serif;font-size:11px;'
        'color:#55606c;line-height:1.9;box-shadow:0 2px 8px rgba(28,32,36,0.1);">'
        '<div style="color:#16365c;font-size:9.5px;letter-spacing:1.5px;font-weight:700;'
        'text-transform:uppercase;margin-bottom:4px;">Severity</div>'
        + "".join(
            f'<div><span style="display:inline-block;width:10px;height:10px;'
            f'border-radius:50%;background:{_SEV_CSS[s]};margin-right:6px;'
            f'vertical-align:middle;"></span>{s.capitalize()}</div>'
            for s in reversed(_SEV_ORDER)
        )
        + '<div style="border-top:1px solid #e7e5e0;margin:7px 0 5px;"></div>'
        '<div style="color:#16365c;font-size:9.5px;letter-spacing:1.5px;font-weight:700;'
        'text-transform:uppercase;margin-bottom:4px;">Location</div>'
        f'<div><span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:#98a1ab;border:2px solid #fff;'
        f'margin-right:6px;vertical-align:middle;"></span>{loc_a} (solid)</div>'
        f'<div><span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:transparent;border:3px solid #98a1ab;'
        f'margin-right:6px;vertical-align:middle;"></span>{loc_b} (ring)</div>'
        '</div>'
    )
    m.get_root().html.add_child(Element(legend_html))

    # Reuse the same pull-out card + JS from _map_iframe
    m.get_root().html.add_child(Element("""
<style>
.marker-cluster-small, .marker-cluster-medium, .marker-cluster-large { background: rgba(22,54,92,0.25) !important; }
.marker-cluster-small div, .marker-cluster-medium div, .marker-cluster-large div {
  background: rgba(22,54,92,0.9) !important; color: #fff !important;
  font-family: 'Segoe UI', system-ui, sans-serif !important; font-weight: 600;
}
.marker-cluster span { color: #fff !important; }
.leaflet-container { font-family: 'Segoe UI', system-ui, sans-serif; }
</style>
<svg id="gw-svg" style="position:fixed;top:0;left:0;width:100vw;height:100vh;
  pointer-events:none;z-index:9997;overflow:visible;">
  <line id="gw-line" x1="0" y1="0" x2="0" y2="0"
    stroke-width="1.5" stroke-opacity="0.7" display="none"/>
</svg>
<div id="gw-card" style="display:none;position:fixed;z-index:9999;width:200px;
  background:#fff;border-radius:8px;
  box-shadow:0 4px 20px rgba(0,0,0,0.22),0 0 0 1px rgba(0,0,0,0.07);
  overflow:hidden;font-family:'Segoe UI',system-ui,sans-serif;" onclick="event.stopPropagation()">
  <div style="position:relative;width:100%;height:100px;">
    <div style="position:absolute;top:0;left:0;right:0;bottom:0;background:#f0f2f5;
      display:flex;align-items:center;justify-content:center;
      color:#aaa;font-size:9px;letter-spacing:1px;">NO IMAGE AVAILABLE</div>
    <img id="gw-img" alt="" referrerpolicy="no-referrer"
      onerror="this.style.display='none'"
      style="position:absolute;top:0;left:0;width:100%;height:100%;
      object-fit:cover;display:none;z-index:1;">
    <div id="gw-badge" style="position:absolute;top:6px;left:6px;z-index:2;
      border-radius:3px;padding:2px 5px;font-size:8px;letter-spacing:1px;
      text-transform:uppercase;background:rgba(0,0,0,0.65);color:#fff;"></div>
  </div>
  <div style="padding:8px 10px 10px;cursor:pointer;" onclick="gwOpen()">
    <div id="gw-title" style="color:#111;font-weight:bold;font-size:10.5px;
      line-height:1.4;margin-bottom:4px;"></div>
    <div id="gw-meta" style="color:#999;font-size:9px;margin-bottom:6px;"></div>
    <span style="color:#1a6ef5;font-size:9px;">&#x1F517; Read article</span>
  </div>
</div>
<script>
(function(){
  var SEV={low:'#1a7f37',medium:'#d4a72c',high:'#ea7317',critical:'#dc2626'};
  var PW=200,M=12,GAP=14,curUrl='',activeEl=null;
  function hide(){
    document.getElementById('gw-card').style.display='none';
    document.getElementById('gw-line').setAttribute('display','none');
    activeEl=null;
  }
  window.gwOpen=function(){if(curUrl)window.open(curUrl,'_blank');};
  var obs=new IntersectionObserver(function(entries){
    entries.forEach(function(e){ if(!e.isIntersecting && e.target===activeEl) hide(); });
  },{threshold:0.1});
  function bestPos(cx,cy,dotR,popH){
    var candidates=[
      {left:cx+dotR+GAP,top:cy-popH/2},
      {left:cx-dotR-GAP-PW,top:cy-popH/2},
      {left:cx-PW/2,top:cy+dotR+GAP},
      {left:cx-PW/2,top:cy-dotR-GAP-popH},
    ];
    var dots=document.querySelectorAll('.gw-marker');
    function pen(c){
      var p=0;
      if(c.left<M||c.left+PW>window.innerWidth-M) p+=40;
      if(c.top<M||c.top+popH>window.innerHeight-M) p+=40;
      dots.forEach(function(d){
        if(d===activeEl) return;
        var r=d.getBoundingClientRect();
        var dx=r.left+r.width/2,dy=r.top+r.height/2;
        if(dx>c.left&&dx<c.left+PW&&dy>c.top&&dy<c.top+popH) p+=6;
      });
      return p;
    }
    var best=candidates.reduce(function(a,b){return pen(a)<=pen(b)?a:b;});
    best.left=Math.max(M,Math.min(best.left,window.innerWidth-PW-M));
    best.top=Math.max(M,Math.min(best.top,window.innerHeight-popH-M));
    return best;
  }
  function show(el){
    if(el===activeEl){hide();return;}
    if(activeEl) obs.unobserve(activeEl);
    activeEl=el; obs.observe(el);
    var d=el.dataset,card=document.getElementById('gw-card'),
        ln=document.getElementById('gw-line');
    curUrl=d.url||'';
    var img=document.getElementById('gw-img');
    if(d.image){img.style.display='block';img.src=d.image;}
    else{img.style.display='none';}
    var badge=document.getElementById('gw-badge');
    badge.textContent=(d.etype||'').replace(/_/g,' ');
    badge.style.color=SEV[d.sev]||'#888';
    document.getElementById('gw-title').textContent=d.title||'';
    var meta=document.getElementById('gw-meta');
    meta.textContent=(d.source||'')+(d.date?' · '+d.date:'')+(d.grade?' · '+d.grade:'');
    meta.title=d.gradedesc||'';
    var col=SEV[d.sev]||'#888';
    card.style.display='block';card.style.visibility='hidden';
    var popH=card.offsetHeight;
    var mr=el.getBoundingClientRect();
    var cx=mr.left+mr.width/2,cy=mr.top+mr.height/2,dotR=mr.width/2;
    var pos=bestPos(cx,cy,dotR,popH);
    var lineX2=(cx>pos.left+PW/2)?pos.left:pos.left+PW;
    card.style.top=pos.top+'px';card.style.left=pos.left+'px';
    card.style.visibility='visible';
    ln.setAttribute('stroke',col);
    ln.setAttribute('x1',cx);ln.setAttribute('y1',cy);
    ln.setAttribute('x2',lineX2);ln.setAttribute('y2',pos.top+popH/2);
    ln.setAttribute('display','block');
  }
  document.addEventListener('click',function(e){
    var m=e.target.closest('.gw-marker');
    if(m){e.stopPropagation();show(m);}
    else if(!e.target.closest('#gw-card')){hide();}
  });
  setTimeout(function(){
    var container=document.querySelector('.leaflet-container');
    if(!container) return;
    for(var k in window){
      try{
        var v=window[k];
        if(v&&v._container===container&&typeof v.on==='function'){
          v.on('movestart',hide); break;
        }
      }catch(e){}
    }
  },1200);
})();
</script>"""))

    map_full = m.get_root().render()
    map_b64  = base64.b64encode(map_full.encode("utf-8")).decode("ascii")
    return (
        f'<iframe src="data:text/html;base64,{map_b64}" '
        f'width="100%" height="520" style="border:none;display:block;"></iframe>'
    )


def _comparison_summary_html(
    events_a: list[dict], events_b: list[dict],
    loc_a: str, loc_b: str, days: int,
) -> str:
    """Summary card: article counts, event-type bars, and key-differences bullets."""

    def _stats(events):
        analyzed = [e for e in events if e.get("analysis")]
        sev_c = Counter(
            e["analysis"]["severity"]
            for e in analyzed if e["analysis"].get("severity")
        )
        evt_c = Counter(
            e["analysis"]["event_type"]
            for e in analyzed if e["analysis"].get("event_type")
        )
        total = len(analyzed)
        w_sum = sum(_SEV_WEIGHT.get(s, 1) * c for s, c in sev_c.items())
        return {"total": total, "sev": sev_c, "evt": evt_c,
                "avg": w_sum / total if total else 0}

    sa, sb = _stats(events_a), _stats(events_b)
    ta = _compute_trend(events_a, days)
    tb = _compute_trend(events_b, days)

    def _tag(t):
        if "escalat"  in t.lower(): return "▲ escalating"
        if "stabiliz" in t.lower(): return "▼ stabilizing"
        return "● stable"

    def _bars(stats, accent):
        total = sum(stats["evt"].values()) or 1
        out = ""
        for etype, cnt in sorted(stats["evt"].items(), key=lambda x: -x[1])[:6]:
            pct   = cnt / total * 100
            label = etype.replace("_", " ").capitalize()
            out += (
                f'<div style="margin-bottom:7px;">'
                f'<div style="display:flex;justify-content:space-between;'
                f'color:#55606c;font-size:11px;margin-bottom:3px;">'
                f'<span>{label}</span><span>{cnt}</span></div>'
                f'<div style="background:#f0efec;border-radius:999px;height:6px;">'
                f'<div style="background:{accent};border-radius:999px;height:6px;'
                f'width:{pct:.1f}%;"></div></div></div>'
            )
        return out or '<div style="color:#98a1ab;font-size:11px;">No data</div>'

    bullets = []
    if sa["avg"] > sb["avg"] + 0.3:
        bullets.append(f"{loc_a} shows higher average severity than {loc_b}")
    elif sb["avg"] > sa["avg"] + 0.3:
        bullets.append(f"{loc_b} shows higher average severity than {loc_a}")
    else:
        bullets.append(f"Average severity is comparable between {loc_a} and {loc_b}")

    if sb["total"] > 0 and sa["total"] > sb["total"] * 1.5:
        bullets.append(
            f"{loc_a} has substantially more media coverage "
            f"({sa['total']} vs {sb['total']} articles)"
        )
    elif sa["total"] > 0 and sb["total"] > sa["total"] * 1.5:
        bullets.append(
            f"{loc_b} has substantially more media coverage "
            f"({sb['total']} vs {sa['total']} articles)"
        )

    def _top(stats):
        return stats["evt"].most_common(1)[0][0].replace("_", " ") if stats["evt"] else None

    top_a, top_b = _top(sa), _top(sb)
    if top_a and top_b:
        if top_a != top_b:
            bullets.append(f"Dominant event: {loc_a} → {top_a} | {loc_b} → {top_b}")
        else:
            bullets.append(f"Both regions show predominantly {top_a} events")

    if "escalat" in ta.lower() and "stable" in tb.lower():
        bullets.append(f"{loc_a} is escalating while {loc_b} remains stable")
    elif "escalat" in tb.lower() and "stable" in ta.lower():
        bullets.append(f"{loc_b} is escalating while {loc_a} remains stable")
    elif "escalat" in ta.lower() and "escalat" in tb.lower():
        bullets.append("Both regions show escalating trends")

    bullets_html = "".join(
        f'<li style="margin-bottom:8px;color:#55606c;font-size:12.5px;">{b}</li>'
        for b in bullets
    )

    return f"""
<div class="card full">
  <div class="card-head"><span class="card-title">Comparison Summary</span></div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:32px;padding:18px 22px;">
    <div>
      <div style="color:{_COLOR_A};font-size:14px;font-weight:700;margin-bottom:6px;">{loc_a}</div>
      <div style="color:#98a1ab;font-size:11.5px;margin-bottom:12px;">
        {sa['total']} articles &middot; {_tag(ta)}</div>
      <div style="color:#98a1ab;font-size:10px;letter-spacing:1.5px;
        text-transform:uppercase;font-weight:700;margin-bottom:8px;">Event breakdown</div>
      {_bars(sa, _COLOR_A)}
    </div>
    <div>
      <div style="color:{_COLOR_B};font-size:14px;font-weight:700;margin-bottom:6px;">{loc_b}</div>
      <div style="color:#98a1ab;font-size:11.5px;margin-bottom:12px;">
        {sb['total']} articles &middot; {_tag(tb)}</div>
      <div style="color:#98a1ab;font-size:10px;letter-spacing:1.5px;
        text-transform:uppercase;font-weight:700;margin-bottom:8px;">Event breakdown</div>
      {_bars(sb, _COLOR_B)}
    </div>
  </div>
  <div style="border-top:1px solid #e7e5e0;padding:14px 22px 18px;">
    <div style="color:#98a1ab;font-size:10px;letter-spacing:1.5px;
      text-transform:uppercase;font-weight:700;margin-bottom:10px;">Key differences</div>
    <ul style="list-style:disc;padding-left:20px;">{bullets_html}</ul>
  </div>
</div>"""


_COMP_TMPL = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GeoWatch &mdash; __LOC_A__ vs __LOC_B__</title>
  <style>""" + _SHARED_CSS + """
    .loc-a { color: """ + _COLOR_A + """; font-weight: 600; }
    .loc-b { color: """ + _COLOR_B + """; font-weight: 600; }
    .chart-wrap { padding: 18px 22px; }
    .chart-wrap img { display: block; max-width: 100%; width: 100%; }
    .trend-row { display: flex; gap: 40px; padding: 0 22px 16px; }
    .trend-cell { color: #55606c; font-size: 12.5px; }
  </style>
</head>
<body>
  <header>
    <div class="brand">Geo<em>Watch</em></div>
    <div class="loc">__LOC_A__ vs __LOC_B__ &mdash; last __DAYS__ days</div>
    <div class="head-meta">
      <span class="chip blue">Comparative analysis &middot; __TIMESTAMP__</span>
    </div>
  </header>

  <main>
    <div class="card full">
      <div class="card-head"><span class="card-title">Combined Map</span>
        <span class="card-sub"><span class="loc-a">__LOC_A__</span> solid &middot; <span class="loc-b">__LOC_B__</span> ring &middot; color = severity</span></div>
      __COMBINED_MAP__
    </div>

    <div class="card full">
      <div class="card-head"><span class="card-title">Severity Escalation</span><span class="card-sub">Weekly, stacked &middot; same scale for both</span></div>
      <div class="chart-wrap">
        <img src="data:image/png;base64,__COMP_TIMELINE__" alt="Comparison Timeline">
      </div>
      <div class="trend-row">
        <div class="trend-cell"><span class="loc-a">__LOC_A__</span>: __TREND_A__</div>
        <div class="trend-cell"><span class="loc-b">__LOC_B__</span>: __TREND_B__</div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><span class="card-title"><span class="loc-a">__LOC_A__</span> &mdash; Event Log</span></div>
      __LOG_A__
    </div>

    <div class="card">
      <div class="card-head"><span class="card-title"><span class="loc-b">__LOC_B__</span> &mdash; Event Log</span></div>
      __LOG_B__
    </div>

    __ENTITY_GRID__

    __COMPARISON_SUMMARY__
  </main>

  <footer>Generated by GeoWatch &mdash; open-source geospatial intelligence &mdash; __TIMESTAMP__</footer>
</body>
</html>"""


def build_comparison_dashboard(
    loc_a: str, events_a: list[dict],
    loc_b: str, events_b: list[dict],
    days: int,
) -> str:
    """Return a fully self-contained two-location comparison dashboard HTML string."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    trend_a = _compute_trend(events_a, days)
    trend_b = _compute_trend(events_b, days)

    def _trend_label(t: str) -> str:
        if "escalat"  in t.lower(): return f"{t} ▲"
        if "stabiliz" in t.lower(): return f"{t} ▼"
        return f"{t} ●"

    return (
        _COMP_TMPL
        .replace("__LOC_A__",              loc_a)
        .replace("__LOC_B__",              loc_b)
        .replace("__DAYS__",               str(days))
        .replace("__COMBINED_MAP__",        _combined_map_iframe(
                                               events_a, loc_a, events_b, loc_b))
        .replace("__COMP_TIMELINE__",      _comparison_severity_b64(
                                               events_a, events_b, loc_a, loc_b, days))
        .replace("__TREND_A__",            _trend_label(trend_a))
        .replace("__TREND_B__",            _trend_label(trend_b))
        .replace("__LOG_A__",              _event_log_html(events_a, days))
        .replace("__LOG_B__",              _event_log_html(events_b, days))
        .replace("__ENTITY_GRID__",         _entity_grid_html(events_a, loc_a, events_b, loc_b))
        .replace("__COMPARISON_SUMMARY__", _comparison_summary_html(
                                               events_a, events_b, loc_a, loc_b, days))
        .replace("__TIMESTAMP__",          timestamp)
    )
