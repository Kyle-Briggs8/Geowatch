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
_MAX_NODES = 30
_MIN_NODE_FREQ = 2
_MIN_EDGE_WEIGHT = 2


def build_entity_cooccurrence(events: list[dict]) -> dict[str, Any]:
    """Compute entity co-occurrence from analyzed events.

    For each article, every pair of entities counts as one co-occurrence.
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
        ents = [e.strip() for e in (analysis.get("entities") or []) if e and e.strip()]
        sev  = analysis.get("severity", "low").lower()
        for ent in ents:
            freq[ent] += 1
            entity_sevs[ent].append(sev)
        for a, b in combinations(sorted(set(ents)), 2):
            cooc[(a, b)] += 1

    # Filter and cap nodes
    top_nodes = {name for name, cnt in freq.most_common(_MAX_NODES) if cnt >= _MIN_NODE_FREQ}

    def _dominant_color(ent: str) -> str:
        sev_order = ["critical", "high", "medium", "low"]
        counts = Counter(entity_sevs[ent])
        for s in sev_order:
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


def render_entity_graph_html(cooccurrence: dict[str, Any], title: str = "") -> str:
    """Render a force-directed entity co-occurrence graph as a self-contained HTML string.

    Uses plain SVG + JavaScript — no external libraries. Dark theme matching the dashboard.
    Node size encodes frequency; edge opacity encodes co-occurrence strength.
    """
    nodes = cooccurrence.get("nodes", [])
    edges = cooccurrence.get("edges", [])

    if not nodes:
        return ""

    nodes_json = str(nodes).replace("'", '"').replace("True", "true").replace("False", "false")
    edges_json = str(edges).replace("'", '"').replace("True", "true").replace("False", "false")

    max_freq = max((n["freq"] for n in nodes), default=1)
    max_weight = max((e["weight"] for e in edges), default=1)

    header = (
        f'<div style="color:#4a6080;font-size:0.7rem;letter-spacing:3px;'
        f'text-transform:uppercase;padding:8px 16px 0;">'
        f'{title or "Entity Co-occurrence Network"}</div>'
        if title else ""
    )

    return f"""{header}
<div style="background:#0d1117;width:100%;position:relative;">
<svg id="eg-svg" width="100%" height="420"
     style="display:block;background:#0d1117;font-family:'Courier New',monospace;">
  <g id="eg-edges"></g>
  <g id="eg-nodes"></g>
  <g id="eg-labels"></g>
</svg>
<div id="eg-tooltip" style="display:none;position:absolute;background:rgba(13,17,23,0.95);
  border:1px solid #263040;border-radius:4px;padding:6px 10px;font-size:11px;
  color:#c8d6e5;font-family:'Courier New',monospace;pointer-events:none;z-index:10;">
</div>
</div>
<script>
(function(){{
  var nodes = {nodes_json};
  var edges = {edges_json};
  var MAX_FREQ   = {max_freq};
  var MAX_WEIGHT = {max_weight};

  var svg    = document.getElementById('eg-svg');
  var gEdges = document.getElementById('eg-edges');
  var gNodes = document.getElementById('eg-nodes');
  var gLabels= document.getElementById('eg-labels');
  var tip    = document.getElementById('eg-tooltip');

  var W = svg.clientWidth  || 800;
  var H = svg.clientHeight || 420;

  function nodeRadius(freq) {{ return 6 + (freq / MAX_FREQ) * 18; }}

  // Initialise node positions (evenly spaced on a circle)
  nodes.forEach(function(n, i) {{
    var angle = (i / nodes.length) * 2 * Math.PI;
    n.x  = W / 2 + (W * 0.36) * Math.cos(angle);
    n.y  = H / 2 + (H * 0.36) * Math.sin(angle);
    n.vx = 0; n.vy = 0;
  }});

  // Build name→index map
  var idx = {{}};
  nodes.forEach(function(n, i) {{ idx[n.name] = i; }});

  // Create SVG elements
  var edgeEls = edges.map(function(e) {{
    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    var op = 0.15 + 0.6 * (e.weight / MAX_WEIGHT);
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
    circ.setAttribute('stroke', 'rgba(255,255,255,0.25)');
    circ.setAttribute('stroke-width', '1.5');
    circ.style.cursor = 'pointer';
    circ.addEventListener('mouseenter', function(ev) {{
      tip.textContent = n.name + ' (' + n.freq + ')';
      tip.style.display = 'block';
      tip.style.left = (ev.clientX - svg.getBoundingClientRect().left + 12) + 'px';
      tip.style.top  = (ev.clientY - svg.getBoundingClientRect().top  - 10) + 'px';
    }});
    circ.addEventListener('mouseleave', function() {{ tip.style.display = 'none'; }});
    gNodes.appendChild(circ);
    return circ;
  }});

  var labelEls = nodes.map(function(n) {{
    var t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('font-size', '9');
    t.setAttribute('fill', '#8aa0ba');
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('pointer-events', 'none');
    t.textContent = n.name.length > 14 ? n.name.slice(0, 13) + '…' : n.name;
    gLabels.appendChild(t);
    return t;
  }});

  // Force simulation
  var REPULSION = 2200;
  var SPRING_K  = 0.04;
  var SPRING_LEN= 120;
  var DAMPING   = 0.82;
  var PADDING   = 20;

  function tick() {{
    // Repulsion between all node pairs
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
    // Spring attraction along edges
    edges.forEach(function(e) {{
      var a = nodes[idx[e.source]];
      var b = nodes[idx[e.target]];
      if (!a || !b) return;
      var dx = b.x - a.x;
      var dy = b.y - a.y;
      var dist = Math.sqrt(dx*dx + dy*dy) || 1;
      var stretch = dist - SPRING_LEN;
      var fx = SPRING_K * stretch * dx / dist;
      var fy = SPRING_K * stretch * dy / dist;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }});
    // Gravity toward center
    nodes.forEach(function(n) {{
      n.vx += (W/2 - n.x) * 0.004;
      n.vy += (H/2 - n.y) * 0.004;
    }});
    // Integrate and damp
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
    // Update edges
    edges.forEach(function(e, i) {{
      var a = nodes[idx[e.source]];
      var b = nodes[idx[e.target]];
      if (!a || !b) return;
      edgeEls[i].setAttribute('x1', a.x); edgeEls[i].setAttribute('y1', a.y);
      edgeEls[i].setAttribute('x2', b.x); edgeEls[i].setAttribute('y2', b.y);
    }});
  }}

  var frame = 0;
  function animate() {{
    tick();
    frame++;
    if (frame < 300) requestAnimationFrame(animate);
  }}
  requestAnimationFrame(animate);
}})();
</script>"""
