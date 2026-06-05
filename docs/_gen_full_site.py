#!/usr/bin/env python3
"""Generate full-dataset companion site: 256 debates from NYT+BR.

- index.html with all 256 cards + working filter/sort
- debate_<debate_id>.html for each (minimal template; existing 3 toy detail pages preserved)
"""
from pathlib import Path
import json, gzip, html as ihtml, re

ROOT = Path(__file__).parent.parent.resolve()
DOCS = Path(__file__).parent.resolve()
DATA_NYT = ROOT / "data" / "nyt"
DATA_BR = ROOT / "data" / "br"

# === Already-built toy detail pages map to specific debate_ids ===
TOY_DETAIL_MAP = {
    # debate_id → existing detail filename. Site links cards to these.
    "are-americans-too-obsessed-with-cleanliness": ("cleanliness.html",),
    "silicon-valley-goes-to-washington":            ("silicon_valley.html",),
    "forum_after_911":                              ("boston_review_civil_liberties.html",),
}

# Topic display names + sort order
TOPIC_LABEL = {
    "politics":     "Politics",
    "economy":      "Economy",
    "justice":      "Justice",
    "culture":      "Culture",
    "health":       "Health",
    "society":      "Society",
    "environment":  "Environment",
    "religion":     "Religion",
    "science_tech": "Science · Tech",
    "philosophy":   "Philosophy",
    "education":    "Education",
    "media":        "Media",
    "labor":        "Labor",
    "gender":       "Gender",
    "international":"International",
}

def topic_name(t):
    return TOPIC_LABEL.get(t, (t or "").replace("_", " ").title())

def esc(s):
    if s is None: return ""
    return ihtml.escape(str(s), quote=True)

def slugify(s):
    s = re.sub(r"[^\w]+", "-", (s or "")).strip("-").lower()
    return s[:60]

def excerpt(text, n=180):
    if not text: return ""
    text = re.sub(r"\s+", " ", text.strip())
    # Strip leading markdown heading
    text = re.sub(r"^#+\s*[^\n]*\n+", "", text).strip()
    if len(text) <= n: return text
    cut = text.rfind(" ", 0, n)
    return text[:cut if cut > 0 else n] + "…"

def debate_title(d):
    """Extract debate title from question_text first H1, fall back to title field."""
    q = d.get("question_text") or d.get("lead_essay_text") or ""
    m = re.match(r"^\s*#\s+(.+?)(?:\n|$)", q)
    if m:
        return m.group(1).strip()
    return d.get("title") or d.get("debate_id", "Untitled")

def question_body_only(d):
    """Strip the leading H1 from question_text/lead so the body alone is shown."""
    q = d.get("question_text") or d.get("lead_essay_text") or ""
    return re.sub(r"^\s*#\s+.+?\n+", "", q, count=1).strip()

def load_debates():
    rows = []
    for line in gzip.open(DATA_NYT / "debates.jsonl.gz", "rt"):
        d = json.loads(line)
        d["question_type_norm"] = d["question_type"]  # 'stance' | 'open_ended'
        rows.append(d)
    for line in gzip.open(DATA_BR / "debates.jsonl.gz", "rt"):
        d = json.loads(line)
        d["question_type_norm"] = "lead_essay"  # BR is lead-essay
        rows.append(d)
    return rows


# === Common CSS + nav ===
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
    --strong-oppose: #3a6479;
    --strong-support: #b85e3a;
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
"""

MOBILE_CSS = """
  @media (max-width: 900px) {
    .masthead { padding: 16px 20px; flex-wrap: wrap; gap: 12px; }
    .nav { gap: 18px; }
    .nav a { font-size: 10.5px; letter-spacing: 0.1em; }
    .hero { padding: 40px 20px 18px !important; }
    .hero h1 { font-size: 30px !important; }
    .hero .deck { font-size: 15px !important; }
    .body-grid { padding: 24px 20px 80px !important; grid-template-columns: 1fr !important; gap: 28px !important; }
    .sidebar { position: static !important; }
    .filter-group { margin-bottom: 20px; }
    .cards { grid-template-columns: 1fr !important; }
  }
"""


def build_index(debates):
    # Build cards as JSON-like data array, render with JS
    # That way filter/sort is fast and clean
    out = ['<!DOCTYPE html>\n<html lang="en">\n<head>']
    out.append('<meta charset="UTF-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append('<title>Argument Collapse · Debates</title>')
    out.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    out.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    out.append('<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">')
    out.append('<style>')
    out.append(CSS_BASE)
    out.append("""
  .hero { padding: 70px 40px 24px; max-width: 1280px; margin: 0 auto; }
  .hero .eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--quiet); margin-bottom: 16px; }
  .hero h1 { font-family: 'Newsreader', serif; font-weight: 500; font-size: 52px; line-height: 1.05; letter-spacing: -0.02em; margin-bottom: 16px; }
  .hero h1 em { font-style: italic; color: var(--quiet); font-weight: 400; }
  .hero .deck { font-family: 'Newsreader', serif; font-size: 17px; line-height: 1.55; color: var(--ink-soft); font-style: italic; max-width: 820px; }
  .hero .models-line { font-size: 11.5px; color: var(--quiet); letter-spacing: 0.04em; margin-top: 14px; }

  .body-grid { max-width: 1280px; margin: 0 auto; padding: 32px 40px 120px; display: grid; grid-template-columns: 220px 1fr; gap: 48px; }
  .sidebar { position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px); overflow-y: auto; }
  .filter-head { font-size: 10.5px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink); margin: 6px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--ink); }
  .filter-list { list-style: none; }
  .filter-list li { padding: 5px 0; font-size: 13px; color: var(--ink-soft); cursor: pointer; border-bottom: 1px solid var(--line-soft); display: flex; align-items: center; justify-content: space-between; transition: color 0.15s; }
  .filter-list li:hover { color: var(--ink); }
  .filter-list li.active { color: var(--ink); font-weight: 500; }
  .filter-list li .ct { font-size: 11px; color: var(--quiet); font-variant-numeric: tabular-nums; }
  .filter-list li.active .ct { color: var(--src-van); }
  .filter-group { margin-bottom: 26px; }
  .search-box {
    width: 100%;
    padding: 8px 10px;
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    border: 1px solid var(--line);
    border-radius: 3px;
    background: var(--paper);
    color: var(--ink);
    margin-bottom: 14px;
  }
  .search-box:focus { outline: none; border-color: var(--ink); }

  .toolbar { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: 8px; }
  .toolbar .title { font-family: 'Newsreader', serif; font-size: 22px; font-weight: 500; }
  .toolbar .sort { font-size: 11px; color: var(--quiet); letter-spacing: 0.06em; }
  .sort-btn { cursor: pointer; padding: 2px 0; border-bottom: 1px solid transparent; transition: color 0.15s, border-color 0.15s; }
  .sort-btn:hover { color: var(--ink); }
  .sort-btn.active { color: var(--ink); font-weight: 500; border-bottom-color: var(--ink); }

  .cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
  .card {
    background: var(--paper);
    border: 1px solid var(--line);
    padding: 22px 22px 20px;
    cursor: pointer;
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
    display: flex; flex-direction: column;
    min-height: 200px;
  }
  .card:hover { border-color: var(--ink); transform: translateY(-1px); box-shadow: 0 2px 0 var(--line-soft); }
  .card .topic-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .card .topic {
    font-size: 9.5px; font-weight: 600; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--quiet);
  }
  .card .venue {
    font-family: 'Inter', sans-serif;
    font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--quiet); border: 1px solid var(--line); padding: 1px 6px;
    border-radius: 2px; font-weight: 600;
  }
  .card .qtype {
    font-size: 9px; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--quiet); font-weight: 500;
  }
  .card h3 {
    font-family: 'Newsreader', serif; font-size: 18px;
    font-weight: 500; line-height: 1.25; letter-spacing: -0.005em;
    color: var(--ink); margin-bottom: 10px;
  }
  .card .excerpt {
    font-family: 'Newsreader', serif; font-size: 13.5px; line-height: 1.45;
    color: var(--ink-soft); flex: 1; margin-bottom: 14px;
  }
  .card .counts {
    display: flex; gap: 10px; font-size: 10.5px; color: var(--ink-soft);
    letter-spacing: 0.02em; font-variant-numeric: tabular-nums;
    padding-top: 12px; border-top: 1px solid var(--line-soft);
  }
  .card .counts .ct { display: flex; align-items: center; gap: 5px; }
  .card .counts .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .card .counts .dot.h { background: var(--src-human); }
  .card .counts .dot.v { background: var(--src-van); }
  .card .counts .dot.d { background: var(--src-div); }

  .empty { padding: 60px 20px; text-align: center; color: var(--quiet); font-size: 14px; font-style: italic; font-family: 'Newsreader', serif; }
""")
    out.append(MOBILE_CSS)
    out.append('</style>\n</head>\n<body>')

    out.append('<header class="masthead">')
    out.append('  <div class="brand"><b>Argument Collapse</b></div>')
    out.append('  <nav class="nav">')
    out.append('    <a href="index.html" class="active">DEBATES</a>')
    out.append('    <a href="main_argument.html">MAIN_ARGUMENT</a>')
    out.append('    <a href="sub_argument.html">SUB_ARGUMENT</a>')
    out.append('  </nav>')
    out.append('</header>')

    out.append('<section class="hero">')
    out.append('  <div class="eyebrow">Argument Collapse: LLMs Flatten Long-Form Public Debate &nbsp;·&nbsp; Yekyung Kim*, Yapei Chang*, Chau Minh Pham, Mohit Iyyer (2026)</div>')
    out.append('  <h1>What main arguments did <em>humans</em> and <em>LLMs</em> produce across these debates?</h1>')
    out.append('  <p class="deck">Browse 195 NYT Room for Debate debates and 61 Boston Review forums, comparing what writers originally published with what five LLM families (GPT-5.5, Claude Opus 4.7, DeepSeek V4 Pro, Gemini 3.1 Pro, MiniMax M2.7) produce under <b>vanilla</b> and <b>diversified</b> prompting.</p>')
    out.append('</section>')

    out.append('<div class="body-grid">')

    # Sidebar with venue/question type/topic filters
    out.append('  <aside class="sidebar">')
    out.append('    <input type="search" class="search-box" id="search-box" placeholder="Search debate titles…">')
    out.append('    <div class="filter-group">')
    out.append('      <div class="filter-head">Venue</div>')
    out.append('      <ul class="filter-list" data-filter="venue">')
    out.append('        <li class="active" data-val="all">All<span class="ct" id="ct-venue-all"></span></li>')
    out.append('        <li data-val="nyt">NYT Room for Debate<span class="ct" id="ct-venue-nyt"></span></li>')
    out.append('        <li data-val="br">Boston Review<span class="ct" id="ct-venue-br"></span></li>')
    out.append('      </ul>')
    out.append('    </div>')
    out.append('    <div class="filter-group">')
    out.append('      <div class="filter-head">Question type</div>')
    out.append('      <ul class="filter-list" data-filter="qtype">')
    out.append('        <li class="active" data-val="all">All<span class="ct" id="ct-qtype-all"></span></li>')
    out.append('        <li data-val="stance">Binary<span class="ct" id="ct-qtype-stance"></span></li>')
    out.append('        <li data-val="open_ended">Open-ended<span class="ct" id="ct-qtype-open"></span></li>')
    out.append('        <li data-val="lead_essay">Lead-essay<span class="ct" id="ct-qtype-lead"></span></li>')
    out.append('      </ul>')
    out.append('    </div>')
    out.append('    <div class="filter-group">')
    out.append('      <div class="filter-head">Topic</div>')
    out.append('      <ul class="filter-list" data-filter="topic">')
    out.append('        <li class="active" data-val="all">All<span class="ct" id="ct-topic-all"></span></li>')
    # Build topic items from data
    topics_seen = set()
    for d in debates:
        if d.get("topic"):
            topics_seen.add(d["topic"])
    for t in sorted(topics_seen, key=lambda x: TOPIC_LABEL.get(x, x)):
        out.append(f'        <li data-val="{esc(t)}">{esc(topic_name(t))}<span class="ct" id="ct-topic-{esc(t)}"></span></li>')
    out.append('      </ul>')
    out.append('    </div>')
    out.append('  </aside>')

    # Main column
    out.append('  <main>')
    out.append('    <div class="toolbar">')
    out.append('      <div class="title" id="result-title">256 debates</div>')
    out.append('      <div class="sort">Sort: '
               '<span class="sort-btn active" data-sort="alphabet">alphabet</span> · '
               '<span class="sort-btn" data-sort="humans">humans</span> · '
               '<span class="sort-btn" data-sort="vanilla">vanilla</span> · '
               '<span class="sort-btn" data-sort="diversified">diversified</span> · '
               '<span class="sort-btn" data-sort="date">date</span>'
               '</div>')
    out.append('    </div>')
    out.append('    <div class="cards" id="cards-container"></div>')
    out.append('  </main>')
    out.append('</div>')

    # === Data injection ===
    cards_data = []
    for d in debates:
        debate_id = d["debate_id"]
        # Map toy debates to existing detail pages
        if debate_id in TOY_DETAIL_MAP:
            href = TOY_DETAIL_MAP[debate_id][0]
        else:
            href = f"debate_{d['venue']}_{debate_id}.html"
        question_excerpt = excerpt(d.get("question_text") or d.get("lead_essay_text") or "", 160)
        cards_data.append({
            "id": debate_id,
            "venue": d["venue"],
            "qtype": d["question_type_norm"],
            "topic": d.get("topic") or "",
            "title": debate_title(d),
            "excerpt": question_excerpt,
            "humans": d["n_humans"],
            "vanilla": d["n_vanilla"],
            "diversified": d["n_diversified"],
            "date": d.get("date") or "",
            "href": href,
        })
    out.append('<script>')
    out.append(f'const debates = {json.dumps(cards_data, ensure_ascii=False)};')
    out.append("""
const state = { venue: "all", qtype: "all", topic: "all", search: "", sort: "alphabet" };
const VENUE_LABEL = { nyt: "NYT", br: "BR" };
const QTYPE_LABEL = { stance: "Binary", open_ended: "Open-ended", lead_essay: "Lead-essay" };

function passes(d) {
  if (state.venue !== "all" && d.venue !== state.venue) return false;
  if (state.qtype !== "all" && d.qtype !== state.qtype) return false;
  if (state.topic !== "all" && d.topic !== state.topic) return false;
  if (state.search && !d.title.toLowerCase().includes(state.search.toLowerCase())) return false;
  return true;
}

function topicName(t) {
  if (!t) return "";
  const map = {
    politics: "Politics", economy: "Economy", justice: "Justice", culture: "Culture",
    health: "Health", society: "Society", environment: "Environment", religion: "Religion",
    science_tech: "Science · Tech", philosophy: "Philosophy", education: "Education",
    media: "Media", labor: "Labor", gender: "Gender", international: "International",
  };
  return map[t] || t.replace(/_/g, " ");
}

function cardHtml(d) {
  return `<div class="card" data-href="${d.href}">
    <div class="topic-row">
      <span class="venue">${VENUE_LABEL[d.venue] || d.venue.toUpperCase()}</span>
      <span class="topic">${topicName(d.topic)}</span>
      <span class="qtype">· ${QTYPE_LABEL[d.qtype] || d.qtype}</span>
    </div>
    <h3>${d.title}</h3>
    <p class="excerpt">${d.excerpt}</p>
    <div class="counts">
      <span class="ct"><span class="dot h"></span>Humans <b>${d.humans}</b></span>
      <span class="ct"><span class="dot v"></span>Vanilla <b>${d.vanilla}</b></span>
      <span class="ct"><span class="dot d"></span>Diversified <b>${d.diversified}</b></span>
    </div>
  </div>`;
}

function sortRows(rows) {
  if (state.sort === "alphabet") rows.sort((a,b) => a.title.localeCompare(b.title));
  else if (state.sort === "humans") rows.sort((a,b) => b.humans - a.humans);
  else if (state.sort === "vanilla") rows.sort((a,b) => b.vanilla - a.vanilla);
  else if (state.sort === "diversified") rows.sort((a,b) => b.diversified - a.diversified);
  else if (state.sort === "date") rows.sort((a,b) => (b.date||"").localeCompare(a.date||""));
  return rows;
}

function updateCounts() {
  // Count debates passing all OTHER filters per facet value
  const baseFiltered = debates.filter(d =>
    (!state.search || d.title.toLowerCase().includes(state.search.toLowerCase())));
  // Venue counts
  document.getElementById("ct-venue-all").textContent = baseFiltered.length;
  ["nyt","br"].forEach(v => {
    const el = document.getElementById(`ct-venue-${v}`);
    if (el) el.textContent = baseFiltered.filter(d => d.venue===v).length;
  });
  // Qtype counts (respect venue)
  const fByVenue = state.venue==="all" ? baseFiltered : baseFiltered.filter(d => d.venue===state.venue);
  document.getElementById("ct-qtype-all").textContent = fByVenue.length;
  document.getElementById("ct-qtype-stance").textContent = fByVenue.filter(d => d.qtype==="stance").length;
  document.getElementById("ct-qtype-open").textContent = fByVenue.filter(d => d.qtype==="open_ended").length;
  document.getElementById("ct-qtype-lead").textContent = fByVenue.filter(d => d.qtype==="lead_essay").length;
  // Topic counts (respect venue+qtype)
  let fForTopic = fByVenue;
  if (state.qtype !== "all") fForTopic = fForTopic.filter(d => d.qtype===state.qtype);
  document.getElementById("ct-topic-all").textContent = fForTopic.length;
  document.querySelectorAll('[id^="ct-topic-"]').forEach(el => {
    const t = el.id.replace("ct-topic-","");
    if (t === "all") return;
    el.textContent = fForTopic.filter(d => d.topic===t).length;
  });
}

function render() {
  const filtered = sortRows(debates.filter(passes));
  const container = document.getElementById("cards-container");
  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty">No debates match these filters.</div>';
  } else {
    container.innerHTML = filtered.map(cardHtml).join("");
    // Wire card clicks
    container.querySelectorAll(".card").forEach(card => {
      card.addEventListener("click", (e) => {
        if (e.target.closest("a") || e.target.closest("button")) return;
        if (card.dataset.href) window.location.href = card.dataset.href;
      });
    });
  }
  document.getElementById("result-title").textContent =
    `${filtered.length} debate${filtered.length===1?'':'s'}`;
  updateCounts();
}

// Wire sidebar filters
document.querySelectorAll(".filter-list[data-filter]").forEach(list => {
  const key = list.dataset.filter;
  list.querySelectorAll("li").forEach(li => {
    li.addEventListener("click", () => {
      list.querySelectorAll("li").forEach(l => l.classList.remove("active"));
      li.classList.add("active");
      state[key] = li.dataset.val;
      render();
    });
  });
});

// Wire search
document.getElementById("search-box").addEventListener("input", (e) => {
  state.search = e.target.value;
  render();
});

// Wire sort
document.querySelectorAll(".sort-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".sort-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.sort = btn.dataset.sort;
    render();
  });
});

render();
""")
    out.append('</script>')
    out.append('</body>\n</html>')

    (DOCS / "index.html").write_text("\n".join(out))
    return cards_data


def build_thin_debate_page(d):
    """Generate a minimal debate detail page with title, question, source counts."""
    debate_id = d["debate_id"]
    if debate_id in TOY_DETAIL_MAP:
        return  # skip; existing rich page

    venue = d["venue"]
    fname = f"debate_{venue}_{debate_id}.html"
    qtype = d["question_type"] or "lead_essay"
    qtype_label = {"stance":"Binary stance debate", "open_ended":"Open-ended debate", "lead_essay":"Lead-essay forum"}[
        "stance" if qtype=="stance" else "open_ended" if qtype=="open_ended" else "lead_essay"
    ]
    topic = topic_name(d.get("topic"))
    venue_label = "NYT Room for Debate" if venue == "nyt" else "Boston Review"

    real_title = debate_title(d)
    body_question = question_body_only(d)
    body_question_html = ihtml.escape(body_question).replace("\n\n", "</p><p>").replace("\n", "<br>")
    if body_question_html:
        body_question_html = f"<p>{body_question_html}</p>"

    out = ['<!DOCTYPE html>\n<html lang="en">\n<head>']
    out.append('<meta charset="UTF-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append(f'<title>{esc(real_title)} · Argument Collapse</title>')
    out.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    out.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    out.append('<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">')
    out.append('<style>')
    out.append(CSS_BASE)
    out.append("""
  .page { max-width: 820px; margin: 0 auto; padding: 56px 40px 120px; }
  .crumb { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--quiet); }
  .crumb:hover { color: var(--ink); }
  .topic-row { display: flex; align-items: center; gap: 10px; margin-top: 20px; margin-bottom: 8px; }
  .venue-pin { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; color: var(--quiet); border: 1px solid var(--line); padding: 2px 8px; border-radius: 2px; }
  .topic { font-size: 10.5px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; color: var(--quiet); }
  .qtype { font-size: 10.5px; color: var(--quiet); letter-spacing: 0.04em; }
  h1.title { font-family: 'Newsreader', serif; font-weight: 500; font-size: 38px; line-height: 1.15; letter-spacing: -0.015em; margin-bottom: 18px; }
  .meta-line { font-size: 11.5px; color: var(--quiet); margin-bottom: 28px; }
  .meta-line .author { color: var(--ink-soft); font-style: italic; }
  .question-body { font-family: 'Newsreader', serif; font-size: 15.5px; line-height: 1.55; color: var(--ink-soft); margin-bottom: 36px; }
  .question-body p { margin-bottom: 14px; }
  .question-body p:last-child { margin-bottom: 0; }
  .counts-box { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; background: var(--paper-soft); padding: 18px 22px; border-radius: 4px; margin-bottom: 36px; }
  .count-cell { text-align: center; }
  .count-cell .num { font-family: 'Newsreader', serif; font-size: 28px; font-weight: 500; }
  .count-cell .label { font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 600; margin-top: 2px; }
  .count-cell.h .num { color: var(--src-human); } .count-cell.h .label { color: var(--src-human); }
  .count-cell.v .num { color: var(--src-van); } .count-cell.v .label { color: var(--src-van); }
  .count-cell.d .num { color: var(--src-div); } .count-cell.d .label { color: var(--src-div); }
  .coming-soon { padding: 20px 24px; background: var(--paper-soft); border-left: 3px solid var(--quiet); border-radius: 0 4px 4px 0; font-family: 'Newsreader', serif; font-size: 14px; line-height: 1.55; color: var(--ink-soft); }
  .coming-soon b { color: var(--ink); }
""")
    out.append(MOBILE_CSS)
    out.append('</style>\n</head>\n<body>')
    out.append('<header class="masthead">')
    out.append('  <div class="brand"><b>Argument Collapse</b></div>')
    out.append('  <nav class="nav">')
    out.append('    <a href="index.html" class="active">DEBATES</a>')
    out.append('    <a href="main_argument.html">MAIN_ARGUMENT</a>')
    out.append('    <a href="sub_argument.html">SUB_ARGUMENT</a>')
    out.append('  </nav>')
    out.append('</header>')

    out.append('<div class="page">')
    out.append('  <a href="index.html" class="crumb">← All debates</a>')
    out.append('  <div class="topic-row">')
    out.append(f'    <span class="venue-pin">{venue.upper()}</span>')
    if topic:
        out.append(f'    <span class="topic">{esc(topic)}</span>')
    out.append(f'    <span class="qtype">· {esc(qtype_label)}</span>')
    out.append('  </div>')
    out.append(f'  <h1 class="title">{esc(real_title)}</h1>')
    # Lead authors (BR)
    if d.get("lead_essay_authors"):
        out.append(f'  <div class="meta-line">Lead essay by <span class="author">{esc(", ".join(d["lead_essay_authors"]))}</span> · {esc(venue_label)} · {esc((d.get("date") or "")[:10])}</div>')
    else:
        out.append(f'  <div class="meta-line">{esc(venue_label)} · {esc((d.get("date") or "")[:10])}</div>')

    if body_question_html:
        out.append(f'  <div class="question-body">{body_question_html}</div>')

    out.append('  <div class="counts-box">')
    out.append(f'    <div class="count-cell h"><div class="num">{d["n_humans"]}</div><div class="label">Humans</div></div>')
    out.append(f'    <div class="count-cell v"><div class="num">{d["n_vanilla"]}</div><div class="label">Vanilla</div></div>')
    out.append(f'    <div class="count-cell d"><div class="num">{d["n_diversified"]}</div><div class="label">Diversified</div></div>')
    out.append('  </div>')

    out.append('  <div class="coming-soon">')
    out.append('    <b>Cluster analysis in progress.</b> The matrix view comparing humans, vanilla, and diversified essays across main-argument clusters — like the toy detail pages — is being generated for all 256 debates. In the meantime, the source counts above show the raw essay totals for this debate.')
    out.append('  </div>')

    out.append('</div>')
    out.append('</body>\n</html>')

    (DOCS / fname).write_text("\n".join(out))


def main():
    debates = load_debates()
    print(f"Loaded {len(debates)} debates ({sum(1 for d in debates if d['venue']=='nyt')} NYT + {sum(1 for d in debates if d['venue']=='br')} BR)")
    cards_data = build_index(debates)
    print(f"index.html: {len(cards_data)} cards")

    generated = 0
    skipped = 0
    for d in debates:
        if d["debate_id"] in TOY_DETAIL_MAP:
            skipped += 1
            continue
        build_thin_debate_page(d)
        generated += 1
    print(f"detail pages: {generated} generated, {skipped} skipped (toy)")


if __name__ == "__main__":
    main()
