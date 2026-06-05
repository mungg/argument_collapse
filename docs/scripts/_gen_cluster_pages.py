#!/usr/bin/env python3
"""Generate per-cluster detail pages for all 253 non-toy debates.

Each cluster page mirrors the toy template (cleanliness_arg_1.html, etc):
- crumb back to debate page
- main argument quote (h1)
- list of essays with author + main arg quote + Read original (humans) or full essay (LLM)
- sub-arguments list per essay
"""
from pathlib import Path
import json, gzip, re, html as ihtml
from collections import defaultdict
from urllib.parse import quote

ROOT = Path(__file__).parent.parent.parent
DOCS = Path(__file__).parent.parent

import sys
sys.path.insert(0, str(DOCS))
from _gen_main_sub_full import (
    load_toulmin, load_debates, cluster_per_debate, build_clusters,
    debate_title, topic_label, INDEX_HREF_FOR_TOY,
)
from _gen_debate_detail_full import build_humans_lookup, nyt_essay_url, br_essay_url


def build_llm_body_lookup():
    """Map (venue, debate_id, essay_id) -> body_text for LLM essays."""
    lookup = {}
    for p in ["data/nyt/llm_essays.jsonl.gz", "data/br/llm_essays.jsonl.gz"]:
        for line in gzip.open(ROOT / p, "rt"):
            d = json.loads(line)
            if d["kind"] in ("vanilla", "diversified"):
                lookup[(d["venue"], d["debate_id"], d["essay_id"])] = d.get("body_text") or ""
    return lookup


def esc(s): return ihtml.escape(str(s or ""), quote=True)


CSS = """  :root {
    --paper: #f6f3ec;
    --paper-soft: #efebe1;
    --ink: #1c1917;
    --ink-soft: #44403c;
    --quiet: #76706a;
    --line: #d8d2c4;
    --line-soft: #e6dfd1;
    --src-h:  #2d8654;
    --src-v:  #b85e3a;
    --src-d:  #7c5e9a;
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

  .page { max-width: 920px; margin: 0 auto; padding: 56px 40px 120px; }
  .crumb { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--quiet); }
  .crumb:hover { color: var(--ink); }
  .crumb-context { font-size: 11px; letter-spacing: 0.04em; color: var(--quiet); margin-top: 6px; }
  .crumb-context a { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }

  h1.arg-title { font-family: 'Newsreader', serif; font-weight: 500; font-size: 30px; line-height: 1.25; letter-spacing: -0.01em; margin: 28px 0 14px; font-style: italic; color: var(--ink); }
  .arg-meta { font-size: 11.5px; color: var(--quiet); letter-spacing: 0.04em; margin-bottom: 40px; }

  .section-head { font-family: 'Inter', sans-serif; font-size: 10.5px; letter-spacing: 0.16em; font-weight: 600; text-transform: uppercase; color: var(--ink); margin-bottom: 24px; padding-bottom: 8px; border-bottom: 1px solid var(--ink); }

  .essay-item { padding: 24px 0; border-bottom: 1px solid var(--line); }
  .essay-item:last-child { border-bottom: none; }
  .essay-meta { display: flex; align-items: center; gap: 14px; margin-bottom: 8px; }
  .essay-src { font-family: 'Inter', sans-serif; font-size: 9.5px; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 700; padding: 3px 8px; border-radius: 2px; }
  .essay-src.src-h { color: #fff; background: var(--src-h); }
  .essay-src.src-v { color: #fff; background: var(--src-v); }
  .essay-src.src-d { color: #fff; background: var(--src-d); }
  .essay-by { font-family: 'Inter', sans-serif; font-size: 12.5px; color: var(--ink); font-weight: 500; letter-spacing: 0.01em; }

  .essay-quote { font-family: 'Newsreader', serif; font-size: 15.5px; line-height: 1.55; color: var(--ink); font-style: italic; margin-bottom: 14px; }
  .essay-link { display: inline-block; margin-bottom: 14px; font-family: 'Inter', sans-serif; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600; color: var(--src-h); border-bottom: 1px solid var(--src-h); padding-bottom: 1px; transition: opacity 0.15s; }
  .essay-link:hover { opacity: 0.7; }
  .essay-view-full {
    background: none; border: 1px solid var(--ink);
    border-radius: 999px; padding: 5px 14px;
    font-family: 'Inter', sans-serif; font-size: 10.5px;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600;
    color: var(--ink); cursor: pointer; margin-bottom: 14px;
    transition: background 0.15s, color 0.15s;
  }
  .essay-view-full:hover { background: var(--ink); color: var(--paper); }
  .essay-view-full.open { background: var(--ink); color: var(--paper); }
  .essay-full {
    margin-bottom: 14px; padding: 16px 20px;
    background: var(--paper-soft); border-radius: 4px;
    border-left: 3px solid var(--quiet);
  }
  .essay-full p {
    font-family: 'Newsreader', serif;
    font-size: 14.5px; line-height: 1.6;
    color: var(--ink-soft); margin-bottom: 12px;
  }
  .essay-full p:last-child { margin-bottom: 0; }

  .essay-subs { margin-top: 14px; }
  .sub-head { font-family: 'Inter', sans-serif; font-size: 9.5px; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600; color: var(--quiet); margin-bottom: 10px; }
  .sub-list { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: 1fr; gap: 7px; }
  .sub-list li { display: grid; grid-template-columns: 32px 1fr; gap: 12px; padding: 12px 16px; background: var(--paper-soft); border-left: 3px solid; border-radius: 0 4px 4px 0; align-items: baseline; }
  .sub-list li.src-h { border-left-color: var(--src-h); }
  .sub-list li.src-v { border-left-color: var(--src-v); }
  .sub-list li.src-d { border-left-color: var(--src-d); }
  .sub-list .num { font-family: 'Inter', sans-serif; font-size: 10.5px; color: var(--quiet); font-weight: 700; letter-spacing: 0.04em; font-variant-numeric: tabular-nums; }
  .sub-list .sub-text { font-family: 'Newsreader', serif; font-size: 14px; line-height: 1.5; color: var(--ink-soft); }

  @media (max-width: 900px) {
    .masthead { padding: 16px 20px; flex-wrap: wrap; gap: 12px; }
    .nav { gap: 18px; }
    .nav a { font-size: 10.5px; letter-spacing: 0.1em; }
    .page { padding: 28px 20px 80px; }
    h1.arg-title { font-size: 22px; }
    .essay-quote { font-size: 14.5px; }
  }
"""


def render_cluster_page(venue, debate_id, debate_title_str, debate_href, cluster_idx, cluster, humans_lookup, llm_body_lookup, total_clusters):
    out = ['<!DOCTYPE html>\n<html lang="en">\n<head>']
    out.append('<meta charset="UTF-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append(f'<title>{esc(cluster["main_arg"][:60])}... · Argument Collapse</title>')
    out.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    out.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    out.append('<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">')
    out.append('<style>')
    out.append(CSS)
    out.append('</style>\n</head>\n<body>')

    out.append('<header class="masthead">')
    out.append('  <div class="brand"><a href="../index.html"><b>Argument Collapse</b></a></div>')
    out.append('  <nav class="nav">')
    out.append('    <a href="../index.html">DEBATES</a>')
    out.append('    <a href="../main_argument.html">MAIN_ARGUMENT</a>')
    out.append('    <a href="../sub_argument.html" class="active">SUB_ARGUMENT</a>')
    out.append('  </nav>')
    out.append('</header>')

    out.append('<div class="page">')
    out.append(f'  <a href="{esc(debate_href)}" class="crumb">← Back to debate</a>')
    out.append(f'  <div class="crumb-context"><a href="{esc(debate_href)}">{esc(debate_title_str)}</a> · Cluster {cluster_idx} of {total_clusters}</div>')
    out.append(f'  <h1 class="arg-title">"{esc(cluster["main_arg"])}"</h1>')
    n_h = cluster["n_humans"]
    n_total = cluster["n_essays"]
    out.append(f'  <div class="arg-meta">{n_h} human · {n_total - n_h} LLM · {n_total} essays in this cluster</div>')
    out.append('  <div class="section-head">Main arguments in this cluster</div>')

    # Build human lookup for this debate
    debate_humans = humans_lookup.get((venue, debate_id), {})

    for e in cluster["sub_args_by_essay"]:
        essay_id = e["essay_id"]
        kind = e["kind"]
        subs = e.get("subs") or []
        family = e.get("family")
        main_arg_quote = e.get("main_argument") or ""
        out.append('      <div class="essay-item">')
        out.append('        <div class="essay-meta">')
        if kind == "human":
            hinfo = debate_humans.get(essay_id, {})
            authors = ", ".join(hinfo.get("authors") or []) or essay_id
            date = hinfo.get("date") or ""
            url = nyt_essay_url(debate_id, essay_id, date) if venue == "nyt" else br_essay_url(essay_id)
            out.append(f'          <span class="essay-src src-h">Human</span>')
            out.append(f'          <span class="essay-by">{esc(authors)}</span>')
            out.append('        </div>')
            if main_arg_quote:
                out.append(f'        <p class="essay-quote">"{esc(main_arg_quote)}"</p>')
            if url:
                out.append(f'        <a class="essay-link" href="{esc(url)}" target="_blank" rel="noopener">Read original ↗</a>')
        elif kind == "vanilla" or kind == "diversified":
            label = "Vanilla" if kind == "vanilla" else "Diversified"
            src_short = "src-v" if kind == "vanilla" else "src-d"
            out.append(f'          <span class="essay-src {src_short}">{label}</span>')
            out.append(f'          <span class="essay-by">{esc(family or "LLM")}</span>')
            out.append('        </div>')
            if main_arg_quote:
                out.append(f'        <p class="essay-quote">"{esc(main_arg_quote)}"</p>')
            body = llm_body_lookup.get((venue, debate_id, essay_id), "")
            if body:
                target_id = f"full-{cluster_idx}-{abs(hash(essay_id)) % 100000:05d}"
                out.append(f'        <button class="essay-view-full" data-target="{target_id}">View full essay</button>')
                out.append(f'        <div class="essay-full" id="{target_id}" style="display:none;">')
                # split body into paragraphs
                paras = [p.strip() for p in re.split(r"\n\n+", body.strip()) if p.strip()]
                for para in paras:
                    out.append(f'            <p>{esc(para)}</p>')
                out.append('        </div>')

        if subs:
            out.append('        <div class="essay-subs">')
            out.append('          <div class="sub-head">Sub-arguments</div>')
            out.append('          <ol class="sub-list">')
            src_cls = "src-h" if kind == "human" else ("src-v" if kind == "vanilla" else "src-d")
            for si, s in enumerate(subs, 1):
                out.append(f'              <li class="{src_cls}"><span class="num">{si:02d}</span><span class="sub-text">{esc(s)}</span></li>')
            out.append('          </ol>')
            out.append('        </div>')
        out.append('      </div>')

    out.append('</div>')
    out.append('''<script>
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


def main():
    print("Loading data…")
    toulmin = load_toulmin()
    debate_meta = load_debates()
    cmap = cluster_per_debate()
    per_debate_clusters = build_clusters(toulmin, cmap)
    humans_lookup = build_humans_lookup()
    print("Loading LLM essay bodies…")
    llm_body_lookup = build_llm_body_lookup()
    print(f"  LLM essays loaded: {len(llm_body_lookup)}")

    # Augment per_debate_clusters: add main_argument per essay (from toulmin)
    # build_clusters already includes sub_args_by_essay; need to also include main_argument per essay
    # Re-build with main_argument
    print("Augmenting per-essay main_argument…")
    toulmin_lookup = {}
    for t in toulmin:
        toulmin_lookup[(t["venue"], t["debate_id"], t["essay_id"])] = t.get("main_argument") or ""

    for key, clusters in per_debate_clusters.items():
        venue, debate_id = key
        for c in clusters:
            for e in c["sub_args_by_essay"]:
                e["main_argument"] = toulmin_lookup.get((venue, debate_id, e["essay_id"]), "")

    generated = 0
    skipped_debates = 0
    for key, clusters in per_debate_clusters.items():
        venue, debate_id = key
        if key in INDEX_HREF_FOR_TOY:
            skipped_debates += 1
            continue
        meta = debate_meta.get(key)
        if not meta: continue
        dtitle = debate_title(meta)
        dhref = f"../debates/debate_{venue}_{debate_id}.html"
        total = len(clusters)
        for ci, c in enumerate(clusters, 1):
            html = render_cluster_page(venue, debate_id, dtitle, dhref, ci, c, humans_lookup, llm_body_lookup, total)
            fname = DOCS / "clusters" / f"debate_{venue}_{debate_id}_arg_{ci}.html"
            fname.write_text(html)
            generated += 1
    print(f"Generated: {generated} cluster pages, skipped {skipped_debates} toy debates")


if __name__ == "__main__":
    main()
