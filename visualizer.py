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

_SEV_ORDER = ["low", "medium", "high", "critical"]
_SEV_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_SEV_MPL = {
    "low": "#2ea44f",
    "medium": "#e3b341",
    "high": "#f97316",
    "critical": "#ef4444",
}
_SEV_CSS = {
    "low": "#2ea44f",
    "medium": "#e3b341",
    "high": "#f97316",
    "critical": "#ef4444",
}
_EVENT_TYPES = [
    "conflict", "political", "natural_disaster", "economic",
    "protest", "terrorism", "other",
]
_BG    = "#0d1117"
_TEXT  = "#c8d6e5"
_GRID  = "#1e2535"


def _fig_to_b64(fig: plt.Figure) -> str:
    """Serialize a Matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150, facecolor=_BG)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


# ── Chart 1: Severity Escalation Timeline ────────────────────────────────────

def severity_timeline_b64(events: list[dict], days: int) -> str:
    """Weekly stacked severity bar chart with trend label. Returns base64 PNG."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)

    weeks: list[tuple] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=7), end)
        weeks.append((cur, nxt))
        cur = nxt

    week_labels = [w[0].strftime("%b %d") for w in weeks]
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

    # Weighted severity score: first half vs second half
    mid = max(1, len(weeks) // 2)
    first  = sum(_SEV_WEIGHT[s] * sum(counts[s][:mid]) for s in _SEV_ORDER)
    second = sum(_SEV_WEIGHT[s] * sum(counts[s][mid:]) for s in _SEV_ORDER)

    if first == 0 and second == 0:
        trend = "No data to assess trend"
    elif first == 0:
        trend = "Situation escalating"
    elif (second - first) / first > 0.20:
        trend = "Situation escalating"
    elif (first - second) / first > 0.20:
        trend = "Situation stabilizing"
    else:
        trend = "Situation stable"

    fig, ax = plt.subplots(figsize=(14, 4.5))
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)

    x = np.arange(len(weeks))
    bottom = np.zeros(len(weeks))
    for sev in _SEV_ORDER:
        vals = np.array(counts[sev], dtype=float)
        if vals.sum() > 0:
            ax.bar(x, vals, bottom=bottom, color=_SEV_MPL[sev],
                   label=sev.capitalize(), width=0.65, zorder=2)
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels(week_labels, color=_TEXT, fontsize=9)
    ax.tick_params(axis="both", colors=_TEXT, length=0)
    ax.set_ylabel("Events", color=_TEXT, fontsize=10)
    ax.yaxis.set_tick_params(labelcolor=_TEXT)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color(_GRID)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.8)
    ax.set_title(trend, color=_TEXT, fontsize=13, fontweight="bold", pad=14)
    ax.legend(loc="upper right", framealpha=0.15, facecolor="#1a2030",
              edgecolor=_GRID, labelcolor=_TEXT, fontsize=9)

    fig.tight_layout()
    return _fig_to_b64(fig)


# ── Chart 2: Event Type Swimlane (interactive HTML/JS) ───────────────────────

_SWIMLANE_JS = """\
<script>
(function(){
  var popup  = document.getElementById('sw-popup');
  var svgLn  = document.getElementById('sw-svg-line');
  var curUrl = '', activeDot = null;
  var SEV = {low:'#2ea44f', medium:'#e3b341', high:'#f97316', critical:'#ef4444'};
  var PW = 200, M = 12, GAP = 14;

  function hide() {
    popup.style.display = 'none';
    svgLn.setAttribute('display', 'none');
    activeDot = null;
  }

  window.swImgErr = function() { document.getElementById('sw-img').style.display = 'none'; };
  window.swOpen   = function(e) { if (e) e.stopPropagation(); if (curUrl) window.open(curUrl,'_blank'); };

  /* Close on outside click */
  document.addEventListener('click', hide);

  /* Close when the page is scrolled (card is fixed, dots move) */
  window.addEventListener('scroll', hide, {passive: true});

  /* Close when swimlane is scrolled horizontally so the dot leaves the visible area */
  var swScroll = document.querySelector('.sw-scroll');
  if (swScroll) {
    swScroll.addEventListener('scroll', function() {
      if (!activeDot) return;
      var dr = activeDot.getBoundingClientRect();
      var cr = swScroll.getBoundingClientRect();
      if (dr.right < cr.left || dr.left > cr.right) hide();
    }, {passive: true});
  }

  /* Pick the card position (right/left/below/above) that overlaps fewest other dots */
  function bestPos(cx, cy, dotR, popH) {
    var candidates = [
      {left: cx + dotR + GAP,       top: cy - popH / 2},
      {left: cx - dotR - GAP - PW,  top: cy - popH / 2},
      {left: cx - PW / 2,           top: cy + dotR + GAP},
      {left: cx - PW / 2,           top: cy - dotR - GAP - popH},
    ];
    var dots = document.querySelectorAll('.sw-dot');
    function penalty(c) {
      var p = 0;
      if (c.left < M || c.left + PW > window.innerWidth  - M) p += 40;
      if (c.top  < M || c.top + popH > window.innerHeight - M) p += 40;
      dots.forEach(function(d) {
        if (d === activeDot) return;
        var r  = d.getBoundingClientRect();
        var dx = r.left + r.width / 2, dy = r.top + r.height / 2;
        if (dx > c.left && dx < c.left + PW && dy > c.top && dy < c.top + popH) p += 6;
      });
      return p;
    }
    var best = candidates.reduce(function(a, b) { return penalty(a) <= penalty(b) ? a : b; });
    best.left = Math.max(M, Math.min(best.left, window.innerWidth  - PW - M));
    best.top  = Math.max(M, Math.min(best.top,  window.innerHeight - popH - M));
    return best;
  }

  window.swShow = function(dot, e) {
    if (e) e.stopPropagation();
    if (dot === activeDot) { hide(); return; }   /* same dot → toggle off */
    activeDot = dot;
    var d = dot.dataset;
    curUrl = d.url || '';

    var img = document.getElementById('sw-img');
    if (d.image) { img.style.display = 'block'; img.src = d.image; }
    else          { img.style.display = 'none'; }

    var badge = document.getElementById('sw-badge');
    badge.textContent = (d.etype || '').replace(/_/g, ' ');
    badge.style.color = SEV[d.severity] || '#888';

    document.getElementById('sw-title').textContent = d.title   || '';
    document.getElementById('sw-sum').textContent   = d.summary || '';
    document.getElementById('sw-meta').textContent  =
      (d.source || '') + (d.date ? ' · ' + d.date : '');

    var col = SEV[d.severity] || '#888';
    popup.style.display = 'block'; popup.style.visibility = 'hidden';
    var popH = popup.offsetHeight;

    var dr   = dot.getBoundingClientRect();
    var cx   = dr.left + dr.width / 2;
    var cy   = dr.top  + dr.height / 2;
    var dotR = dr.width / 2;

    var pos    = bestPos(cx, cy, dotR, popH);
    var lineX2 = (cx > pos.left + PW / 2) ? pos.left : pos.left + PW;
    var lineY2 = pos.top + popH / 2;

    popup.style.top  = pos.top  + 'px';
    popup.style.left = pos.left + 'px';
    popup.style.visibility = 'visible';

    svgLn.setAttribute('stroke', col);
    svgLn.setAttribute('x1', cx);     svgLn.setAttribute('y1', cy);
    svgLn.setAttribute('x2', lineX2); svgLn.setAttribute('y2', lineY2);
    svgLn.setAttribute('display', 'block');
  };
})();
</script>"""

# SVG overlay for the connecting line + the card itself.
# Card always appears on the opposite side of the viewport from the clicked dot,
# so the dot and its neighbours stay fully clickable.
_SWIMLANE_POPUP = (
    # Full-viewport SVG layer for the connecting line (pointer-events:none so it
    # never blocks clicks on dots or the rest of the page)
    '<svg id="sw-svg" style="position:fixed;top:0;left:0;'
    'width:100vw;height:100vh;pointer-events:none;z-index:9997;overflow:visible;">'
    '<line id="sw-svg-line" x1="0" y1="0" x2="0" y2="0"'
    ' stroke-width="1.5" stroke-opacity="0.7" display="none"/>'
    '</svg>'
    # Card
    '<div id="sw-popup" style="display:none;position:fixed;z-index:9999;width:200px;'
    'background:#fff;border-radius:8px;'
    "box-shadow:0 4px 20px rgba(0,0,0,0.22),0 0 0 1px rgba(0,0,0,0.07);"
    "overflow:hidden;font-family:'Courier New',monospace;"
    '" onclick="swOpen(event)">'
    '<div style="position:relative;width:100%;height:100px;">'
    '<div style="position:absolute;top:0;left:0;right:0;bottom:0;background:#f0f2f5;'
    'display:flex;align-items:center;justify-content:center;'
    'color:#aaa;font-size:9px;letter-spacing:1px;">NO IMAGE AVAILABLE</div>'
    '<img id="sw-img" alt="" referrerpolicy="no-referrer" onerror="swImgErr()"'
    ' style="position:absolute;top:0;left:0;width:100%;height:100%;'
    'object-fit:cover;display:none;z-index:1;">'
    '<div id="sw-badge" style="position:absolute;top:6px;left:6px;z-index:2;'
    'border-radius:3px;padding:2px 5px;font-size:8px;letter-spacing:1px;'
    'text-transform:uppercase;background:rgba(0,0,0,0.65);color:#fff;"></div>'
    '</div>'
    '<div style="padding:8px 10px 10px;cursor:pointer;">'
    '<div id="sw-title" style="color:#111;font-weight:bold;font-size:10.5px;'
    'line-height:1.4;margin-bottom:4px;"></div>'
    '<div id="sw-sum" style="color:#555;font-size:9.5px;line-height:1.35;'
    'margin-bottom:6px;"></div>'
    '<div id="sw-meta" style="color:#999;font-size:9px;"></div>'
    '</div></div>'
)


def event_swimlane_html(events: list[dict], days: int) -> str:
    """Interactive swimlane chart — HTML/JS with hover popups. Returns an HTML string."""
    end        = datetime.utcnow()
    start      = end - timedelta(days=days)
    total_days = max(1, days)

    _DOT_R = {"low": 8, "medium": 12, "high": 17, "critical": 23}

    type_date: dict = defaultdict(lambda: defaultdict(list))
    for ev in events:
        analysis = ev.get("analysis")
        if not analysis:
            continue
        etype    = analysis.get("event_type", "other").lower()
        sev      = analysis.get("severity",   "low").lower()
        date_str = ev.get("article", {}).get("date", "")
        if etype not in _EVENT_TYPES:
            etype = "other"
        art = ev.get("article", {})
        type_date[etype][date_str].append({
            "sev":     sev,
            "title":   art.get("title", ""),
            "summary": analysis.get("one_line_summary", ""),
            "source":  art.get("source", ""),
            "date":    date_str,
            "url":     art.get("url", ""),
            "image":   art.get("image_url") or "",
            "etype":   etype,
        })

    active = [t for t in _EVENT_TYPES if type_date[t]]

    if not active:
        return (
            '<div style="color:#3a4a5a;padding:24px 28px;font-size:11px;'
            'letter-spacing:1px;font-family:monospace;text-align:center;">'
            'No events to display</div>'
        )

    ROW_H      = 120
    LEFT_PAD   = 140
    BOTTOM_PAD = 40
    TOP_PAD    = 20
    RIGHT_PAD  = 20
    px_per_day = max(40, min(80, 1100 // total_days))
    chart_iw   = total_days * px_per_day
    chart_w    = LEFT_PAD + chart_iw + RIGHT_PAD
    chart_h    = TOP_PAD + len(active) * ROW_H + BOTTOM_PAD

    parts: list[str] = []

    # Alternating row backgrounds + labels + divider lines
    for row_i, etype in enumerate(active):
        row_y = TOP_PAD + row_i * ROW_H
        bg = "rgba(255,255,255,0.02)" if row_i % 2 == 0 else "transparent"
        parts.append(
            f'<div style="position:absolute;left:0;top:{row_y}px;'
            f'width:{chart_w}px;height:{ROW_H}px;background:{bg};pointer-events:none;"></div>'
        )
        parts.append(
            f'<div style="position:absolute;left:0;top:{row_y}px;'
            f'width:{LEFT_PAD - 12}px;height:{ROW_H}px;display:flex;'
            f'align-items:center;justify-content:flex-end;padding-right:14px;'
            f'color:#8aa0ba;font-size:11px;font-weight:600;letter-spacing:0.5px;'
            f'text-transform:uppercase;white-space:nowrap;user-select:none;">'
            f'{etype.replace("_", " ")}</div>'
        )
        parts.append(
            f'<div style="position:absolute;left:{LEFT_PAD}px;top:{row_y + ROW_H - 1}px;'
            f'width:{chart_iw}px;height:1px;background:#1e2535;pointer-events:none;"></div>'
        )

    # X-axis date labels + vertical tick lines
    tick_every = max(1, total_days // 10)
    for d in range(0, total_days + 1, tick_every):
        lbl = (start + timedelta(days=d)).strftime("%b %d")
        x   = LEFT_PAD + d * px_per_day
        parts.append(
            f'<div style="position:absolute;left:{x}px;bottom:4px;'
            f'transform:translateX(-50%);color:#4a6080;font-size:10px;'
            f'white-space:nowrap;user-select:none;">{lbl}</div>'
        )
        parts.append(
            f'<div style="position:absolute;left:{x}px;top:{TOP_PAD}px;'
            f'width:1px;height:{len(active) * ROW_H}px;background:#1a2030;"></div>'
        )

    # Dots
    for row_i, etype in enumerate(active):
        row_cy = TOP_PAD + row_i * ROW_H + ROW_H // 2
        for date_str, items in sorted(type_date[etype].items()):
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            day_off = (dt - start).days
            if not (0 <= day_off <= total_days):
                continue
            x = LEFT_PAD + day_off * px_per_day
            sorted_items = sorted(
                items,
                key=lambda x: _SEV_ORDER.index(x["sev"] if x["sev"] in _SEV_ORDER else "low"),
                reverse=True,
            )
            n = len(sorted_items)
            for si, item in enumerate(sorted_items):
                sev = item["sev"] if item["sev"] in _SEV_ORDER else "low"
                r   = _DOT_R[sev]
                col = _SEV_CSS.get(sev, "#4af")
                y   = row_cy + (si - (n - 1) / 2) * 32
                data_str = " ".join(
                    f'data-{k}="{_html.escape(str(v))}"'
                    for k, v in {
                        "title":    item["title"],
                        "summary":  item["summary"],
                        "source":   item["source"],
                        "date":     item["date"],
                        "url":      item["url"],
                        "image":    item["image"],
                        "severity": sev,
                        "etype":    item["etype"],
                    }.items()
                )
                # Tooltip: abbreviated title so it's readable on hover
                tooltip = _html.escape((item["title"] or item["summary"] or "")[:80])
                parts.append(
                    f'<div class="sw-dot" {data_str} title="{tooltip}" '
                    f'style="position:absolute;'
                    f'left:{x}px;top:{y}px;'
                    f'width:{r*2}px;height:{r*2}px;'
                    f'margin-left:-{r}px;margin-top:-{r}px;'
                    f'border-radius:50%;background:{col};'
                    f'border:2px solid rgba(255,255,255,0.35);'
                    f'box-shadow:0 0 8px {col}66;'
                    f'cursor:pointer;z-index:2;'
                    f'transition:transform .12s,box-shadow .12s;" '
                    f'onclick="swShow(this,event)" '
                    f'onmouseenter="this.style.transform=\'scale(1.35)\'" '
                    f'onmouseleave="this.style.transform=\'scale(1)\'"></div>'
                )

    # Separate legend bar above the scrollable chart area
    leg_items = []
    for sev in _SEV_ORDER:
        r   = _DOT_R[sev]
        col = _SEV_CSS[sev]
        leg_items.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;">'
            f'<span style="display:inline-block;width:{r*2}px;height:{r*2}px;'
            f'border-radius:50%;background:{col};flex-shrink:0;'
            f'border:1.5px solid rgba(255,255,255,0.3);box-shadow:0 0 5px {col}66;"></span>'
            f'<span style="color:#8aa0ba;font-size:10px;letter-spacing:0.3px;">'
            f'{sev.capitalize()}</span>'
            f'</span>'
        )
    legend_bar = (
        f'<div style="display:flex;align-items:center;gap:20px;'
        f'padding:8px 16px 10px;background:{_BG};'
        f'border-bottom:1px solid #1e2535;">'
        f'<span style="color:#4a6080;font-size:9px;letter-spacing:1px;'
        f'text-transform:uppercase;margin-right:4px;">Severity</span>'
        + "".join(leg_items) +
        f'</div>'
    )

    chart_html = (
        f'<div class="sw-scroll" style="overflow-x:auto;width:100%;background:{_BG};">'
        f'<div style="position:relative;width:{chart_w}px;height:{chart_h}px;">'
        + "".join(parts)
        + "</div></div>"
    )

    return legend_bar + chart_html + _SWIMLANE_POPUP + _SWIMLANE_JS


# ── Folium map (MarkerCluster spiderifies on click) ──────────────────────────

def _map_iframe(events: list[dict], location: str) -> str:
    """Build a Folium map with MarkerCluster. Returns a self-contained <iframe> string."""
    center = REGION_COORDS.get(location, (20.0, 0.0))
    zoom   = 6 if location in REGION_COORDS else 2

    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB dark_matter")
    cluster = MarkerCluster().add_to(m)

    for ev in events:
        analysis = ev.get("analysis")
        article  = ev.get("article", {})
        if not analysis:
            continue

        sev   = analysis.get("severity", "low").lower()
        color = _SEV_CSS.get(sev, "#4af")

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
            }.items()
        )
        icon_html = (
            f'<div class="gw-marker" {data_attrs} '
            f'style="width:14px;height:14px;border-radius:50%;cursor:pointer;'
            f'background:{color};border:2px solid rgba(255,255,255,0.55);'
            f'box-shadow:0 0 5px {color};"></div>'
        )
        folium.Marker(
            location=center,
            icon=folium.DivIcon(html=icon_html, icon_size=(14, 14), icon_anchor=(7, 7)),
            tooltip=analysis.get("one_line_summary", article.get("title", "")),
        ).add_to(cluster)

    m.get_root().html.add_child(Element(_LEGEND_HTML))

    # Inject pull-out card + SVG line + JS — same interaction pattern as the swimlane
    m.get_root().html.add_child(Element("""
<svg id="gw-svg" style="position:fixed;top:0;left:0;width:100vw;height:100vh;
  pointer-events:none;z-index:9997;overflow:visible;">
  <line id="gw-line" x1="0" y1="0" x2="0" y2="0"
    stroke-width="1.5" stroke-opacity="0.7" display="none"/>
</svg>
<div id="gw-card" style="display:none;position:fixed;z-index:9999;width:200px;
  background:#fff;border-radius:8px;
  box-shadow:0 4px 20px rgba(0,0,0,0.22),0 0 0 1px rgba(0,0,0,0.07);
  overflow:hidden;font-family:'Courier New',monospace;" onclick="event.stopPropagation()">
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
  var SEV={low:'#2ea44f',medium:'#e3b341',high:'#f97316',critical:'#ef4444'};
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
    document.getElementById('gw-meta').textContent=(d.source||'')+(d.date?' · '+d.date:'');
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

_DASH_TMPL = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GeoWatch — __LOCATION__</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0d1117;
      color: #ffffff;
      font-family: 'Courier New', Courier, monospace;
    }
    header {
      border-bottom: 1px solid #1e2535;
      padding: 18px 28px;
    }
    h1 {
      color: #44aaff;
      font-size: 1.1rem;
      letter-spacing: 3px;
      text-transform: uppercase;
    }
    .section-label {
      background: #11151c;
      border-top: 1px solid #1e2535;
      border-bottom: 1px solid #1e2535;
      color: #4a6080;
      font-size: 0.7rem;
      letter-spacing: 3px;
      padding: 8px 28px;
      text-transform: uppercase;
    }
    .chart-wrap {
      background: #0d1117;
      padding: 24px 28px;
    }
    .chart-wrap img {
      display: block;
      max-width: 100%;
      width: 100%;
    }
    footer {
      border-top: 1px solid #1e2535;
      color: #2a3a4a;
      font-size: 0.7rem;
      letter-spacing: 1px;
      padding: 14px 28px;
      text-align: center;
    }
  </style>
</head>
<body>
  __ALERT__
  <header>
    <h1>GeoWatch &mdash; __LOCATION__ &mdash; last __DAYS__ days</h1>
  </header>

  <div>
    <div class="section-label">Interactive Map &mdash; click cluster to expand individual events</div>
    __MAP__
  </div>

  <div>
    <div class="section-label">Severity Escalation Timeline</div>
    <div class="chart-wrap">
      <img src="data:image/png;base64,__TIMELINE__" alt="Severity Timeline">
    </div>
  </div>

  <div>
    <div class="section-label">Event Type Swimlane &mdash; click a dot to see article details</div>
    __SWIMLANE__
  </div>

  <footer>Generated by GeoWatch &mdash; __TIMESTAMP__</footer>
</body>
</html>"""


def build_dashboard(events: list[dict], location: str, days: int,
                    alert: dict | None = None) -> str:
    """Return a fully self-contained dashboard HTML string (no external dependencies)."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    alert_html = ""
    if alert:
        pct_str = f"{alert['pct'] * 100:.0f}%"
        thr     = alert["threshold"].upper()
        alert_html = (
            '<div style="background:#1c0a0a;border-bottom:2px solid #ef4444;'
            'padding:12px 28px;display:flex;align-items:center;gap:14px;">'
            '<span style="color:#ef4444;font-size:1.3rem;">&#9888;</span>'
            '<div>'
            f'<div style="color:#ef4444;font-size:0.75rem;letter-spacing:2px;'
            f'text-transform:uppercase;font-weight:bold;">'
            f'Alert: Elevated Activity — {location}</div>'
            f'<div style="color:#8aa0ba;font-size:0.72rem;margin-top:2px;">'
            f'{pct_str} of events in the last 7 days rated {thr} or above '
            f'({alert["count"]}/{alert["total"]} events)</div>'
            '</div></div>'
        )

    return (
        _DASH_TMPL
        .replace("__ALERT__",    alert_html)
        .replace("__LOCATION__", location)
        .replace("__DAYS__",     str(days))
        .replace("__MAP__",      _map_iframe(events, location))
        .replace("__TIMELINE__", severity_timeline_b64(events, days))
        .replace("__SWIMLANE__", event_swimlane_html(events, days))
        .replace("__TIMESTAMP__", timestamp)
    )


# ── Comparison mode ───────────────────────────────────────────────────────────

_BLUES = {"low": "#a5f3fc", "medium": "#22d3ee", "high": "#0891b2", "critical": "#155e75"}
_REDS  = {"low": "#fed7aa", "medium": "#fb923c", "high": "#ea580c", "critical": "#7c2d12"}
_COLOR_A = "#22d3ee"   # teal  — used in summary/CSS
_COLOR_B = "#fb923c"   # orange — used in summary/CSS


def _ns_swimlane(html: str, ns: str) -> str:
    """Replace all sw-prefixed IDs, classes, and function names with a namespaced prefix."""
    for old, new in [
        # Hyphenated element IDs — longer match first so sw-svg-line beats sw-svg
        ("sw-svg-line",     f"{ns}-svg-line"),
        ("sw-svg",          f"{ns}-svg"),
        ("sw-popup",        f"{ns}-popup"),
        ("sw-img",          f"{ns}-img"),
        ("sw-badge",        f"{ns}-badge"),
        ("sw-title",        f"{ns}-title"),
        ("sw-sum",          f"{ns}-sum"),
        ("sw-meta",         f"{ns}-meta"),
        ("sw-dot",          f"{ns}-dot"),
        ("sw-scroll",       f"{ns}-scroll"),
        # Global function names — replace window.swX before bare swX() call sites
        ("window.swImgErr", f"window.swImgErr_{ns}"),
        ("window.swOpen",   f"window.swOpen_{ns}"),
        ("window.swShow",   f"window.swShow_{ns}"),
        # Inline call sites in HTML attributes
        ("swImgErr()",      f"swImgErr_{ns}()"),
        ("swOpen(event)",   f"swOpen_{ns}(event)"),
        ("swShow(",         f"swShow_{ns}("),
    ]:
        html = html.replace(old, new)
    return html


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
        ax.spines["bottom"].set_color(_GRID)
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color=_GRID, linewidth=0.8)
        ax.text(0.01, 0.94, title, transform=ax.transAxes,
                color=_TEXT, fontsize=11, fontweight="bold",
                va="top", ha="left")

    ax_a.legend(loc="upper right", framealpha=0.15, facecolor="#1a2030",
                edgecolor=_GRID, labelcolor=_TEXT, fontsize=9)
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
                   tiles="CartoDB dark_matter")

    cluster_a = MarkerCluster(name=loc_a).add_to(m)
    cluster_b = MarkerCluster(name=loc_b).add_to(m)

    def _add_markers(events, center, cluster, style: str):
        for ev in events:
            analysis = ev.get("analysis")
            article  = ev.get("article", {})
            if not analysis:
                continue
            sev   = analysis.get("severity", "low").lower()
            color = _SEV_CSS.get(sev, "#4af")
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
                }.items()
            )
            if style == "solid":
                icon_html = (
                    f'<div class="gw-marker" {data_attrs} '
                    f'style="width:13px;height:13px;border-radius:50%;cursor:pointer;'
                    f'background:{color};border:2px solid rgba(255,255,255,0.6);'
                    f'box-shadow:0 0 5px {color};"></div>'
                )
            else:  # ring
                icon_html = (
                    f'<div class="gw-marker" {data_attrs} '
                    f'style="width:15px;height:15px;border-radius:50%;cursor:pointer;'
                    f'background:transparent;border:3px solid {color};'
                    f'box-shadow:0 0 6px {color};"></div>'
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
        'background:rgba(13,17,23,0.92);border:1px solid #263040;border-radius:6px;'
        'padding:10px 14px;font-family:\'Courier New\',monospace;font-size:10px;'
        'color:#8aa0ba;line-height:1.9;">'
        '<div style="color:#4a6080;font-size:9px;letter-spacing:2px;'
        'text-transform:uppercase;margin-bottom:6px;">Severity</div>'
        + "".join(
            f'<div><span style="display:inline-block;width:10px;height:10px;'
            f'border-radius:50%;background:{_SEV_CSS[s]};margin-right:6px;'
            f'vertical-align:middle;"></span>{s.capitalize()}</div>'
            for s in reversed(_SEV_ORDER)
        )
        + '<div style="border-top:1px solid #263040;margin:7px 0 5px;"></div>'
        '<div style="color:#4a6080;font-size:9px;letter-spacing:2px;'
        'text-transform:uppercase;margin-bottom:5px;">Location</div>'
        f'<div><span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:#888;border:2px solid rgba(255,255,255,0.6);'
        f'margin-right:6px;vertical-align:middle;"></span>{loc_a} (solid)</div>'
        f'<div><span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:transparent;border:3px solid #888;'
        f'margin-right:6px;vertical-align:middle;"></span>{loc_b} (ring)</div>'
        '</div>'
    )
    m.get_root().html.add_child(Element(legend_html))

    # Reuse the same pull-out card + JS from _map_iframe
    m.get_root().html.add_child(Element("""
<svg id="gw-svg" style="position:fixed;top:0;left:0;width:100vw;height:100vh;
  pointer-events:none;z-index:9997;overflow:visible;">
  <line id="gw-line" x1="0" y1="0" x2="0" y2="0"
    stroke-width="1.5" stroke-opacity="0.7" display="none"/>
</svg>
<div id="gw-card" style="display:none;position:fixed;z-index:9999;width:200px;
  background:#fff;border-radius:8px;
  box-shadow:0 4px 20px rgba(0,0,0,0.22),0 0 0 1px rgba(0,0,0,0.07);
  overflow:hidden;font-family:'Courier New',monospace;" onclick="event.stopPropagation()">
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
  var SEV={low:'#2ea44f',medium:'#e3b341',high:'#f97316',critical:'#ef4444'};
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
    document.getElementById('gw-meta').textContent=(d.source||'')+(d.date?' · '+d.date:'');
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
            label = etype.replace("_", " ")
            out += (
                f'<div style="margin-bottom:6px;">'
                f'<div style="display:flex;justify-content:space-between;'
                f'color:#8aa0ba;font-size:10px;margin-bottom:3px;">'
                f'<span>{label}</span><span>{cnt}</span></div>'
                f'<div style="background:#0d1117;border-radius:3px;height:5px;">'
                f'<div style="background:{accent};border-radius:3px;height:5px;'
                f'width:{pct:.1f}%;"></div></div></div>'
            )
        return out or '<div style="color:#3a4a5a;font-size:10px;">No data</div>'

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
        f'<li style="margin-bottom:8px;color:#c8d6e5;font-size:11px;">{b}</li>'
        for b in bullets
    )

    return f"""
<div style="background:#1a1f2e;border:1px solid #30363d;border-radius:8px;
  padding:24px 28px;margin:0 0 24px;">
  <div style="color:#44aaff;font-size:0.7rem;letter-spacing:3px;
    text-transform:uppercase;margin-bottom:20px;">Comparison Summary</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-bottom:20px;">
    <div>
      <div style="color:{_COLOR_A};font-size:13px;font-weight:bold;margin-bottom:8px;">{loc_a}</div>
      <div style="color:#8aa0ba;font-size:11px;margin-bottom:12px;">
        {sa['total']} articles &middot; {_tag(ta)}</div>
      <div style="color:#4a6080;font-size:9px;letter-spacing:1px;
        text-transform:uppercase;margin-bottom:8px;">Event breakdown</div>
      {_bars(sa, _COLOR_A)}
    </div>
    <div>
      <div style="color:{_COLOR_B};font-size:13px;font-weight:bold;margin-bottom:8px;">{loc_b}</div>
      <div style="color:#8aa0ba;font-size:11px;margin-bottom:12px;">
        {sb['total']} articles &middot; {_tag(tb)}</div>
      <div style="color:#4a6080;font-size:9px;letter-spacing:1px;
        text-transform:uppercase;margin-bottom:8px;">Event breakdown</div>
      {_bars(sb, _COLOR_B)}
    </div>
  </div>
  <div style="border-top:1px solid #30363d;padding-top:16px;">
    <div style="color:#4a6080;font-size:9px;letter-spacing:1px;
      text-transform:uppercase;margin-bottom:12px;">Key differences</div>
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
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #0d1117; color: #fff;
           font-family: 'Courier New', Courier, monospace; }
    header { border-bottom: 1px solid #1e2535; padding: 18px 28px; }
    h1 { color: #44aaff; font-size: 1.1rem; letter-spacing: 3px;
         text-transform: uppercase; }
    .subtitle { color: #4a6080; font-size: 0.75rem; letter-spacing: 2px; margin-top: 4px; }
    .section-label { background: #11151c; border-top: 1px solid #1e2535;
                     border-bottom: 1px solid #1e2535; color: #4a6080;
                     font-size: 0.7rem; letter-spacing: 3px; padding: 8px 28px;
                     text-transform: uppercase; }
    .chart-wrap { background: #0d1117; padding: 24px 28px; }
    .chart-wrap img { display: block; max-width: 100%; width: 100%; }
    .trend-row { display: flex; gap: 40px; padding: 10px 28px 16px;
                 border-bottom: 1px solid #1e2535; }
    .trend-cell { color: #8aa0ba; font-size: 0.78rem; letter-spacing: 1px; }
    .loc-a { color: #22d3ee; }
    .loc-b { color: #fb923c; }
    .summary-wrap { padding: 24px 28px 0; }
    footer { border-top: 1px solid #1e2535; color: #2a3a4a;
             font-size: 0.7rem; letter-spacing: 1px;
             padding: 14px 28px; text-align: center; }
  </style>
</head>
<body>
  <header>
    <h1>GeoWatch &mdash; Comparative Analysis</h1>
    <div class="subtitle">__LOC_A__ vs __LOC_B__ &mdash; last __DAYS__ days</div>
  </header>

  <div class="section-label">Combined Map &mdash; <span class="loc-a">__LOC_A__</span> solid &middot; <span class="loc-b">__LOC_B__</span> ring &middot; color = severity</div>
  __COMBINED_MAP__

  <div class="section-label">Severity Escalation &mdash; Overlaid Comparison</div>
  <div class="chart-wrap">
    <img src="data:image/png;base64,__COMP_TIMELINE__" alt="Comparison Timeline">
  </div>
  <div class="trend-row">
    <div class="trend-cell"><span class="loc-a">__LOC_A__</span>: __TREND_A__</div>
    <div class="trend-cell"><span class="loc-b">__LOC_B__</span>: __TREND_B__</div>
  </div>

  <div class="section-label"><span class="loc-a">__LOC_A__</span> &mdash; Event Swimlane</div>
  __SWIMLANE_A__

  <div class="section-label"><span class="loc-b">__LOC_B__</span> &mdash; Event Swimlane</div>
  __SWIMLANE_B__

  <div class="summary-wrap">__COMPARISON_SUMMARY__</div>

  <footer>Generated by GeoWatch &mdash; __TIMESTAMP__</footer>
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

    swimlane_a = _ns_swimlane(event_swimlane_html(events_a, days), "swa")
    swimlane_b = _ns_swimlane(event_swimlane_html(events_b, days), "swb")

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
        .replace("__SWIMLANE_A__",         swimlane_a)
        .replace("__SWIMLANE_B__",         swimlane_b)
        .replace("__COMPARISON_SUMMARY__", _comparison_summary_html(
                                               events_a, events_b, loc_a, loc_b, days))
        .replace("__TIMESTAMP__",          timestamp)
    )
