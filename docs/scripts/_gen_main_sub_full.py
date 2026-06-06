#!/usr/bin/env python3
"""Build clusters for all 256 debates from main_argument_pairs and regenerate
main_argument.html + sub_argument.html with full data."""
from pathlib import Path
import json, gzip, re
from collections import defaultdict, Counter

ROOT = Path(__file__).parent.parent.parent
DOCS = Path(__file__).parent.parent
INTERNAL = ROOT.parent / "argument_collapse_internal"

# === Load essays (toulmin) — main_arg + sub_args per essay ===

def load_representative_essays():
    """Set of essay_ids marked is_representative=True (the 5 vanilla medoids per debate)."""
    reps = set()
    for p in ["data/nyt/llm_essays.jsonl.gz", "data/br/llm_essays.jsonl.gz"]:
        for line in gzip.open(ROOT / p, "rt"):
            d = json.loads(line)
            if d.get("is_representative"):
                reps.add(d["essay_id"])
    return reps


def load_toulmin():
    """Load toulmin per essay. For vanilla, keep only is_representative essays (medoids)."""
    reps = load_representative_essays()
    rows = []
    for venue, p in [("nyt", "data/nyt/toulmin.jsonl.gz"), ("br", "data/br/toulmin.jsonl.gz")]:
        for line in gzip.open(ROOT / p, "rt"):
            d = json.loads(line)
            if d["kind"] == "vanilla" and d["essay_id"] not in reps:
                continue  # filter non-medoid vanilla
            if d["kind"] == "position-guided":
                continue  # not used in site visualizations
            rows.append(d)
    return rows


def load_debates():
    out = {}
    for p in ["data/nyt/debates.jsonl.gz", "data/br/debates.jsonl.gz"]:
        for line in gzip.open(ROOT / p, "rt"):
            d = json.loads(line)
            out[(d["venue"], d["debate_id"])] = d
    return out


# === Cluster from main_argument_pairs ===

class UF:
    def __init__(self): self.p = {}
    def find(self, x):
        if x not in self.p: self.p[x] = x; return x
        if self.p[x] != x: self.p[x] = self.find(self.p[x])
        return self.p[x]
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.p[ra] = rb


def cluster_per_debate():
    """Return: (venue, debate_id) -> {essay_id: cluster_root}"""
    per_debate_uf = defaultdict(UF)
    for venue, path in [("nyt","data/nyt/main_argument_pairs.jsonl.gz"), ("br","data/br/main_argument_pairs.jsonl.gz")]:
        for line in gzip.open(ROOT/path, "rt"):
            d = json.loads(line)
            key = (venue, d["debate_id"])
            uf = per_debate_uf[key]
            # Ensure essays exist as nodes
            uf.find(d["essay_i"]); uf.find(d["essay_j"])
            if d["relation"] in ("equivalent", "strong_overlap"):
                uf.union(d["essay_i"], d["essay_j"])
    out = {}
    for key, uf in per_debate_uf.items():
        out[key] = {e: uf.find(e) for e in uf.p}
    return out


# === Source classification ===

def normalize_kind(kind, model_short):
    if kind == "human": return ("human", None)
    if kind == "vanilla": return ("vanilla", model_short)
    if kind == "diversified": return ("diversified", model_short)
    if kind == "position-guided": return ("position-guided", model_short)
    return (kind, model_short)


MODEL_FAMILIES_ORDER = ["gpt-5.5", "anthropic-claude-opus-4.7", "deepseek-deepseek-v4-pro", "vertex-api__gemini-3.1-pro-preview", "minimax-minimax-m2.7"]
MODEL_SHORT = ["gpt-5.5", "claude-opus-4.7", "deepseek-v4-pro", "gemini-3.1-pro", "minimax-m2.7"]
MODEL_DISPLAY = ["GPT", "Claude", "DeepSeek", "Gemini", "MiniMax"]


def model_family_from_essay_id(essay_id):
    """Best-effort extract LLM family from essay_id."""
    if "gpt-5.5" in essay_id: return "GPT"
    if "claude-opus" in essay_id: return "Claude"
    if "deepseek-v4-pro" in essay_id: return "DeepSeek"
    if "gemini-3.1-pro" in essay_id: return "Gemini"
    if "minimax-m2.7" in essay_id: return "MiniMax"
    return None


# === Build cluster info per debate ===

def build_clusters(toulmin_rows, cluster_map):
    """Return per-debate cluster list with:
        cluster_id, main_arg quote (representative),
        per-source counts: humans count, vanilla [GPT,Claude,DeepSeek,Gemini,MiniMax] presence,
        diversified [...] presence
        essay_ids in cluster
    """
    # Group toulmin by (venue, debate)
    per_debate_essays = defaultdict(list)
    for t in toulmin_rows:
        per_debate_essays[(t["venue"], t["debate_id"])].append(t)

    result = {}
    for key, essays in per_debate_essays.items():
        # Vanilla only the representative essays (is_representative) — but toulmin doesn't have that flag.
        # Use ALL vanilla essays; in the matrix we'll show presence per model_family.
        cmap = cluster_map.get(key, {})
        clusters = defaultdict(lambda: {"essays": []})
        for e in essays:
            root = cmap.get(e["essay_id"], e["essay_id"])  # singleton if no pair
            clusters[root]["essays"].append(e)

        # Build cluster summary
        cluster_list = []
        for root, info in clusters.items():
            essays_in_cluster = info["essays"]
            # Pick representative: prefer human first, else first essay
            humans = [e for e in essays_in_cluster if e["kind"] == "human"]
            rep = humans[0] if humans else essays_in_cluster[0]
            main_arg_text = rep["main_argument"]

            # Source breakdown
            humans_set = {e["essay_id"] for e in essays_in_cluster if e["kind"] == "human"}
            vanilla_by_family = {}
            div_by_family = {}
            for e in essays_in_cluster:
                fam = model_family_from_essay_id(e["essay_id"])
                if e["kind"] == "vanilla" and fam:
                    vanilla_by_family[fam] = vanilla_by_family.get(fam, 0) + 1
                elif e["kind"] == "diversified" and fam:
                    div_by_family[fam] = div_by_family.get(fam, 0) + 1

            cluster_list.append({
                "main_arg": main_arg_text,
                "n_humans": len(humans_set),
                "humans_authors": sorted({"|".join(e.get("essay_id","")) for e in essays_in_cluster if e["kind"]=="human"}),
                "vanilla_families": vanilla_by_family,
                "diversified_families": div_by_family,
                "n_essays": len(essays_in_cluster),
                "essay_ids": [e["essay_id"] for e in essays_in_cluster],
                "sub_args_by_essay": [
                    {
                        "essay_id": e["essay_id"],
                        "kind": e["kind"],
                        "family": model_family_from_essay_id(e["essay_id"]),
                        "subs": e.get("sub_arguments") or [],
                    } for e in essays_in_cluster
                ],
            })
        # Sort clusters by n_essays desc, then by # humans desc
        cluster_list.sort(key=lambda c: (-c["n_essays"], -c["n_humans"]))
        result[key] = cluster_list
    return result


# === HTML generators ===

CSS_BASE = """  :root {
    --paper: #f6f3ec;
    --paper-soft: #efebe1;
    --ink: #1c1917;
    --ink-soft: #44403c;
    --quiet: #76706a;
    --line: #d8d2c4;
    --line-soft: #e6dfd1;
    --src-human:  #2d8654;
    --src-van:    #b85e3a;
    --src-div:    #7c5e9a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: var(--paper); }
  body { color: var(--ink); font-family: 'Inter', -apple-system, sans-serif; font-size: 14px; line-height: 1.6; -webkit-font-smoothing: antialiased; }
  a { color: inherit; text-decoration: none; }
  .masthead { border-bottom: 1px solid var(--line); padding: 22px 40px; display: flex; align-items: center; justify-content: space-between; background: var(--paper); }
  .brand { font-family: 'Newsreader', serif; font-size: 19px; font-weight: 500; letter-spacing: -0.01em; }
  .brand b { font-weight: 600; }
  .nav { display: flex; gap: 32px; }
  .nav a { font-size: 11.5px; font-weight: 500; letter-spacing: 0.16em; text-transform: uppercase; color: var(--quiet); padding: 6px 0; border-bottom: 1.5px solid transparent; transition: color 0.15s, border-color 0.15s; }
  .nav a:hover { color: var(--ink); }
  .nav a.active { color: var(--ink); border-bottom-color: var(--ink); }

  .hero { padding: 70px 40px 24px; max-width: 1280px; margin: 0 auto; }
  .hero .eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--quiet); margin-bottom: 18px; }
  .hero h1 { font-family: 'Newsreader', serif; font-weight: 500; font-size: 44px; line-height: 1.1; letter-spacing: -0.02em; margin-bottom: 14px; }
  .hero h1 em { font-style: italic; color: var(--quiet); font-weight: 400; }
  .hero .deck { font-family: 'Newsreader', serif; font-size: 17px; line-height: 1.55; color: var(--ink-soft); font-style: italic; max-width: 820px; }

  .body-grid { max-width: 1280px; margin: 0 auto; padding: 24px 40px 120px; display: grid; grid-template-columns: 220px 1fr; gap: 48px; }
  .sidebar { position: sticky; top: 16px; align-self: start; max-height: calc(100vh - 32px); overflow-y: auto; }
  .search-box { width: 100%; padding: 8px 10px; font-family: 'Inter', sans-serif; font-size: 12px; border: 1px solid var(--line); border-radius: 3px; background: var(--paper); color: var(--ink); margin-bottom: 14px; }
  .search-box:focus { outline: none; border-color: var(--ink); }
  .filter-head { font-size: 10.5px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink); margin: 6px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--ink); }
  .filter-list { list-style: none; }
  .filter-list li { padding: 5px 0; font-size: 13px; color: var(--ink-soft); cursor: pointer; border-bottom: 1px solid var(--line-soft); display: flex; align-items: center; justify-content: space-between; transition: color 0.15s; }
  .filter-list li:hover { color: var(--ink); }
  .filter-list li.active { color: var(--ink); font-weight: 500; }
  .filter-list li .ct { font-size: 11px; color: var(--quiet); font-variant-numeric: tabular-nums; }
  .filter-list li.active .ct { color: var(--src-van); }
  .filter-group { margin-bottom: 22px; }

  .toolbar { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 22px; padding-bottom: 12px; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: 8px; }
  .toolbar .title { font-family: 'Newsreader', serif; font-size: 22px; font-weight: 500; }
  .toolbar .sort { font-size: 11px; color: var(--quiet); letter-spacing: 0.06em; }
  .sort-btn { cursor: pointer; padding: 2px 0; border-bottom: 1px solid transparent; transition: color 0.15s, border-color 0.15s; }
  .sort-btn:hover { color: var(--ink); }
  .sort-btn.active { color: var(--ink); font-weight: 500; border-bottom-color: var(--ink); }

  .debate-section { margin-bottom: 36px; }
  .debate-section:last-child { margin-bottom: 0; }
  .debate-head { display: flex; align-items: baseline; justify-content: space-between; padding-bottom: 10px; border-bottom: 1.5px solid var(--ink); margin-bottom: 12px; cursor: pointer; }
  .debate-head h2 { font-family: 'Newsreader', serif; font-size: 19px; font-weight: 500; letter-spacing: -0.005em; line-height: 1.25; }
  .debate-head h2 a:hover { text-decoration: underline; text-underline-offset: 3px; }
  .debate-head .meta { font-size: 10.5px; color: var(--quiet); letter-spacing: 0.04em; flex-shrink: 0; }
  .debate-head .toggle { font-size: 10px; color: var(--quiet); margin-left: 8px; }
  .debate-section.collapsed .arg-table { display: none; }

  /* Arg table */
  .arg-table { display: grid; gap: 0; }
  .col-header, .arg-row {
    display: grid;
    grid-template-columns: minmax(280px, 1fr) 50px repeat(5, 36px);
    gap: 4px;
    align-items: center;
  }
  .col-header {
    padding: 4px 6px 8px 0;
    font-family: 'Inter', sans-serif;
    font-size: 9px; letter-spacing: 0.1em;
    text-transform: uppercase; font-weight: 600;
    color: var(--quiet);
    border-bottom: 1px solid var(--line);
  }
  .col-header .model-label { text-align: center; font-size: 9.5px; letter-spacing: 0.04em; text-transform: none; font-weight: 600; color: var(--ink); }
  .col-header .center { text-align: center; }

  .arg-row {
    padding: 10px 6px 10px 0;
    border-bottom: 1px solid var(--line-soft);
    cursor: pointer;
    transition: background 0.12s;
  }
  .arg-row:hover { background: rgba(0,0,0,0.025); }
  .arg-row:last-child { border-bottom: none; }
  .arg-text { font-family: 'Newsreader', serif; font-size: 13.5px; line-height: 1.4; color: var(--ink); font-style: italic; padding-right: 8px; }
  .humans-pill { display: inline-block; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 2px; color: #fff; background: var(--src-human); font-variant-numeric: tabular-nums; min-width: 20px; text-align: center; }
  .humans-pill.zero { background: var(--line); color: var(--quiet); font-weight: 500; }
  .model-cell { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .model-cell .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--line); }
  .model-cell .dot.v.on { background: var(--src-van); }
  .model-cell .dot.d.on { background: var(--src-div); }
  .model-cell .dot.off { background: transparent; border: 1px dashed var(--line); }

  .legend {
    margin: 0 0 18px;
    font-size: 11px;
    color: var(--quiet);
    letter-spacing: 0.02em;
    display: flex; gap: 14px; flex-wrap: wrap;
    padding: 8px 12px;
    border: 1px solid var(--line-soft);
    border-radius: 4px;
    background: var(--paper-soft);
  }
  .legend .item { display: flex; align-items: center; gap: 5px; }
  .legend .key { display: inline-block; width: 9px; height: 9px; border-radius: 50%; }
  .legend .key.h { background: var(--src-human); }
  .legend .key.v { background: var(--src-van); }
  .legend .key.d { background: var(--src-div); }
  .legend .key.off { background: transparent; border: 1px dashed var(--quiet); }

  @media (max-width: 900px) {
    .masthead { padding: 16px 20px; flex-wrap: wrap; gap: 12px; }
    .nav { gap: 18px; }
    .nav a { font-size: 10.5px; letter-spacing: 0.1em; }
    .hero { padding: 40px 20px 18px; }
    .hero h1 { font-size: 28px; }
    .body-grid { padding: 20px 20px 80px; grid-template-columns: 1fr; gap: 24px; }
    .sidebar { position: static; max-height: none; }
    .col-header, .arg-row {
      grid-template-columns: 1fr 50px repeat(5, 28px);
      gap: 4px;
      font-size: 12px;
    }
    .arg-text { font-size: 12.5px; }
    .toolbar { flex-direction: column; align-items: flex-start; gap: 8px; }
  }
"""

INDEX_HREF_FOR_TOY = {
    ("nyt", "are-americans-too-obsessed-with-cleanliness"): "cleanliness.html",
    ("nyt", "silicon-valley-goes-to-washington"):           "silicon_valley.html",
    ("br", "forum_after_911"):                              "boston_review_civil_liberties.html",
}

def detail_href(venue, debate_id):
    key = (venue, debate_id)
    if key in INDEX_HREF_FOR_TOY: return "debates/" + INDEX_HREF_FOR_TOY[key]
    return f"debates/debate_{venue}_{debate_id}.html"


def debate_title(d):
    q = d.get("question_text") or d.get("lead_essay_text") or ""
    m = re.match(r"^\s*#\s+(.+?)(?:\n|$)", q)
    if m: return m.group(1).strip()
    return d.get("title") or d["debate_id"]


def topic_label(t):
    if not t: return ""
    return t.replace("_", " ").title()


def build_main_argument_html(per_debate_clusters, debate_meta):
    """Render main_argument.html with all debates."""
    # Build data payload for JS rendering
    debates_data = []
    for (venue, debate_id), clusters in per_debate_clusters.items():
        meta = debate_meta.get((venue, debate_id))
        if not meta: continue
        debates_data.append({
            "venue": venue,
            "debate_id": debate_id,
            "title": debate_title(meta),
            "topic": topic_label(meta.get("topic")),
            "qtype": meta["question_type"] or "lead_essay",
            "href": detail_href(venue, debate_id),
            "n_humans": meta["n_humans"],
            "clusters": [
                {
                    "main_arg": c["main_arg"],
                    "n_humans": c["n_humans"],
                    "n_essays": c["n_essays"],
                    "vanilla_families": c["vanilla_families"],
                    "diversified_families": c["diversified_families"],
                }
                for c in clusters
            ],
        })
    # Sort debates alphabetically
    debates_data.sort(key=lambda d: d["title"])

    # Compute summary counts for sidebar
    total_clusters = sum(len(d["clusters"]) for d in debates_data)

    data_json = json.dumps(debates_data, ensure_ascii=False)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Main arguments · Argument Collapse</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
""" + CSS_BASE + """
</style>
</head>
<body>

<header class="masthead">
  <div class="brand"><a href="index.html"><b>Argument Collapse</b></a></div>
  <nav class="nav">
    <a href="index.html">DEBATES</a>
    <a href="main_argument.html" class="active">MAIN_ARGUMENT</a>
    <a href="sub_argument.html">SUB_ARGUMENT</a>
  </nav>
</header>

<section class="hero">
  <div class="eyebrow">Main arguments · across all debates</div>
  <h1>What main arguments did <em>humans</em> and <em>LLMs</em> produce?</h1>
  <p class="deck">Each row is one cluster of equivalent main arguments. The five model columns show which families (GPT-5.5, Claude Opus 4.7, DeepSeek V4 Pro, Gemini 3.1 Pro, MiniMax M2.7) produced an essay in that cluster, under <b>vanilla</b> (top dot) or <b>diversified</b> (bottom dot) prompting.</p>
</section>

<div class="body-grid">

  <aside class="sidebar">
    <input type="search" id="search-box" class="search-box" placeholder="Search debate titles…">
    <div class="filter-group">
      <div class="filter-head">Venue</div>
      <ul class="filter-list" data-filter="venue">
        <li class="active" data-val="all">All<span class="ct" id="ct-venue-all"></span></li>
        <li data-val="nyt">NYT<span class="ct" id="ct-venue-nyt"></span></li>
        <li data-val="br">Boston Review<span class="ct" id="ct-venue-br"></span></li>
      </ul>
    </div>
    <div class="filter-group">
      <div class="filter-head">Question type</div>
      <ul class="filter-list" data-filter="qtype">
        <li class="active" data-val="all">All<span class="ct" id="ct-qtype-all"></span></li>
        <li data-val="stance">Binary<span class="ct" id="ct-qtype-stance"></span></li>
        <li data-val="open_ended">Open-ended<span class="ct" id="ct-qtype-open"></span></li>
        <li data-val="lead_essay">Lead-essay<span class="ct" id="ct-qtype-lead"></span></li>
      </ul>
    </div>
    <div class="filter-group">
      <div class="filter-head">Cluster source</div>
      <ul class="filter-list" data-filter="source">
        <li class="active" data-val="all">All clusters<span class="ct" id="ct-source-all"></span></li>
        <li data-val="has_humans">Has humans<span class="ct" id="ct-source-h"></span></li>
        <li data-val="has_vanilla">Has vanilla<span class="ct" id="ct-source-v"></span></li>
        <li data-val="llm_only">LLM-only<span class="ct" id="ct-source-llm"></span></li>
      </ul>
    </div>
  </aside>

  <main>
    <div class="toolbar">
      <div class="title" id="title-counter">Debates</div>
      <div class="sort">View: <span class="sort-btn active" data-view="collapsed">collapsed</span> · <span class="sort-btn" data-view="expanded">expanded</span></div>
    </div>

    <div class="legend">
      <div class="item"><span class="key h"></span>Human in cluster</div>
      <div class="item"><span class="key v"></span>Vanilla (top dot)</div>
      <div class="item"><span class="key d"></span>Diversified (bottom dot)</div>
      <div class="item"><span class="key off"></span>Not produced</div>
    </div>

    <div id="debates-container"></div>

  </main>
</div>

<script id="debates-data" type="application/json">__DATA__</script>
<script>
const debates = JSON.parse(document.getElementById('debates-data').textContent);
const state = { venue:"all", qtype:"all", source:"all", search:"", view:"collapsed" };
const MODELS = ["GPT", "Claude", "DeepSeek", "Gemini", "MiniMax"];

function clusterPassesSource(c) {
  if (state.source === "all") return true;
  const hasV = MODELS.some(m => (c.vanilla_families[m]||0) > 0);
  const hasD = MODELS.some(m => (c.diversified_families[m]||0) > 0);
  if (state.source === "has_humans") return c.n_humans > 0;
  if (state.source === "has_vanilla") return hasV;
  if (state.source === "llm_only") return c.n_humans === 0;
  return true;
}

function debatePasses(d) {
  if (state.venue !== "all" && d.venue !== state.venue) return false;
  if (state.qtype !== "all" && d.qtype !== state.qtype) return false;
  if (state.search && !d.title.toLowerCase().includes(state.search.toLowerCase())) return false;
  return true;
}

function rowHtml(c) {
  let html = '<div class="arg-row">';
  html += `<span class="arg-text">${c.main_arg}</span>`;
  html += `<span style="text-align:center;"><span class="humans-pill ${c.n_humans===0?'zero':''}">${c.n_humans}</span></span>`;
  for (const m of MODELS) {
    const v = (c.vanilla_families[m]||0) > 0;
    const d = (c.diversified_families[m]||0) > 0;
    html += `<span class="model-cell"><span class="dot v ${v?'on':'off'}"></span><span class="dot d ${d?'on':'off'}"></span></span>`;
  }
  html += '</div>';
  return html;
}

function colHeader() {
  let html = '<div class="col-header"><span>Argument cluster</span><span class="center">Hum.</span>';
  for (const m of MODELS) html += `<span class="model-label">${m}</span>`;
  html += '</div>';
  return html;
}

function debateHtml(d) {
  const clusters = d.clusters.filter(clusterPassesSource);
  if (clusters.length === 0) return '';
  const collapsedClass = state.view === "collapsed" ? "" : "";  // both default expanded for now
  const venueLabel = d.venue === "nyt" ? "NYT" : "BR";
  let html = `<div class="debate-section" data-debate="${d.debate_id}">`;
  html += `<div class="debate-head" onclick="this.parentElement.classList.toggle('collapsed')">`;
  html += `<h2><a href="${d.href}" onclick="event.stopPropagation()">${d.title}</a></h2>`;
  html += `<span class="meta">${venueLabel} · ${d.topic} · ${clusters.length} cluster${clusters.length===1?'':'s'}</span>`;
  html += `</div>`;
  html += `<div class="arg-table">${colHeader()}`;
  clusters.forEach(c => { html += rowHtml(c); });
  html += `</div></div>`;
  return html;
}

function render() {
  const filtered = debates.filter(debatePasses);
  const container = document.getElementById('debates-container');
  let html = '';
  for (const d of filtered) html += debateHtml(d);
  container.innerHTML = html || '<div style="padding:60px 20px;text-align:center;color:var(--quiet);font-style:italic;font-family:Newsreader,serif;">No debates match these filters.</div>';

  // Collapse all if view=collapsed
  if (state.view === "collapsed") {
    document.querySelectorAll('.debate-section').forEach(s => s.classList.add('collapsed'));
  }

  // Update sidebar counts
  const all = debates;
  const baseSearch = all.filter(d => !state.search || d.title.toLowerCase().includes(state.search.toLowerCase()));
  document.getElementById('ct-venue-all').textContent = baseSearch.length;
  document.getElementById('ct-venue-nyt').textContent = baseSearch.filter(d=>d.venue==='nyt').length;
  document.getElementById('ct-venue-br').textContent = baseSearch.filter(d=>d.venue==='br').length;
  const v = state.venue === "all" ? baseSearch : baseSearch.filter(d=>d.venue===state.venue);
  document.getElementById('ct-qtype-all').textContent = v.length;
  document.getElementById('ct-qtype-stance').textContent = v.filter(d=>d.qtype==='stance').length;
  document.getElementById('ct-qtype-open').textContent = v.filter(d=>d.qtype==='open_ended').length;
  document.getElementById('ct-qtype-lead').textContent = v.filter(d=>d.qtype==='lead_essay').length;
  // Source counts (count clusters)
  let countClusters = (filterFn) => {
    return filtered.reduce((sum,d) => sum + d.clusters.filter(filterFn).length, 0);
  };
  document.getElementById('ct-source-all').textContent = countClusters(_=>true);
  document.getElementById('ct-source-h').textContent = countClusters(c=>c.n_humans>0);
  document.getElementById('ct-source-v').textContent = countClusters(c=>MODELS.some(m=>(c.vanilla_families[m]||0)>0));
  document.getElementById('ct-source-llm').textContent = countClusters(c=>c.n_humans===0);
  document.getElementById('title-counter').textContent = `${filtered.length} debate${filtered.length===1?'':'s'} · ${countClusters(_=>true)} clusters`;
}

// Wire interactions
document.querySelectorAll('.filter-list[data-filter]').forEach(list => {
  const key = list.dataset.filter;
  list.querySelectorAll('li').forEach(li => {
    li.addEventListener('click', () => {
      list.querySelectorAll('li').forEach(l => l.classList.remove('active'));
      li.classList.add('active');
      state[key] = li.dataset.val;
      render();
    });
  });
});
document.getElementById('search-box').addEventListener('input', e => { state.search = e.target.value; render(); });
document.querySelectorAll('.sort-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.view = btn.dataset.view;
    render();
  });
});

render();
</script>

</body>
</html>
"""
    html = html.replace("__DATA__", data_json)
    return html


def build_sub_argument_html(per_debate_clusters, debate_meta):
    """Sub-argument page: flat table — each row is one sub-arg, columns
    Sub# | Source | Sub-arg text | Main-cluster | Debate · Author."""
    # Human author lookup
    human_authors = {}
    for p in ["data/nyt/human_essays.jsonl.gz", "data/br/human_essays.jsonl.gz"]:
        for line in gzip.open(ROOT / p, "rt"):
            d = json.loads(line)
            human_authors[(d["venue"], d["debate_id"], d["essay_id"])] = ", ".join(d.get("authors") or [])
    TOY_CLUSTER_PREFIX = {
        "are-americans-too-obsessed-with-cleanliness": "clusters/cleanliness_arg_",
        "silicon-valley-goes-to-washington":            "clusters/silicon_valley_arg_",
        "forum_after_911":                              "clusters/boston_review_civil_liberties_arg_",
    }
    # Normalized payload to slim JSON
    debates_list = []  # parallel arrays keyed by index
    clusters_list = []
    rows = []
    debate_idx_by_id = {}
    for (venue, debate_id), clusters in per_debate_clusters.items():
        meta = debate_meta.get((venue, debate_id))
        if not meta: continue
        di = len(debates_list)
        debate_idx_by_id[(venue, debate_id)] = di
        debates_list.append({
            "t": debate_title(meta),
            "v": venue,
            "q": meta["question_type"] or "lead_essay",
            "h": detail_href(venue, debate_id),
        })
        for ci, c in enumerate(clusters, 1):
            if debate_id in TOY_CLUSTER_PREFIX:
                cluster_href = f"{TOY_CLUSTER_PREFIX[debate_id]}{ci}.html"
            else:
                cluster_href = f"clusters/debate_{venue}_{debate_id}_arg_{ci}.html"
            cidx = len(clusters_list)
            clusters_list.append({
                "d": di,           # debate index
                "i": ci,           # 1-based cluster idx within debate
                "t": c["main_arg"],
                "h": cluster_href,
            })
            for e in c["sub_args_by_essay"]:
                subs = e.get("subs") or []
                if not subs: continue
                k = "h" if e["kind"]=="human" else ("v" if e["kind"]=="vanilla" else "d")
                if k == "h":
                    author = human_authors.get((venue, debate_id, e["essay_id"]), e["essay_id"][:30])
                else:
                    author = e.get("family") or "LLM"
                total_subs = len(subs)
                for si, s in enumerate(subs, 1):
                    rows.append({
                        "c": cidx,             # cluster index
                        "s": k,
                        "i": si,
                        "n": total_subs,
                        "t": s,
                        "a": author,
                    })
    print(f"  debates: {len(debates_list)}  clusters: {len(clusters_list)}  sub-args: {len(rows)}")
    payload = {"debates": debates_list, "clusters": clusters_list, "rows": rows}

    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sub-arguments · Argument Collapse</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
""" + CSS_BASE + """
  .toolbar { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 22px; padding-bottom: 12px; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: 8px; }
  .toolbar .title { font-family: 'Newsreader', serif; font-size: 22px; font-weight: 500; }
  .toolbar .sort { font-size: 11px; color: var(--quiet); letter-spacing: 0.06em; }
  .sort-btn { cursor: pointer; padding: 2px 0; border-bottom: 1px solid transparent; transition: color 0.15s, border-color 0.15s; }
  .sort-btn:hover { color: var(--ink); }
  .sort-btn.active { color: var(--ink); font-weight: 500; border-bottom-color: var(--ink); }

  /* Cluster header row */
  .cluster-block { margin-bottom: 22px; }
  .cluster-head-row {
    background: var(--paper-soft);
    border-left: 3px solid var(--src-div);
    padding: 12px 16px;
    margin-bottom: 0;
    display: grid;
    grid-template-columns: 60px 1fr minmax(200px, 280px);
    gap: 14px;
    align-items: baseline;
    border-radius: 0 4px 0 0;
  }
  .cluster-head-row .cluster-num {
    font-family: 'Inter', sans-serif;
    font-size: 10px; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--src-div);
    border: 1px solid var(--src-div);
    padding: 3px 8px; border-radius: 2px;
    text-align: center;
  }
  .cluster-head-row .cluster-title {
    font-family: 'Newsreader', serif; font-style: italic;
    font-size: 14.5px; line-height: 1.45; color: var(--ink);
  }
  .cluster-head-row .cluster-title a { color: var(--ink); text-decoration: none; border-bottom: 1px dashed var(--line); }
  .cluster-head-row .cluster-title a:hover { border-bottom-color: var(--src-div); color: var(--src-div); }
  .cluster-head-row .debate-attrib {
    font-size: 11px;
    line-height: 1.4;
    color: var(--ink-soft);
    text-align: right;
  }
  .cluster-head-row .debate-attrib .debate-pin {
    display: inline-block;
    font-family: 'Inter', sans-serif;
    font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--quiet);
    border: 1px solid var(--line);
    padding: 1px 5px; border-radius: 2px;
    margin-right: 4px; font-weight: 600;
  }
  .cluster-head-row .debate-attrib a { color: var(--ink-soft); }
  .cluster-head-row .debate-attrib a:hover { color: var(--ink); border-bottom: 1px solid var(--ink); }

  .cluster-subs { border: 1px solid var(--line-soft); border-top: none; border-radius: 0 0 4px 4px; }
  .sub-row {
    display: grid;
    grid-template-columns: 64px 80px minmax(280px, 1fr) 140px;
    gap: 14px;
    align-items: baseline;
    padding: 9px 16px;
    border-bottom: 1px solid var(--line-soft);
    transition: background 0.12s;
  }
  .sub-row:hover { background: rgba(0,0,0,0.025); }
  .sub-row:last-child { border-bottom: none; }
  .sub-id { font-family: 'Inter', sans-serif; font-size: 10.5px; color: var(--quiet); font-weight: 600; letter-spacing: 0.04em; font-variant-numeric: tabular-nums; }
  .sub-source { font-family: 'Inter', sans-serif; font-size: 9.5px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; padding: 3px 8px; border-radius: 2px; color: #fff; display: inline-block; }
  .sub-source.h { background: var(--src-human); }
  .sub-source.v { background: var(--src-van); }
  .sub-source.d { background: var(--src-div); }
  .sub-body { font-family: 'Newsreader', serif; font-size: 14px; line-height: 1.5; color: var(--ink); }
  .sub-author { font-size: 11px; color: var(--quiet); font-style: italic; text-align: right; line-height: 1.4; }
  .sub-author .author-name { font-style: normal; color: var(--ink-soft); }
  .pagination { display: flex; gap: 12px; justify-content: center; padding: 24px 0 0; font-size: 11.5px; }
  .pagination button { background: none; border: 1px solid var(--line); padding: 6px 12px; border-radius: 2px; cursor: pointer; font-family: 'Inter', sans-serif; font-size: 11.5px; color: var(--ink-soft); }
  .pagination button:hover { border-color: var(--ink); color: var(--ink); }
  .pagination button:disabled { opacity: 0.4; cursor: default; }
  .pagination .ind { font-variant-numeric: tabular-nums; color: var(--quiet); align-self: center; }

  @media (max-width: 900px) {
    .sub-table > .col-header,
    .sub-table > .sub-row { grid-template-columns: 50px 1fr; gap: 8px 10px; }
    .col-header > span:nth-child(n+3) { display: none; }
    .sub-row { grid-template-areas: "id source" "body body" "cluster cluster" "attrib attrib"; }
    .sub-row .sub-id { grid-area: id; }
    .sub-row .sub-source { grid-area: source; justify-self: start; }
    .sub-row .sub-body { grid-area: body; padding-top: 4px; }
    .sub-row .sub-cluster { grid-area: cluster; }
    .sub-row .sub-attrib { grid-area: attrib; }
  }
</style>
</head>
<body>

<header class="masthead">
  <div class="brand"><a href="index.html"><b>Argument Collapse</b></a></div>
  <nav class="nav">
    <a href="index.html">DEBATES</a>
    <a href="main_argument.html">MAIN_ARGUMENT</a>
    <a href="sub_argument.html" class="active">SUB_ARGUMENT</a>
  </nav>
</header>

<section class="hero">
  <div class="eyebrow">Sub-arguments · across all debates</div>
  <h1>What supporting points does each essay use?</h1>
  <p class="deck">Every sub-argument across 256 debates, with the main-argument cluster it belongs to and the essay/author it came from. Filter by source or debate; click a cluster name to drill in.</p>
</section>

<div class="body-grid">

  <aside class="sidebar">
    <input type="search" id="search-box" class="search-box" placeholder="Search sub-arg text…">
    <div class="filter-group">
      <div class="filter-head">Venue</div>
      <ul class="filter-list" data-filter="venue">
        <li class="active" data-val="all">All<span class="ct" id="ct-venue-all"></span></li>
        <li data-val="nyt">NYT<span class="ct" id="ct-venue-nyt"></span></li>
        <li data-val="br">Boston Review<span class="ct" id="ct-venue-br"></span></li>
      </ul>
    </div>
    <div class="filter-group">
      <div class="filter-head">Source</div>
      <ul class="filter-list" data-filter="source">
        <li class="active" data-val="all">All<span class="ct" id="ct-source-all"></span></li>
        <li data-val="h">Humans<span class="ct" id="ct-source-h"></span></li>
        <li data-val="v">Vanilla<span class="ct" id="ct-source-v"></span></li>
        <li data-val="d">Diversified<span class="ct" id="ct-source-d"></span></li>
      </ul>
    </div>
    <div class="filter-group">
      <div class="filter-head">Question type</div>
      <ul class="filter-list" data-filter="qtype">
        <li class="active" data-val="all">All<span class="ct" id="ct-qtype-all"></span></li>
        <li data-val="stance">Binary<span class="ct" id="ct-qtype-stance"></span></li>
        <li data-val="open_ended">Open-ended<span class="ct" id="ct-qtype-open"></span></li>
        <li data-val="lead_essay">Lead-essay<span class="ct" id="ct-qtype-lead"></span></li>
      </ul>
    </div>
  </aside>

  <main>
    <div class="toolbar">
      <div class="title" id="title-counter">Sub-arguments</div>
      <div class="sort">Sort: <span class="sort-btn active" data-sort="cluster">by cluster</span> · <span class="sort-btn" data-sort="source">by source</span> · <span class="sort-btn" data-sort="debate">by debate</span></div>
    </div>

    <div id="sub-table-container"></div>
    <div class="pagination" id="pagination"></div>

  </main>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById('data').textContent);
const debates = data.debates;     // {t,v,q,h}
const clusters = data.clusters;   // {d,i,t,h}
const rows = data.rows;           // {c,s,i,n,t,a}
const state = { venue:"all", source:"all", qtype:"all", search:"", sort:"cluster", page:0 };
const PAGE_SIZE = 200;
const SRC_LABEL = { h:"Human", v:"Vanilla", d:"Diversified" };
const VENUE_LABEL = { nyt:"NYT", br:"BR" };

function debateOf(r) { return debates[clusters[r.c].d]; }
function clusterOf(r) { return clusters[r.c]; }

function passes(r) {
  const d = debateOf(r);
  if (state.venue !== "all" && d.v !== state.venue) return false;
  if (state.source !== "all" && r.s !== state.source) return false;
  if (state.qtype !== "all" && d.q !== state.qtype) return false;
  if (state.search && !r.t.toLowerCase().includes(state.search.toLowerCase())) return false;
  return true;
}

function sortRows(arr) {
  if (state.sort === "cluster") {
    const so = ["h","v","d"];
    arr.sort((a,b) => {
      const da = debateOf(a).t, db = debateOf(b).t;
      return da.localeCompare(db) || a.c - b.c || so.indexOf(a.s) - so.indexOf(b.s);
    });
  } else if (state.sort === "source") {
    const so = ["h","v","d"];
    arr.sort((a,b) => so.indexOf(a.s)-so.indexOf(b.s) || debateOf(a).t.localeCompare(debateOf(b).t) || a.c - b.c);
  } else if (state.sort === "debate") {
    arr.sort((a,b) => debateOf(a).t.localeCompare(debateOf(b).t) || a.c - b.c);
  }
  return arr;
}

function subRowHtml(r) {
  return `<div class="sub-row">
    <span class="sub-id">${String(r.i).padStart(2,'0')} / ${String(r.n).padStart(2,'0')}</span>
    <span><span class="sub-source ${r.s}">${SRC_LABEL[r.s]}</span></span>
    <span class="sub-body">${r.t.replace(/</g,'&lt;')}</span>
    <span class="sub-author"><span class="author-name">${r.a.replace(/</g,'&lt;')}</span></span>
  </div>`;
}

function clusterGroupHtml(c, rs) {
  const d = debates[c.d];
  return `<div class="cluster-block">
    <div class="cluster-head-row">
      <span class="cluster-num">M${String(c.i).padStart(2,'0')}</span>
      <span class="cluster-title"><a href="${c.h}">${c.t.replace(/</g,'&lt;')}</a></span>
      <span class="debate-attrib"><span class="debate-pin">${VENUE_LABEL[d.v]}</span><a href="${d.h}">${d.t.replace(/</g,'&lt;')}</a></span>
    </div>
    <div class="cluster-subs">${rs.map(subRowHtml).join('')}</div>
  </div>`;
}

function render() {
  const filtered = sortRows(rows.filter(passes));
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (state.page >= pages) state.page = pages - 1;
  if (state.page < 0) state.page = 0;
  const start = state.page * PAGE_SIZE, end = Math.min(start + PAGE_SIZE, total);
  const slice = filtered.slice(start, end);

  // Group by cluster
  const grouped = {};
  const order = [];
  for (const r of slice) {
    if (!(r.c in grouped)) { grouped[r.c] = []; order.push(r.c); }
    grouped[r.c].push(r);
  }
  let html = '';
  for (const cIdx of order) {
    html += clusterGroupHtml(clusters[cIdx], grouped[cIdx]);
  }
  document.getElementById('sub-table-container').innerHTML = html || '<div style="padding:60px 20px;text-align:center;color:var(--quiet);font-style:italic;font-family:Newsreader,serif;">No sub-arguments match these filters.</div>';

  // pagination
  const pag = document.getElementById('pagination');
  if (total > PAGE_SIZE) {
    pag.innerHTML = `<button id="prev">‹ Prev</button><span class="ind">Page ${state.page+1} of ${pages} · showing ${start+1}-${end} of ${total.toLocaleString()}</span><button id="next">Next ›</button>`;
    document.getElementById('prev').onclick = () => { state.page--; render(); window.scrollTo(0,0); };
    document.getElementById('next').onclick = () => { state.page++; render(); window.scrollTo(0,0); };
    document.getElementById('prev').disabled = state.page <= 0;
    document.getElementById('next').disabled = state.page >= pages - 1;
  } else { pag.innerHTML = ''; }

  document.getElementById('title-counter').textContent = `${total.toLocaleString()} sub-argument${total===1?'':'s'}`;

  // sidebar counts
  const base = rows.filter(r => !state.search || r.t.toLowerCase().includes(state.search.toLowerCase()));
  document.getElementById('ct-venue-all').textContent = base.length.toLocaleString();
  document.getElementById('ct-venue-nyt').textContent = base.filter(r=>debateOf(r).v==='nyt').length.toLocaleString();
  document.getElementById('ct-venue-br').textContent = base.filter(r=>debateOf(r).v==='br').length.toLocaleString();
  const v = state.venue==='all' ? base : base.filter(r=>debateOf(r).v===state.venue);
  document.getElementById('ct-source-all').textContent = v.length.toLocaleString();
  document.getElementById('ct-source-h').textContent = v.filter(r=>r.s==='h').length.toLocaleString();
  document.getElementById('ct-source-v').textContent = v.filter(r=>r.s==='v').length.toLocaleString();
  document.getElementById('ct-source-d').textContent = v.filter(r=>r.s==='d').length.toLocaleString();
  const s = state.source==='all' ? v : v.filter(r=>r.s===state.source);
  document.getElementById('ct-qtype-all').textContent = s.length.toLocaleString();
  document.getElementById('ct-qtype-stance').textContent = s.filter(r=>debateOf(r).q==='stance').length.toLocaleString();
  document.getElementById('ct-qtype-open').textContent = s.filter(r=>debateOf(r).q==='open_ended').length.toLocaleString();
  document.getElementById('ct-qtype-lead').textContent = s.filter(r=>debateOf(r).q==='lead_essay').length.toLocaleString();
}

document.querySelectorAll('.filter-list[data-filter]').forEach(list => {
  const key = list.dataset.filter;
  list.querySelectorAll('li').forEach(li => {
    li.addEventListener('click', () => {
      list.querySelectorAll('li').forEach(l => l.classList.remove('active'));
      li.classList.add('active');
      state[key] = li.dataset.val;
      state.page = 0;
      render();
    });
  });
});
document.getElementById('search-box').addEventListener('input', e => { state.search = e.target.value; state.page = 0; render(); });
document.querySelectorAll('.sort-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.sort = btn.dataset.sort;
    state.page = 0;
    render();
  });
});

render();
</script>

</body>
</html>
"""
    html = html.replace("__DATA__", data_json)
    return html


def main():
    print("Loading toulmin essays…")
    toulmin = load_toulmin()
    print(f"  toulmin rows: {len(toulmin)}")

    print("Loading debate metadata…")
    debate_meta = load_debates()
    print(f"  debates: {len(debate_meta)}")

    print("Clustering essays by 'equivalent' pairs…")
    cmap = cluster_per_debate()
    print(f"  per-debate cluster maps: {len(cmap)}")

    print("Building per-debate cluster summaries…")
    per_debate_clusters = build_clusters(toulmin, cmap)
    print(f"  debates with clusters: {len(per_debate_clusters)}")
    total_clusters = sum(len(v) for v in per_debate_clusters.values())
    print(f"  total clusters: {total_clusters}")

    print("Rendering main_argument.html…")
    main_html = build_main_argument_html(per_debate_clusters, debate_meta)
    (DOCS / "main_argument.html").write_text(main_html)
    print(f"  main_argument.html: {(DOCS/'main_argument.html').stat().st_size:,} bytes")

    print("Rendering sub_argument.html…")
    sub_html = build_sub_argument_html(per_debate_clusters, debate_meta)
    (DOCS / "sub_argument.html").write_text(sub_html)
    print(f"  sub_argument.html: {(DOCS/'sub_argument.html').stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
