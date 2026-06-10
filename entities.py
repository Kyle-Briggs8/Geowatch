"""Entity co-occurrence analysis and force-directed graph visualization."""
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any


_SEV_COLOR = {
    "low":      "#2ea44f",
    "medium":   "#e3b341",
    "high":     "#f97316",
    "critical": "#ef4444",
}
_DEFAULT_NODE_COLOR = "#4af"
_MAX_NODES    = 30
_MIN_NODE_FREQ = 2
_MIN_EDGE_WEIGHT = 2

# Fix 2: canonical entity name table (keyed by lowercase variant)
_CANONICAL: dict[str, str] = {
    # United States
    "us":                        "United States",
    "u.s.":                      "United States",
    "u.s":                       "United States",
    "usa":                       "United States",
    "united states":             "United States",
    "united states of america":  "United States",
    "america":                   "United States",
    # United Kingdom
    "uk":                        "United Kingdom",
    "u.k.":                      "United Kingdom",
    "u.k":                       "United Kingdom",
    "united kingdom":            "United Kingdom",
    "britain":                   "United Kingdom",
    "great britain":             "United Kingdom",
    # European Union
    "eu":                        "European Union",
    "e.u.":                      "European Union",
    "e.u":                       "European Union",
    "european union":            "European Union",
    # Russia
    "russia":                    "Russia",
    "russian federation":        "Russia",
    # China
    "china":                     "China",
    "prc":                       "China",
    "people's republic of china": "China",
    # Iran
    "iran":                      "Iran",
    "islamic republic of iran":  "Iran",
    # North Korea
    "north korea":               "North Korea",
    "dprk":                      "North Korea",
    # NATO
    "nato":                      "NATO",
    "n.a.t.o.":                  "NATO",
    # United Nations
    "un":                        "United Nations",
    "u.n.":                      "United Nations",
    "united nations":            "United Nations",
}


def _normalize_entity(name: str) -> str:
    """Return the canonical display name for an entity, normalizing common variants."""
    stripped = name.strip()
    return _CANONICAL.get(stripped.lower(), stripped)


def build_entity_cooccurrence(events: list[dict]) -> dict[str, Any]:
    """Compute entity co-occurrence from analyzed events.

    For each article, every pair of entities counts as one co-occurrence.
    Entity names are normalized before counting (e.g. 'US' → 'United States').
    Returns {'nodes': [...], 'edges': [...]} filtered to significant entries only.
    Nodes have: name, freq, color (based on dominant severity of articles they appear in).
    Edges have: source, target, weight.
    """
    freq: Counter = Counter()
    cooc: Counter = Counter()
    entity_sevs: dict[str, list[str]] = defaultdict(list)

    for ev in events:
        analysis = ev.get("analysis")
        if not analysis:
            continue
        raw_ents = [e.strip() for e in (analysis.get("entities") or []) if e and e.strip()]
        ents = [_normalize_entity(e) for e in raw_ents]
        sev  = analysis.get("severity", "low").lower()
        for ent in ents:
            freq[ent] += 1
            entity_sevs[ent].append(sev)
        for a, b in combinations(sorted(set(ents)), 2):
            cooc[(a, b)] += 1

    top_nodes = {name for name, cnt in freq.most_common(_MAX_NODES) if cnt >= _MIN_NODE_FREQ}

    def _dominant_color(ent: str) -> str:
        counts = Counter(entity_sevs[ent])
        for s in ("critical", "high", "medium", "low"):
            if counts.get(s, 0) > 0:
                return _SEV_COLOR[s]
        return _DEFAULT_NODE_COLOR

    nodes = [
        {"name": name, "freq": freq[name], "color": _dominant_color(name)}
        for name in top_nodes
    ]
    nodes.sort(key=lambda n: -n["freq"])

    edges = [
        {"source": a, "target": b, "weight": w}
        for (a, b), w in cooc.items()
        if w >= _MIN_EDGE_WEIGHT and a in top_nodes and b in top_nodes
    ]

    return {"nodes": nodes, "edges": edges}


def render_entity_graph_html(
    cooccurrence: dict[str, Any],
    title: str = "",
    graph_id: str = "eg",
) -> str:
    """Render a force-directed entity co-occurrence graph as a self-contained HTML string.

    Uses plain SVG + JavaScript — no external libraries. Dark theme matching the dashboard.
    Node size encodes frequency; edge opacity encodes co-occurrence strength.
    graph_id must be unique per page to avoid DOM ID conflicts when multiple graphs coexist.
    """
    nodes = cooccurrence.get("nodes", [])
    edges = cooccurrence.get("edges", [])

    if not nodes:
        return ""

    nodes_json = str(nodes).replace("'", '"').replace("True", "true").replace("False", "false")
    edges_json = str(edges).replace("'", '"').replace("True", "true").replace("False", "false")

    max_freq   = max((n["freq"]   for n in nodes), default=1)
    max_weight = max((e["weight"] for e in edges), default=1)

    # Fix 1: use graph_id to namespace all DOM IDs
    gid = graph_id
    svg_id     = f"{gid}-svg"
    edges_id   = f"{gid}-edges"
    nodes_id   = f"{gid}-nodes"
    labels_id  = f"{gid}-labels"
    tooltip_id = f"{gid}-tooltip"

    header = (
        f'<div style="color:#4a6080;font-size:0.7rem;letter-spacing:2px;'
        f'text-transform:uppercase;padding:8px 16px 4px;">{title}</div>'
        if title else ""
    )

    return f"""{header}
<div style="background:#0d1117;width:100%;position:relative;">
<svg id="{svg_id}" width="100%" height="360"
     style="display:block;background:#0d1117;font-family:'Courier New',monospace;">
  <g id="{edges_id}"></g>
  <g id="{nodes_id}"></g>
  <g id="{labels_id}"></g>
</svg>
<div id="{tooltip_id}" style="display:none;position:absolute;background:rgba(13,17,23,0.95);
  border:1px solid #263040;border-radius:4px;padding:5px 9px;font-size:11px;
  color:#c8d6e5;font-family:'Courier New',monospace;pointer-events:none;z-index:10;white-space:nowrap;">
</div>
</div>
<script>
(function(){{
  var nodes = {nodes_json};
  var edges = {edges_json};
  var MAX_FREQ   = {max_freq};
  var MAX_WEIGHT = {max_weight};

  var svg    = document.getElementById('{svg_id}');
  var gEdges = document.getElementById('{edges_id}');
  var gNodes = document.getElementById('{nodes_id}');
  var gLabels= document.getElementById('{labels_id}');
  var tip    = document.getElementById('{tooltip_id}');

  var W = svg.clientWidth  || 700;
  var H = svg.clientHeight || 360;

  function nodeRadius(freq) {{ return 5 + (freq / MAX_FREQ) * 16; }}

  // Initialise node positions evenly on a circle
  nodes.forEach(function(n, i) {{
    var angle = (i / nodes.length) * 2 * Math.PI;
    n.x  = W / 2 + (W * 0.34) * Math.cos(angle);
    n.y  = H / 2 + (H * 0.34) * Math.sin(angle);
    n.vx = 0; n.vy = 0;
  }});

  var idx = {{}};
  nodes.forEach(function(n, i) {{ idx[n.name] = i; }});

  var edgeEls = edges.map(function(e) {{
    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    var op = 0.12 + 0.55 * (e.weight / MAX_WEIGHT);
    line.setAttribute('stroke', '#4a6080');
    line.setAttribute('stroke-opacity', op);
    line.setAttribute('stroke-width', 1 + 2 * (e.weight / MAX_WEIGHT));
    gEdges.appendChild(line);
    return line;
  }});

  var nodeEls = nodes.map(function(n) {{
    var r = nodeRadius(n.freq);
    var circ = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circ.setAttribute('r', r);
    circ.setAttribute('fill', n.color);
    circ.setAttribute('fill-opacity', '0.85');
    circ.setAttribute('stroke', 'rgba(255,255,255,0.22)');
    circ.setAttribute('stroke-width', '1.5');
    circ.style.cursor = 'pointer';
    circ.addEventListener('mouseenter', function(ev) {{
      tip.textContent = n.name + ' (' + n.freq + ')';
      tip.style.display = 'block';
      var svgR = svg.getBoundingClientRect();
      tip.style.left = (ev.clientX - svgR.left + 12) + 'px';
      tip.style.top  = (ev.clientY - svgR.top  - 10) + 'px';
    }});
    circ.addEventListener('mouseleave', function() {{ tip.style.display = 'none'; }});
    gNodes.appendChild(circ);
    return circ;
  }});

  // Fix 3: truncate at 15 chars; full name shown on hover via circle tooltip
  var labelEls = nodes.map(function(n) {{
    var t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('font-size', '9');
    t.setAttribute('fill', '#8aa0ba');
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('pointer-events', 'none');
    var display = n.name.length > 15 ? n.name.slice(0, 14) + '…' : n.name;
    t.textContent = display;
    t.setAttribute('title', n.name);
    gLabels.appendChild(t);
    return t;
  }});

  var REPULSION = 2400;
  var SPRING_K  = 0.04;
  var SPRING_LEN= 110;
  var DAMPING   = 0.82;
  var PADDING   = 22;

  function tick() {{
    for (var i = 0; i < nodes.length; i++) {{
      for (var j = i + 1; j < nodes.length; j++) {{
        var dx = nodes[j].x - nodes[i].x;
        var dy = nodes[j].y - nodes[i].y;
        var dist = Math.sqrt(dx*dx + dy*dy) || 1;
        var force = REPULSION / (dist * dist);
        var fx = force * dx / dist;
        var fy = force * dy / dist;
        nodes[i].vx -= fx; nodes[i].vy -= fy;
        nodes[j].vx += fx; nodes[j].vy += fy;
      }}
    }}
    edges.forEach(function(e) {{
      var a = nodes[idx[e.source]];
      var b = nodes[idx[e.target]];
      if (!a || !b) return;
      var dx = b.x - a.x, dy = b.y - a.y;
      var dist = Math.sqrt(dx*dx + dy*dy) || 1;
      var stretch = dist - SPRING_LEN;
      var fx = SPRING_K * stretch * dx / dist;
      var fy = SPRING_K * stretch * dy / dist;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }});
    nodes.forEach(function(n) {{
      n.vx += (W/2 - n.x) * 0.004;
      n.vy += (H/2 - n.y) * 0.004;
    }});
    nodes.forEach(function(n, i) {{
      n.vx *= DAMPING; n.vy *= DAMPING;
      n.x  += n.vx;   n.y  += n.vy;
      var r = nodeRadius(n.freq);
      n.x = Math.max(r + PADDING, Math.min(W - r - PADDING, n.x));
      n.y = Math.max(r + PADDING, Math.min(H - r - PADDING, n.y));
      nodeEls[i].setAttribute('cx', n.x);
      nodeEls[i].setAttribute('cy', n.y);
      labelEls[i].setAttribute('x', n.x);
      labelEls[i].setAttribute('y', n.y + r + 11);
    }});
    edges.forEach(function(e, i) {{
      var a = nodes[idx[e.source]], b = nodes[idx[e.target]];
      if (!a || !b) return;
      edgeEls[i].setAttribute('x1', a.x); edgeEls[i].setAttribute('y1', a.y);
      edgeEls[i].setAttribute('x2', b.x); edgeEls[i].setAttribute('y2', b.y);
    }});
  }}

  // Fix 3: label collision resolution — run after simulation settles
  function resolveLabels() {{
    var CHAR_W = 5.4, LH = 13, PAD = 3;
    var lbls = labelEls.map(function(el, i) {{
      var text = el.textContent || '';
      return {{
        el:   el,
        x:    parseFloat(el.getAttribute('x') || 0),
        y:    parseFloat(el.getAttribute('y') || 0),
        w:    text.length * CHAR_W,
        freq: nodes[i].freq
      }};
    }});

    for (var iter = 0; iter < 30; iter++) {{
      for (var i = 0; i < lbls.length; i++) {{
        for (var j = i + 1; j < lbls.length; j++) {{
          var a = lbls[i], b = lbls[j];
          var overlapX = Math.abs(a.x - b.x) < (a.w + b.w) / 2 + PAD;
          var overlapY = Math.abs(a.y - b.y) < LH + PAD;
          if (overlapX && overlapY) {{
            var push = (LH + PAD - Math.abs(a.y - b.y)) / 2 + 1;
            if (a.freq >= b.freq) {{
              b.y += push;
            }} else {{
              a.y -= push;
            }}
          }}
        }}
      }}
    }}

    lbls.forEach(function(l) {{ l.el.setAttribute('y', l.y); }});
  }}

  var frame = 0;
  function animate() {{
    tick();
    frame++;
    if (frame < 300) {{
      requestAnimationFrame(animate);
    }} else {{
      resolveLabels();
    }}
  }}
  requestAnimationFrame(animate);
}})();
</script>"""
