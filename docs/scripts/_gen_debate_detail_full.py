#!/usr/bin/env python3
"""Generate full debate detail pages for all 253 non-toy debates.

Each page shows: title, question/lead essay, source counts, stance axis (binary only),
cluster matrix (humans × 5 LLM families × V/D), clickable rows that expand inline to
show essays + sub-arguments. Mirrors the cleanliness.html toy template's information
density without requiring per-cluster sub-pages.
"""
from pathlib import Path
import json, gzip, re, html as ihtml
from collections import defaultdict, Counter

ROOT = Path(__file__).parent.parent.parent
DOCS = Path(__file__).parent.parent
INTERNAL = ROOT.parent / "argument_collapse_internal"

# Reuse cluster builder from sibling generator
import sys
sys.path.insert(0, str(DOCS))
from _gen_main_sub_full import (
    load_toulmin, load_debates, cluster_per_debate, build_clusters,
    detail_href, debate_title, topic_label, INDEX_HREF_FOR_TOY,
)

# Stance data
sides  = json.load(open(INTERNAL / "analysis_stance/stage1_sides_merged.json"))
medoid = {r["cohort"]: r for r in json.load(open(INTERNAL / "plot/stance_v15a_medoid.json"))}


def aggregate_div():
    stage2 = json.load(open(INTERNAL / "analysis_stance/stage2_labels_merged.json"))
    per_cohort = defaultdict(Counter)
    for r in stage2:
        stem = r["stem"]
        if "__" not in stem: continue
        parts = stem.split("__")
        if len(parts) >= 4 and parts[3] == "v15a":
            per_cohort[r["cohort"]][r["label"]] += 1
    return per_cohort

div_dist = aggregate_div()


def bar_pcts(counts, total):
    if total == 0: return (0,0,0,0,0,0)
    return (
        round(counts.get("strong_oppose",0)/total*100),
        round(counts.get("weak_oppose",0)/total*100),
        round(counts.get("neutral",0)/total*100),
        round(counts.get("weak_support",0)/total*100),
        round(counts.get("strong_support",0)/total*100),
        total,
    )


def humans_bar(cohort):
    r = medoid.get(cohort)
    if not r: return (0,0,0,0,0,0)
    h_n = r["n_human"] - (r["h_sO"] + r["h_wO"] + r["h_wS"] + r["h_sS"])
    h_n = max(h_n, 0)
    c = {"strong_oppose":r["h_sO"],"weak_oppose":r["h_wO"],"neutral":h_n,"weak_support":r["h_wS"],"strong_support":r["h_sS"]}
    return bar_pcts(c, r["n_human"])


def vanilla_bar(cohort):
    r = medoid.get(cohort)
    if not r: return (0,0,0,0,0,0)
    l_n = r["n_medoid"] - (r["l_sO"] + r["l_wO"] + r["l_wS"] + r["l_sS"])
    l_n = max(l_n, 0)
    c = {"strong_oppose":r["l_sO"],"weak_oppose":r["l_wO"],"neutral":l_n,"weak_support":r["l_wS"],"strong_support":r["l_sS"]}
    return bar_pcts(c, r["n_medoid"])


def diversified_bar(cohort):
    d = div_dist.get(cohort, Counter())
    return bar_pcts(d, sum(d.values()))


def esc(s): return ihtml.escape(str(s or ""), quote=True)


CSS = """  :root {
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
    --weak-oppose:   #7e9fac;
    --neutral:       #b0aa9e;
    --weak-support:  #d99070;
    --strong-support:#b85e3a;
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

  .page { max-width: 1100px; margin: 0 auto; padding: 50px 40px 120px; }
  .crumb { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--quiet); }
  .crumb:hover { color: var(--ink); }
  .topic { font-size: 10.5px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--quiet); margin-top: 18px; }
  h1.debate-title { font-family: 'Newsreader', serif; font-weight: 500; font-size: 40px; line-height: 1.12; letter-spacing: -0.015em; margin: 8px 0 14px; }
  .question-body { font-family: 'Newsreader', serif; font-size: 15px; line-height: 1.55; color: var(--ink-soft); max-width: 820px; margin-bottom: 28px; }
  .question-body p { margin-bottom: 12px; }
  .question-body p:last-child { margin-bottom: 0; }

  .lead-box { background: #fff; border-left: 3px solid var(--src-human); padding: 18px 22px; margin-bottom: 28px; border-radius: 0 4px 4px 0; max-width: 820px; }
  .lead-head { font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600; color: var(--src-human); margin-bottom: 8px; }
  .lead-title { font-family: 'Newsreader', serif; font-size: 18px; font-weight: 500; font-style: italic; color: var(--ink); margin-bottom: 12px; line-height: 1.3; }
  .lead-link { display: inline-block; font-family: 'Inter', sans-serif; font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600; color: var(--src-human); border-bottom: 1px solid var(--src-human); padding-bottom: 1px; }
  .lead-link:hover { opacity: 0.7; }

  .axis { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 26px 0 22px; max-width: 720px; }
  .axis-side { padding: 10px 0 12px 14px; border-left: 2px solid; font-family: 'Newsreader', serif; font-size: 15px; line-height: 1.35; font-style: italic; color: var(--ink-soft); }
  .axis-side.oppose { border-left-color: var(--strong-oppose); }
  .axis-side.support { border-left-color: var(--strong-support); }
  .axis-tag { display: block; font-family: 'Inter', sans-serif; font-style: normal; font-size: 9.5px; letter-spacing: 0.18em; font-weight: 600; text-transform: uppercase; margin-bottom: 3px; }
  .axis-side.oppose .axis-tag { color: var(--strong-oppose); }
  .axis-side.support .axis-tag { color: var(--strong-support); }

  .agg-bars { margin: 0 0 46px; background: var(--paper-soft); padding: 14px 16px 12px; border-radius: 4px; max-width: 720px; }
  .bar-row { display: grid; grid-template-columns: 78px 1fr 44px; gap: 10px; align-items: center; margin-bottom: 8px; }
  .bar-row:last-child { margin-bottom: 0; }
  .bar-label { font-family: 'Inter', sans-serif; font-size: 10px; letter-spacing: 0.14em; font-weight: 500; text-transform: uppercase; color: var(--quiet); }
  .bar { height: 14px; display: flex; border-radius: 2px; overflow: hidden; }
  .seg { height: 100%; }
  .seg.so { background: var(--strong-oppose); }
  .seg.wo { background: var(--weak-oppose); }
  .seg.n  { background: var(--neutral); }
  .seg.ws { background: var(--weak-support); }
  .seg.ss { background: var(--strong-support); }
  .bar-num { font-family: 'Inter', sans-serif; font-size: 10.5px; color: var(--ink-soft); font-variant-numeric: tabular-nums; text-align: right; }

  .args-head { font-family: 'Newsreader', serif; font-size: 22px; font-weight: 500; margin-bottom: 6px; }
  .args-deck { font-family: 'Newsreader', serif; font-style: italic; font-size: 14.5px; color: var(--quiet); margin-bottom: 14px; max-width: 720px; }
  .ex-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 14px 0; margin-bottom: 22px; max-width: 820px; }
  .ex-item h4 { font-family: 'Inter', sans-serif; font-size: 11px; letter-spacing: 0.06em; font-weight: 600; text-transform: uppercase; margin-bottom: 7px; }
  .ex-item h4.ex-van { color: var(--src-van); }
  .ex-item h4.ex-div { color: var(--src-div); }
  .ex-item p { font-family: 'Newsreader', serif; font-size: 13.5px; line-height: 1.5; color: var(--ink-soft); }

  /* Matrix */
  .matrix { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
  .matrix th, .matrix td { padding: 8px 4px; font-size: 12px; text-align: center; }
  .matrix th.arg-head-col { text-align: left; padding-left: 0; font-family: 'Inter', sans-serif; font-size: 9.5px; letter-spacing: 0.10em; font-weight: 600; text-transform: uppercase; color: var(--quiet); width: 50%; vertical-align: bottom; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
  .matrix th.gh-human { font-size: 9.5px; letter-spacing: 0.10em; font-weight: 600; text-transform: uppercase; color: var(--quiet); vertical-align: bottom; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
  .matrix th.gap { width: 12px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }
  .matrix th.group-row-th { font-family: 'Inter', sans-serif; font-size: 9.5px; letter-spacing: 0.10em; font-weight: 600; text-transform: uppercase; color: var(--quiet); border-bottom: 1px solid var(--line); padding-bottom: 6px; }
  .matrix th.model-row-th { font-family: 'Inter', sans-serif; font-size: 9.5px; color: var(--ink); font-weight: 600; padding-top: 2px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
  .matrix .arg-col { width: 50%; }
  .matrix .humans-col { width: 60px; }
  .matrix .gap-col { width: 12px; }
  .matrix .model-col { width: 8%; }

  .matrix .arg-row td { padding: 12px 4px; border-bottom: 1px solid var(--line-soft); cursor: pointer; transition: background 0.12s; }
  .matrix .arg-row:hover td { background: rgba(0,0,0,0.025); }
  .matrix .arg-row.expanded td { background: var(--paper-soft); }
  .matrix .arg-row .arg-text { text-align: left; font-family: 'Newsreader', serif; font-size: 13.5px; line-height: 1.4; color: var(--ink); font-style: italic; padding-right: 8px; }
  .matrix .humans-pill { display: inline-block; font-size: 10.5px; font-weight: 600; padding: 2px 7px; border-radius: 2px; color: #fff; background: var(--src-human); font-variant-numeric: tabular-nums; }
  .matrix .humans-pill.zero { background: var(--line); color: var(--quiet); font-weight: 500; }
  .matrix .model-dots { display: flex; flex-direction: column; align-items: center; gap: 3px; }
  .matrix .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--line); }
  .matrix .dot.v.on { background: var(--src-van); }
  .matrix .dot.d.on { background: var(--src-div); }
  .matrix .dot.off { background: transparent; border: 1px dashed var(--line); }

  /* Expanded essay panel */
  .essay-panel-row td { padding: 0 !important; }
  .essay-panel { padding: 0 6px 18px; background: var(--paper-soft); }
  .essay-item { padding: 14px 0; border-bottom: 1px solid var(--line); }
  .essay-item:last-child { border-bottom: none; }
  .essay-meta { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
  .essay-src { font-family: 'Inter', sans-serif; font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 700; padding: 2px 7px; border-radius: 2px; color: #fff; }
  .essay-src.src-h { background: var(--src-human); }
  .essay-src.src-v { background: var(--src-van); }
  .essay-src.src-d { background: var(--src-div); }
  .essay-by { font-family: 'Inter', sans-serif; font-size: 11.5px; color: var(--ink-soft); font-weight: 500; }
  .essay-quote { font-family: 'Newsreader', serif; font-size: 14.5px; line-height: 1.55; color: var(--ink); font-style: italic; margin-bottom: 10px; }
  .essay-link { display: inline-block; font-family: 'Inter', sans-serif; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600; color: var(--src-human); border-bottom: 1px solid var(--src-human); padding-bottom: 1px; }
  .essay-link:hover { opacity: 0.7; }

  /* All-essays section */
  .essays-group { margin-bottom: 26px; }
  .essays-group-head { font-family: 'Inter', sans-serif; font-size: 10.5px; letter-spacing: 0.14em; font-weight: 700; text-transform: uppercase; color: var(--quiet); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line-soft); }
  .essay-row { display: flex; align-items: center; gap: 14px; padding: 9px 0; border-bottom: 1px solid var(--line-soft); flex-wrap: wrap; }
  .essay-row:last-child { border-bottom: none; }
  .essay-row .essay-by { flex: 1; min-width: 140px; font-size: 12.5px; color: var(--ink); }
  .essay-view-full {
    background: none; border: 1px solid var(--ink);
    border-radius: 999px; padding: 4px 12px;
    font-family: 'Inter', sans-serif; font-size: 10px;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600;
    color: var(--ink); cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }
  .essay-view-full:hover { background: var(--ink); color: var(--paper); }
  .essay-view-full.open { background: var(--ink); color: var(--paper); }
  .essay-full {
    width: 100%; margin: 8px 0 0;
    padding: 16px 20px;
    background: var(--paper-soft); border-radius: 4px;
    border-left: 3px solid var(--quiet);
  }
  .essay-full p { font-family: 'Newsreader', serif; font-size: 14px; line-height: 1.55; color: var(--ink-soft); margin-bottom: 12px; }
  .essay-full p:last-child { margin-bottom: 0; }
  .sub-head { font-family: 'Inter', sans-serif; font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; color: var(--quiet); margin: 8px 0 5px; }
  .sub-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 4px; }
  .sub-list li { display: grid; grid-template-columns: 22px 1fr; gap: 8px; padding: 7px 12px; background: #fff; border-left: 2px solid; border-radius: 0 2px 2px 0; align-items: baseline; }
  .sub-list li.src-h { border-left-color: var(--src-human); }
  .sub-list li.src-v { border-left-color: var(--src-van); }
  .sub-list li.src-d { border-left-color: var(--src-div); }
  .sub-list .num { font-family: 'Inter', sans-serif; font-size: 10px; color: var(--quiet); font-weight: 600; }
  .sub-list .sub-text { font-family: 'Newsreader', serif; font-size: 13px; line-height: 1.5; color: var(--ink-soft); }

  @media (max-width: 900px) {
    .masthead { padding: 16px 20px; }
    .nav { gap: 18px; }
    .nav a { font-size: 10.5px; }
    .page { padding: 28px 20px 80px; }
    h1.debate-title { font-size: 28px; }
    .axis { grid-template-columns: 1fr; }
    .ex-grid { grid-template-columns: 1fr; }
    .matrix-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 0 -20px; padding: 0 20px; }
    .matrix { min-width: 640px; }
    .matrix .arg-col { width: 50%; }
    .matrix .model-col { width: 50px; }
    .matrix th.model-row-th { font-size: 8.5px; padding: 2px 2px 8px; }
    .matrix th.gh-human { font-size: 8.5px; }
    .matrix .arg-row .arg-text { font-size: 12.5px; }
  }
"""


def build_question_html(body):
    if not body: return ""
    body = re.sub(r"^\s*#\s+.+?\n+", "", body, count=1).strip()
    if not body: return ""
    paras = re.split(r"\n\n+", body)
    return "".join(f"<p>{esc(p.replace(chr(10),' '))}</p>" for p in paras)


def nyt_essay_url(debate_id, essay_id, date):
    if not date: return None
    dp = "/".join(date.split("-")[:3])
    if len(dp.split("/")) != 3: return None
    return f"https://www.nytimes.com/roomfordebate/{dp}/{debate_id}/{essay_id}"


def br_essay_url(essay_id):
    return f"https://www.bostonreview.net/forum_response/{essay_id}/"


def render_debate(meta, clusters, human_essays_lookup, llm_essays_lookup):
    venue = meta["venue"]
    debate_id = meta["debate_id"]
    real_title = debate_title(meta)
    topic = topic_label(meta.get("topic"))
    qtype = meta.get("question_type") or "lead_essay"

    venue_label = "NYT Room for Debate" if venue == "nyt" else "Boston Review"
    qtype_label = {"stance":"Binary","open_ended":"Open-ended","lead_essay":"Lead-essay"}[
        "stance" if qtype=="stance" else "open_ended" if qtype=="open_ended" else "lead_essay"
    ]

    is_binary = (qtype == "stance")
    is_lead = (qtype == "lead_essay")

    side_data = sides.get(debate_id, {})

    # Build cluster matrix data
    matrix_rows = []
    cluster_essays = []  # list of (cluster_idx, [essay_item])
    MODELS_KEY = ["GPT","Claude","DeepSeek","Gemini","MiniMax"]

    # Build human essay lookup for this debate
    debate_humans = human_essays_lookup.get((venue, debate_id), {})

    for i, c in enumerate(clusters):
        row = {
            "main_arg": c["main_arg"],
            "n_humans": c["n_humans"],
            "vanilla_families": c["vanilla_families"],
            "diversified_families": c["diversified_families"],
        }
        matrix_rows.append(row)

        # Build essays-in-cluster panel content
        essays = []
        for e in c["sub_args_by_essay"]:
            essay_id = e["essay_id"]
            kind = e["kind"]
            subs = e.get("subs") or []
            family = e.get("family")
            if kind == "human":
                hinfo = debate_humans.get(essay_id, {})
                authors = ", ".join(hinfo.get("authors") or []) or essay_id
                date = hinfo.get("date") or ""
                if venue == "nyt":
                    url = nyt_essay_url(debate_id, essay_id, date)
                else:
                    url = br_essay_url(essay_id)
                essays.append({"kind":"h", "by": authors, "link": url, "subs": subs})
            elif kind == "vanilla":
                essays.append({"kind":"v", "by": family or "LLM", "subs": subs})
            elif kind == "diversified":
                essays.append({"kind":"d", "by": family or "LLM", "subs": subs})
        cluster_essays.append(essays)

    # === Render HTML ===
    out = []
    out.append('<!DOCTYPE html>\n<html lang="en">\n<head>')
    out.append('<meta charset="UTF-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append(f'<title>{esc(real_title)} · Argument Collapse</title>')
    out.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    out.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    out.append('<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">')
    out.append('<style>')
    out.append(CSS)
    out.append('</style>\n</head>\n<body>')

    out.append('<header class="masthead">')
    out.append('  <div class="brand"><a href="../index.html"><b>Argument Collapse</b></a></div>')
    out.append('  <nav class="nav">')
    out.append('    <a href="../index.html" class="active">DEBATES</a>')
    out.append('    <a href="../main_argument.html">MAIN_ARGUMENT</a>')
    out.append('    <a href="../sub_argument.html">SUB_ARGUMENT</a>')
    out.append('  </nav>')
    out.append('</header>')

    out.append('<div class="page">')
    out.append('  <a href="../index.html" class="crumb">← All debates</a>')
    out.append(f'  <div class="topic">{esc(venue_label)} · {esc(topic)} · {esc(qtype_label)}</div>')
    out.append(f'  <h1 class="debate-title">{esc(real_title)}</h1>')

    if is_lead:
        lead_text = meta.get("lead_essay_text") or ""
        lead_authors_list = meta.get("lead_essay_authors") or []
        lead_authors = ", ".join(lead_authors_list)
        # Extract lead essay title from first H1
        lead_title_match = re.match(r"^\s*#\s+(.+?)(?:\n|$)", lead_text or "")
        lead_title = lead_title_match.group(1).strip() if lead_title_match else ""
        # Build URL to original BR lead essay (Google search since BR URL pattern varies)
        from urllib.parse import quote
        if lead_authors_list:
            q = f'"{lead_authors_list[0]}" "{lead_title}" site:bostonreview.net' if lead_title else f'"{lead_authors_list[0]}" site:bostonreview.net'
            lead_url = f"https://www.google.com/search?q={quote(q)}"
        else:
            lead_url = f"https://www.google.com/search?q={quote((lead_title or '') + ' site:bostonreview.net')}"
        out.append(f'  <div class="lead-box">')
        out.append(f'    <div class="lead-head">Lead essay · {esc(lead_authors)}</div>')
        if lead_title:
            out.append(f'    <div class="lead-title">{esc(lead_title)}</div>')
        out.append(f'    <a class="lead-link" href="{esc(lead_url)}" target="_blank" rel="noopener">Read original on Boston Review ↗</a>')
        out.append(f'  </div>')
    else:
        qbody = build_question_html(meta.get("question_text") or "")
        if qbody:
            out.append(f'  <div class="question-body">{qbody}</div>')

    if is_binary:
        out.append('  <div class="axis">')
        out.append(f'    <div class="axis-side oppose"><span class="axis-tag">Oppose</span>{esc(side_data.get("oppose_side","Oppose"))}</div>')
        out.append(f'    <div class="axis-side support"><span class="axis-tag">Support</span>{esc(side_data.get("support_side","Support"))}</div>')
        out.append('  </div>')

        # Aggregate stance bars
        h = humans_bar(debate_id); v = vanilla_bar(debate_id); dv = diversified_bar(debate_id)
        out.append('  <div class="agg-bars">')
        for label, bar in [("Humans", h), ("Vanilla", v), ("Diversified", dv)]:
            so, wo, nu, ws, ss, n = bar
            out.append(f'    <div class="bar-row"><span class="bar-label">{label}</span>')
            out.append('      <div class="bar">')
            out.append(f'        <div class="seg so" style="width: {so}%;"></div>')
            out.append(f'        <div class="seg wo" style="width: {wo}%;"></div>')
            out.append(f'        <div class="seg n"  style="width: {nu}%;"></div>')
            out.append(f'        <div class="seg ws" style="width: {ws}%;"></div>')
            out.append(f'        <div class="seg ss" style="width: {ss}%;"></div>')
            out.append('      </div>')
            out.append(f'      <span class="bar-num">n={n}</span></div>')
        out.append('  </div>')

    # Main arguments section
    out.append(f'  <div class="args-head">Main arguments</div>')
    out.append(f'  <p class="args-deck">Each row groups essays that converge on the same main argument. Top dot = vanilla, bottom dot = diversified. Click a row to expand all essays in that cluster.</p>')

    out.append('  <div class="ex-grid">')
    out.append('    <div class="ex-item"><h4 class="ex-van">Vanilla</h4><p>The basic prompting condition. Each model is given the debate question with no further instruction. We report the most representative essay per LLM family, so vanilla totals five essays per debate.</p></div>')
    out.append('    <div class="ex-item"><h4 class="ex-div">Diversified</h4><p>The same five models are asked the same question but explicitly instructed to produce varied responses. Many essays per family are sampled, roughly twenty per family per debate.</p></div>')
    out.append('  </div>')

    # Matrix
    out.append('  <div class="matrix-wrap"><table class="matrix" id="cluster-matrix"><colgroup>')
    out.append('    <col class="arg-col"><col class="humans-col"><col class="gap-col">')
    out.append('    <col class="model-col"><col class="model-col"><col class="model-col"><col class="model-col"><col class="model-col">')
    out.append('  </colgroup><thead>')
    out.append('    <tr><th class="arg-head-col" rowspan="2">Argument cluster</th>')
    out.append('        <th class="gh-human">Humans</th><th class="gap"></th>')
    out.append('        <th class="group-row-th" colspan="5"><span style="color:var(--src-van);">Vanilla</span> · <span style="color:var(--src-div);">Diversified</span></th></tr>')
    out.append(f'    <tr><th class="gh-human">n={meta["n_humans"]}</th><th class="gap"></th>')
    out.append('        <th class="model-row-th">GPT</th><th class="model-row-th">Claude</th>')
    out.append('        <th class="model-row-th">DeepSeek</th><th class="model-row-th">Gemini</th>')
    out.append('        <th class="model-row-th">MiniMax</th></tr>')
    out.append('  </thead><tbody>')

    for ci, row in enumerate(matrix_rows, 1):
        cluster_href = f"../clusters/debate_{venue}_{debate_id}_arg_{ci}.html"
        out.append(f'    <tr class="arg-row" data-href="{esc(cluster_href)}">')
        out.append(f'      <td class="arg-text">{esc(row["main_arg"])}</td>')
        zero = "zero" if row["n_humans"] == 0 else ""
        out.append(f'      <td><span class="humans-pill {zero}">{row["n_humans"]}</span></td>')
        out.append('      <td></td>')
        for m in MODELS_KEY:
            v = row["vanilla_families"].get(m, 0) > 0
            d = row["diversified_families"].get(m, 0) > 0
            v_cls = "on" if v else "off"
            d_cls = "on" if d else "off"
            out.append(f'      <td><div class="model-dots"><div class="dot v {v_cls}"></div><div class="dot d {d_cls}"></div></div></td>')
        out.append('    </tr>')

    out.append('  </tbody></table></div>')

    # === All essays section ===
    out.append('  <div style="margin-top: 56px;"></div>')
    out.append('  <div class="args-head">All essays</div>')
    out.append('  <p class="args-deck">Quick access to every essay in this debate. Click <b>Read original</b> for human essays (links to the venue) or <b>View full essay</b> to expand an LLM-generated one in place.</p>')

    fmap = {"gpt-5.5":"GPT-5.5", "anthropic-claude-opus-4.7":"Claude Opus 4.7",
            "deepseek-deepseek-v4-pro":"DeepSeek V4 Pro", "vertex-api__gemini-3.1-pro-preview":"Gemini 3.1 Pro",
            "minimax-minimax-m2.7":"MiniMax M2.7"}
    def fam_disp(f):
        return fmap.get(f, f or "LLM")

    # HUMANS
    if debate_humans:
        out.append('  <div class="essays-group">')
        out.append('    <div class="essays-group-head">Humans</div>')
        for essay_id, info in sorted(debate_humans.items()):
            authors = ", ".join(info.get("authors") or []) or essay_id
            date = info.get("date") or ""
            url = nyt_essay_url(debate_id, essay_id, date) if venue == "nyt" else br_essay_url(essay_id)
            out.append('    <div class="essay-row">')
            out.append(f'      <span class="essay-src src-h">Human</span>')
            out.append(f'      <span class="essay-by">{esc(authors)}</span>')
            if url:
                out.append(f'      <a class="essay-link" href="{esc(url)}" target="_blank" rel="noopener">Read original ↗</a>')
            out.append('    </div>')
        out.append('  </div>')

    # LLM essays (vanilla reps + diversified)
    llm_for_debate = llm_essays_lookup.get((venue, debate_id), [])
    vanillas = sorted([e for e in llm_for_debate if e["kind"]=="vanilla"], key=lambda e: e["family"])
    divers   = sorted([e for e in llm_for_debate if e["kind"]=="diversified"], key=lambda e: (e["family"], e["essay_id"]))

    if vanillas:
        out.append('  <div class="essays-group">')
        out.append('    <div class="essays-group-head">Vanilla (5 representatives, one per LLM family)</div>')
        for i, e in enumerate(vanillas):
            tid = f"d-full-v-{i}"
            out.append('    <div class="essay-row">')
            out.append(f'      <span class="essay-src src-v">Vanilla</span>')
            out.append(f'      <span class="essay-by">{esc(fam_disp(e["family"]))}</span>')
            if e["body"]:
                out.append(f'      <button class="essay-view-full" data-target="{tid}">View full essay</button>')
                out.append('    </div>')
                out.append(f'    <div class="essay-full" id="{tid}" style="display:none;">')
                for para in [p.strip() for p in re.split(r"\n\n+", e["body"].strip()) if p.strip()]:
                    out.append(f'      <p>{esc(para)}</p>')
                out.append('    </div>')
            else:
                out.append('    </div>')
        out.append('  </div>')

    if divers:
        out.append('  <div class="essays-group">')
        out.append(f'    <div class="essays-group-head">Diversified ({len(divers)} essays)</div>')
        for i, e in enumerate(divers):
            tid = f"d-full-d-{i}"
            out.append('    <div class="essay-row">')
            out.append(f'      <span class="essay-src src-d">Diversified</span>')
            out.append(f'      <span class="essay-by">{esc(fam_disp(e["family"]))}</span>')
            if e["body"]:
                out.append(f'      <button class="essay-view-full" data-target="{tid}">View full essay</button>')
                out.append('    </div>')
                out.append(f'    <div class="essay-full" id="{tid}" style="display:none;">')
                for para in [p.strip() for p in re.split(r"\n\n+", e["body"].strip()) if p.strip()]:
                    out.append(f'      <p>{esc(para)}</p>')
                out.append('    </div>')
            else:
                out.append('    </div>')
        out.append('  </div>')

    out.append('</div>')

    out.append('''<script>
document.querySelectorAll('tr.arg-row').forEach(row => {
  row.addEventListener('click', () => {
    const href = row.dataset.href;
    if (href) window.location.href = href;
  });
});
document.querySelectorAll('.essay-view-full').forEach(btn => {
  btn.addEventListener('click', () => {
    const t = document.getElementById(btn.dataset.target);
    if (!t) return;
    const open = t.style.display !== 'none';
    t.style.display = open ? 'none' : 'block';
    btn.classList.toggle('open', !open);
    btn.textContent = open ? 'View full essay' : 'Hide full essay';
  });
});
</script>''')

    out.append('</body>\n</html>')
    return "\n".join(out)


def build_humans_lookup():
    lookup = defaultdict(dict)
    for p in ["data/nyt/human_essays.jsonl.gz", "data/br/human_essays.jsonl.gz"]:
        for line in gzip.open(ROOT/p, "rt"):
            d = json.loads(line)
            lookup[(d["venue"], d["debate_id"])][d["essay_id"]] = d
    return lookup


def build_llm_essays_lookup():
    """Return: (venue, debate_id) -> list of {essay_id, kind, family, body, is_rep}."""
    lookup = defaultdict(list)
    for p in ["data/nyt/llm_essays.jsonl.gz", "data/br/llm_essays.jsonl.gz"]:
        for line in gzip.open(ROOT/p, "rt"):
            d = json.loads(line)
            if d["kind"] not in ("vanilla", "diversified"): continue
            # Only keep vanilla representatives; keep all diversified
            if d["kind"] == "vanilla" and not d.get("is_representative"): continue
            lookup[(d["venue"], d["debate_id"])].append({
                "essay_id": d["essay_id"],
                "kind": d["kind"],
                "family": d.get("model_family") or "",
                "body": d.get("body_text") or "",
                "is_rep": d.get("is_representative", False),
            })
    return lookup


def main():
    print("Loading toulmin…")
    toulmin = load_toulmin()
    print("Loading debates…")
    debate_meta = load_debates()
    print("Building cluster map…")
    cmap = cluster_per_debate()
    print("Building cluster summaries…")
    per_debate_clusters = build_clusters(toulmin, cmap)
    print("Loading human essay metadata…")
    humans_lookup = build_humans_lookup()
    print("Loading LLM essay bodies…")
    llm_essays_lookup = build_llm_essays_lookup()
    print(f"  LLM essays loaded: {sum(len(v) for v in llm_essays_lookup.values())}")

    generated = 0
    skipped = 0
    for key, clusters in per_debate_clusters.items():
        venue, debate_id = key
        if key in INDEX_HREF_FOR_TOY:
            skipped += 1
            continue
        meta = debate_meta.get(key)
        if not meta: continue
        html = render_debate(meta, clusters, humans_lookup, llm_essays_lookup)
        fname = DOCS / "debates" / f"debate_{venue}_{debate_id}.html"
        fname.write_text(html)
        generated += 1
    print(f"Generated: {generated} debate pages, skipped: {skipped} (toy)")


if __name__ == "__main__":
    main()
