#!/usr/bin/env python3
"""Generate index.html with all 256 debate cards.

Preserves the original card design exactly: axis + 5-color stance bars for binary
NYT debates; simpler counts variant for open-ended NYT and BR lead-essay forums.
"""
from pathlib import Path
import json, gzip, re
from collections import defaultdict, Counter

ROOT = Path(__file__).parent.parent.parent
DOCS = Path(__file__).parent.parent
INTERNAL = ROOT.parent / "argument_collapse_internal"


def load_debates():
    rows = []
    for line in gzip.open(ROOT / "data/nyt/debates.jsonl.gz", "rt"):
        d = json.loads(line)
        d["question_type_norm"] = d["question_type"]
        rows.append(d)
    for line in gzip.open(ROOT / "data/br/debates.jsonl.gz", "rt"):
        d = json.loads(line)
        d["question_type_norm"] = "lead_essay"
        rows.append(d)
    return rows


sides  = json.load(open(INTERNAL / "analysis_stance/stage1_sides_merged.json"))
medoid = {r["cohort"]: r for r in json.load(open(INTERNAL / "plot/stance_v15a_medoid.json"))}

# Cluster data (built from main_argument_pairs + toulmin)
import sys
sys.path.insert(0, str(DOCS))
from _gen_main_sub_full import load_toulmin, cluster_per_debate, build_clusters as build_clusters_full
print("Loading cluster data for open-card distributions...")
_TOULMIN = load_toulmin()
_CMAP = cluster_per_debate()
_PER_DEBATE_CLUSTERS = build_clusters_full(_TOULMIN, _CMAP)
print(f"  loaded {len(_PER_DEBATE_CLUSTERS)} debate cluster sets")


def aggregate_div():
    stage2 = json.load(open(INTERNAL / "analysis_stance/stage2_labels_merged.json"))
    per_cohort = defaultdict(Counter)
    for r in stage2:
        stem = r["stem"]
        if "__" not in stem:
            continue
        parts = stem.split("__")
        if len(parts) >= 4 and parts[3] == "v15a":
            per_cohort[r["cohort"]][r["label"]] += 1
    return per_cohort

div_dist = aggregate_div()


def bar_pcts(counts, total):
    if total == 0:
        return (0, 0, 0, 0, 0, 0)
    so = round(counts.get("strong_oppose", 0) / total * 100)
    wo = round(counts.get("weak_oppose", 0)   / total * 100)
    nu = round(counts.get("neutral", 0)        / total * 100)
    ws = round(counts.get("weak_support", 0)   / total * 100)
    ss = round(counts.get("strong_support", 0) / total * 100)
    return (so, wo, nu, ws, ss, total)


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


# ===== Paper's main-argument metric: E[K|m] / m =====
# E[K | m] = Σ_i (1 - C(|G|-n_i, m) / C(|G|, m))
# where n_i = size of cluster i in the source's main-arg cluster partition
# Clustering uses STRICT (equivalent only) per paper.
# Sample size m = min(|source|, TARGET=5) per source (humans, per-LLM-family).
from math import comb

LOOSE_REL = {"equivalent", "strong_overlap"}  # paper default for main-arg
TARGET_M = 5

print("Loading toulmin essay→kind+debate...")
_ESSAY_TO_KIND = {}; _ESSAY_DEBATE = {}
for p in ["data/nyt/toulmin.jsonl.gz", "data/br/toulmin.jsonl.gz"]:
    for line in gzip.open(ROOT / p, "rt"):
        d = json.loads(line)
        _ESSAY_TO_KIND[d["essay_id"]] = d["kind"]
        _ESSAY_DEBATE[d["essay_id"]] = (d["venue"], d["debate_id"])

print("Loading vanilla medoid flags...")
_VANILLA_REPS = set()
for p in ["data/nyt/llm_essays.jsonl.gz", "data/br/llm_essays.jsonl.gz"]:
    for line in gzip.open(ROOT / p, "rt"):
        d = json.loads(line)
        if d["kind"] == "vanilla" and d.get("is_representative"):
            _VANILLA_REPS.add(d["essay_id"])

_GROUP_ESSAYS = {}  # (venue, debate_id) -> {"h":[], "v":[], "d":[], "p":[]}
for eid, (venue, debate_id) in _ESSAY_DEBATE.items():
    key = (venue, debate_id)
    g = _GROUP_ESSAYS.setdefault(key, {"h": [], "v": [], "d": [], "p": []})
    kind = _ESSAY_TO_KIND[eid]
    if kind == "human": g["h"].append(eid)
    elif kind == "vanilla" and eid in _VANILLA_REPS: g["v"].append(eid)
    elif kind == "diversified": g["d"].append(eid)
    elif kind == "position-guided": g["p"].append(eid)

print("Loading main_argument_pairs...")
_MAIN_PAIRS_BY_DEBATE = {}  # (venue, debate_id) -> dict {(essay_i, essay_j): relation}
for p in ["data/nyt/main_argument_pairs.jsonl.gz", "data/br/main_argument_pairs.jsonl.gz"]:
    for line in gzip.open(ROOT / p, "rt"):
        d = json.loads(line)
        key = (d["venue"], d["debate_id"])
        if key not in _MAIN_PAIRS_BY_DEBATE:
            _MAIN_PAIRS_BY_DEBATE[key] = {}
        _MAIN_PAIRS_BY_DEBATE[key][(d["essay_i"], d["essay_j"])] = d["relation"]
        _MAIN_PAIRS_BY_DEBATE[key][(d["essay_j"], d["essay_i"])] = d["relation"]
print(f"  loaded main_arg pairs for {len(_MAIN_PAIRS_BY_DEBATE)} debates")


def _cluster_sizes(essay_ids, pair_rel, relation_set):
    """Union-Find within-group clustering using given relation_set.
    Returns list of cluster sizes (essay counts)."""
    if not essay_ids: return []
    in_group = set(essay_ids)
    parent = {e: e for e in essay_ids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for (a, b), rel in pair_rel.items():
        if rel not in relation_set: continue
        if a in in_group and b in in_group and a != b:
            ra, rb = find(a), find(b)
            if ra != rb: parent[ra] = rb
    from collections import Counter
    return sorted(Counter(find(e) for e in essay_ids).values(), reverse=True)


def _expected_K_at_m(cluster_sizes, m):
    """E[K|m] = Σ_i (1 - C(H-n_i, m) / C(H, m)).
    If H <= m, returns # of non-empty clusters (full sample)."""
    sizes = [n for n in cluster_sizes if n > 0]
    H = sum(sizes)
    if H <= 0 or m <= 0: return 0.0
    if H <= m: return float(len(sizes))
    denom = comb(H, m)
    return sum(1.0 - (comb(H - n, m) / denom) for n in sizes)


def open_card_clusters(venue, debate_id):
    """Paper's % unique = singleton ratio within source group.
    A main argument is 'unique' if no other essay in the same source group has a
    loose-equivalent (equivalent or strong_overlap) main argument."""
    key = (venue, debate_id)
    pair_rel = _MAIN_PAIRS_BY_DEBATE.get(key, {})
    groups = _GROUP_ESSAYS.get(key, {"h": [], "v": [], "d": [], "p": []})

    n_h, n_v, n_d = len(groups["h"]), len(groups["v"]), len(groups["d"])

    def singleton_rate(essay_ids):
        if not essay_ids: return None
        sizes = _cluster_sizes(essay_ids, pair_rel, LOOSE_REL)
        singletons = sum(1 for s in sizes if s == 1)
        total = sum(sizes)
        return singletons / total if total else 0

    U_h = singleton_rate(groups["h"])
    U_v = singleton_rate(groups["v"])
    U_d = singleton_rate(groups["d"])

    def pct(v): return round(v * 100) if v is not None else 0

    return {
        "ratios": {"humans": pct(U_h), "vanilla": pct(U_v), "diversified": pct(U_d)},
        "counts": {
            "humans_essays": n_h, "vanilla_essays": n_v, "diversified_essays": n_d,
        },
    }


TOY_MAP = {
    "are-americans-too-obsessed-with-cleanliness": "debates/cleanliness.html",
    "silicon-valley-goes-to-washington":            "debates/silicon_valley.html",
    "forum_after_911":                              "debates/boston_review_civil_liberties.html",
}

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
}


def debate_title(d):
    q = d.get("question_text") or d.get("lead_essay_text") or ""
    m = re.match(r"^\s*#\s+(.+?)(?:\n|$)", q)
    if m: return m.group(1).strip()
    return d.get("title") or d["debate_id"]


def excerpt(text, n=150):
    if not text: return ""
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"^#+\s*[^\n]*\n+", "", text).strip()
    if len(text) <= n: return text
    cut = text.rfind(" ", 0, n)
    return text[:cut if cut > 0 else n] + "…"


def build_cards():
    debates = load_debates()
    binary, openended = [], []
    for d in debates:
        debate_id = d["debate_id"]
        topic_t = TOPIC_LABEL.get(d.get("topic","")) or (d.get("topic","") or "").replace("_"," ").title()
        venue_label = "NYT" if d["venue"] == "nyt" else "BR"
        topic_chip = f"{venue_label} · {topic_t}" if topic_t else venue_label
        card = {
            "id": debate_id,
            "venue": d["venue"],
            "topic_text": topic_t,
            "topic_chip": topic_chip,
            "title": debate_title(d),
            "n_humans": d["n_humans"],
            "n_diversified": d["n_diversified"],
            "href": TOY_MAP.get(debate_id) or f"debates/debate_{d['venue']}_{debate_id}.html",
            "qtype": d["question_type_norm"],
        }
        if d["question_type"] == "stance":
            s = sides.get(debate_id, {})
            card["support_side"] = s.get("support_side", "Support")
            card["oppose_side"]  = s.get("oppose_side", "Oppose")
            card["humans_bar"]      = humans_bar(debate_id)
            card["vanilla_bar"]     = vanilla_bar(debate_id)
            card["diversified_bar"] = diversified_bar(debate_id)
            binary.append(card)
        else:
            card["excerpt"] = excerpt(d.get("question_text") or d.get("lead_essay_text") or "")
            if d["venue"] == "br" and (d.get("lead_essay_authors") or []):
                card["lead_byline"] = "Lead essay by " + ", ".join(d["lead_essay_authors"])
            card["clusters"] = open_card_clusters(d["venue"], debate_id)
            openended.append(card)
    return binary, openended


HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Argument Collapse · Debates</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --paper: #f6f3ec;
    --paper-soft: #efebe1;
    --ink: #1c1917;
    --ink-soft: #44403c;
    --quiet: #76706a;
    --line: #d8d2c4;
    --line-soft: #e6dfd1;
    --strong-oppose: #3a6479;
    --weak-oppose:   #7e9fac;
    --neutral:       #b0aa9e;
    --weak-support:  #d99070;
    --strong-support:#b85e3a;
    --src-h: #2d8654;
    --src-v: var(--strong-support);
    --src-d: #7c5e9a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: var(--paper); }
  body { color: var(--ink); font-family: 'Inter', -apple-system, sans-serif; font-size: 14px; line-height: 1.6; -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }
  a { color: inherit; text-decoration: none; }

  .masthead { border-bottom: 1px solid var(--line); padding: 22px 40px; display: flex; align-items: center; justify-content: space-between; background: var(--paper); }
  .brand { font-family: 'Newsreader', serif; font-size: 19px; font-weight: 500; letter-spacing: -0.01em; }
  .brand b { font-weight: 600; }
  .nav { display: flex; gap: 32px; }
  .nav a { font-size: 11.5px; font-weight: 500; letter-spacing: 0.16em; text-transform: uppercase; color: var(--quiet); padding: 6px 0; border-bottom: 1.5px solid transparent; transition: color 0.15s, border-color 0.15s; }
  .nav a:hover { color: var(--ink); }
  .nav a.active { color: var(--ink); border-bottom-color: var(--ink); }

  .hero { padding: 80px 40px 24px; max-width: 1280px; margin: 0 auto; }
  .hero .eyebrow { font-size: 11px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--quiet); margin-bottom: 18px; }
  .hero h1 { font-family: 'Newsreader', serif; font-weight: 500; font-size: 56px; line-height: 1.05; letter-spacing: -0.02em; margin-bottom: 18px; }
  .hero h1 em { font-style: italic; color: var(--quiet); font-weight: 400; }
  .hero .deck { font-family: 'Newsreader', serif; font-size: 18px; line-height: 1.55; color: var(--ink-soft); font-style: italic; }

  .explainer { max-width: 1280px; margin: 0 auto; padding: 0 40px 18px; }
  .ex-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 14px 0; }
  .ex-item h4 { font-family: 'Inter', sans-serif; font-size: 11px; letter-spacing: 0.06em; font-weight: 600; text-transform: uppercase; margin-bottom: 8px; }
  .ex-item h4.ex-van { color: var(--strong-support); }
  .ex-item h4.ex-div { color: var(--src-d); }
  .ex-item p { font-family: 'Newsreader', serif; font-size: 14.5px; line-height: 1.5; color: var(--ink-soft); max-width: 540px; }

  .body-grid { max-width: 1280px; margin: 0 auto; padding: 16px 40px 120px; display: grid; grid-template-columns: 220px 1fr; gap: 56px; }
  .sidebar { position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px); overflow-y: auto; }
  .search-box { width: 100%; padding: 8px 10px; font-family: 'Inter', sans-serif; font-size: 12px; border: 1px solid var(--line); border-radius: 3px; background: var(--paper); color: var(--ink); margin-bottom: 14px; }
  .search-box:focus { outline: none; border-color: var(--ink); }
  .filter-head { font-size: 10.5px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink); margin: 6px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--ink); }
  .filter-list { list-style: none; }
  .filter-list li { padding: 5px 0; font-size: 13px; color: var(--ink-soft); cursor: pointer; border-bottom: 1px solid var(--line-soft); display: flex; align-items: center; justify-content: space-between; transition: color 0.15s; }
  .filter-list li:hover { color: var(--ink); }
  .filter-list li.active { color: var(--ink); font-weight: 500; }
  .filter-list li .ct { font-size: 11px; color: var(--quiet); font-variant-numeric: tabular-nums; }
  .filter-list li.active .ct { color: var(--strong-support); }
  .filter-group { margin-bottom: 26px; }

  .toolbar { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: 8px; }
  .toolbar .title { font-family: 'Newsreader', serif; font-size: 22px; font-weight: 500; }
  .toolbar .sort { font-size: 11px; color: var(--quiet); letter-spacing: 0.06em; }
  .sort-btn { cursor: pointer; padding: 2px 0; border-bottom: 1px solid transparent; transition: color 0.15s, border-color 0.15s; }
  .sort-btn:hover { color: var(--ink); }
  .sort-btn.active { color: var(--ink); font-weight: 500; border-bottom-color: var(--ink); }

  .section-head { font-family: 'Newsreader', serif; font-weight: 500; font-size: 20px; letter-spacing: -0.005em; margin-bottom: 18px; padding-bottom: 8px; border-bottom: 1px solid var(--line); }
  .section-head span { color: var(--quiet); font-weight: 400; font-size: 13px; margin-left: 8px; }

  .cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px; align-items: stretch; }
  .card { min-width: 0; }
  .cl-bar { min-width: 0; flex: 1 1 0; }

  .card {
    background: var(--paper); border: 1px solid var(--line);
    padding: 28px 28px 24px;
    transition: border-color 0.18s, transform 0.18s ease;
    cursor: pointer; display: flex; flex-direction: column;
  }
  .card:hover { border-color: var(--ink); transform: translateY(-2px); }
  .card .topic {
    font-size: 10px; font-weight: 600; letter-spacing: 0.18em;
    text-transform: uppercase; color: var(--quiet); margin-bottom: 12px;
  }
  .card h3 {
    font-family: 'Newsreader', serif; font-size: 22px;
    font-weight: 500; line-height: 1.2; letter-spacing: -0.01em;
    color: var(--ink); margin-bottom: 18px;
    min-height: 53px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .axis { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px; }
  .axis-side {
    flex: 1; font-family: 'Newsreader', serif; font-size: 12.5px;
    line-height: 1.3; font-style: italic; padding: 6px 0 7px 10px;
    border-left: 2px solid;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  }
  .axis-side.oppose { color: var(--ink-soft); border-left-color: var(--strong-oppose); }
  .axis-side.support { color: var(--ink-soft); border-left-color: var(--strong-support); }
  .axis-tag { display: block; font-family: 'Inter', sans-serif; font-style: normal; font-size: 9.5px; letter-spacing: 0.16em; font-weight: 600; text-transform: uppercase; margin-bottom: 3px; }
  .axis-side.oppose .axis-tag { color: var(--strong-oppose); }
  .axis-side.support .axis-tag { color: var(--strong-support); }

  .bars { margin-top: 16px; background: var(--paper-soft); padding: 14px 14px 12px; border-radius: 4px; }
  .bars-header { display: grid; grid-template-columns: 64px 1fr 40px; gap: 10px; align-items: baseline; padding-bottom: 6px; margin-bottom: 8px; border-bottom: 1px solid var(--line); }
  .bars-title { grid-column: 2; font-family: 'Inter', sans-serif; font-size: 8.5px; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600; color: var(--quiet); }
  .bars-sub { grid-column: 3; font-family: 'Inter', sans-serif; font-size: 8.5px; letter-spacing: 0.06em; text-transform: uppercase; font-weight: 600; color: var(--quiet); text-align: right; }
  .bar-row { display: grid; grid-template-columns: 64px 1fr 40px; gap: 10px; align-items: center; margin-bottom: 12px; }
  .bar-row:last-child { margin-bottom: 0; }
  .bar-label { font-family: 'Inter', sans-serif; font-size: 9.5px; letter-spacing: 0.12em; font-weight: 500; text-transform: uppercase; color: var(--quiet); }
  .bar { height: 14px; display: flex; border-radius: 2px; overflow: hidden; }
  .seg { height: 100%; }
  .seg.so { background: var(--strong-oppose); }
  .seg.wo { background: var(--weak-oppose); }
  .seg.n  { background: var(--neutral); }
  .seg.ws { background: var(--weak-support); }
  .seg.ss { background: var(--strong-support); }
  .bar-num { font-family: 'Inter', sans-serif; font-size: 10.5px; color: var(--ink-soft); font-variant-numeric: tabular-nums; text-align: right; }

  .card-footer { margin-top: auto; padding-top: 12px; border-top: 1px solid var(--line-soft); display: flex; justify-content: flex-end; }
  .card .bars, .card .clusters { margin-top: 16px; }
  .card-footer .open { font-family: 'Inter', sans-serif; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; color: var(--ink); }

  .card-open .question-quote {
    font-family: 'Newsreader', serif; font-size: 13.5px;
    line-height: 1.5; color: var(--ink-soft); font-style: italic;
    padding: 4px 0 0;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: calc(3 * 1.5 * 13.5px);
    max-height: calc(3 * 1.5 * 13.5px);
  }

  .clusters { margin-top: 16px; background: var(--paper-soft); padding: 14px 14px 12px; border-radius: 4px; }
  .cl-row { display: grid; grid-template-columns: 64px 1fr 60px; gap: 8px; align-items: center; margin-bottom: 12px; }
  .cl-row:last-child { margin-bottom: 0; }
  .cl-label { font-family: 'Inter', sans-serif; font-size: 9.5px; letter-spacing: 0.12em; font-weight: 500; text-transform: uppercase; color: var(--quiet); }
  .ratio-track { background: rgba(0,0,0,0.06); height: 14px; border-radius: 2px; overflow: hidden; min-width: 0; }
  .ratio-fill { height: 100%; border-radius: 2px; transition: opacity 0.15s; }
  .ratio-fill.h { background: var(--src-h); }
  .ratio-fill.v { background: var(--src-v); }
  .ratio-fill.d { background: var(--src-d); }
  .cl-num { font-family: 'Inter', sans-serif; font-size: 12px; color: var(--ink); font-weight: 500; font-variant-numeric: tabular-nums; text-align: right; }
  .cl-num b { font-weight: 700; }
  .cl-num-denom { color: var(--quiet); font-size: 10.5px; font-weight: 500; }
  .cl-header { display: grid; grid-template-columns: 64px 1fr 60px; gap: 8px; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
  .cl-header .ratio-label { grid-column: 2 / span 2; font-family: 'Inter', sans-serif; font-size: 8.5px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600; color: var(--quiet); text-align: right; line-height: 1.2; }

  .empty { padding: 60px 20px; text-align: center; color: var(--quiet); font-size: 14px; font-style: italic; font-family: 'Newsreader', serif; }

  @media (max-width: 900px) {
    .masthead { padding: 16px 20px; flex-wrap: wrap; gap: 12px; }
    .nav { gap: 18px; }
    .nav a { font-size: 10.5px; letter-spacing: 0.1em; }
    .hero { padding: 40px 20px 18px; }
    .hero h1 { font-size: 32px; }
    .hero .deck { font-size: 15px; }
    .explainer { padding: 0 20px 18px; }
    .ex-grid { grid-template-columns: 1fr; }
    .body-grid { padding: 16px 20px 80px; grid-template-columns: 1fr; gap: 28px; }
    .sidebar { position: static; max-height: none; }
    .cards { grid-template-columns: 1fr; }
    .toolbar { flex-direction: column; align-items: flex-start; gap: 8px; }
  }
</style>
</head>
<body>

<header class="masthead">
  <div class="brand"><b>Argument Collapse</b></div>
  <nav class="nav">
    <a href="index.html" class="active">DEBATES</a>
    <a href="main_argument.html">MAIN_ARGUMENT</a>
    <a href="sub_argument.html">SUB_ARGUMENT</a>
  </nav>
</header>

<section class="hero">
  <div class="eyebrow"><a href="#" style="color: var(--ink); text-decoration: underline; text-underline-offset: 3px;">Argument Collapse: LLMs Flatten Long-Form Public Debate</a> &nbsp;·&nbsp; Yekyung Kim*, Yapei Chang*, Chau Minh Pham, Mohit Iyyer (2026)</div>
  <h1>Where five LLMs land on a <em>public debate</em></h1>
  <p class="deck">Across 195 NYT Room for Debate debates and 61 Boston Review forums, we compare what five LLM families produce with what the writers originally published in these venues. Each model writes under two prompting conditions: vanilla (basic) and diversified (explicitly asked for varied responses).</p>
  <p style="font-size: 11.5px; color: var(--quiet); letter-spacing: 0.04em; margin-top: 14px;">Models: GPT-5.5 · Claude Opus 4.7 · DeepSeek V4 Pro · Gemini 3.1 Pro · MiniMax M2.7</p>
</section>

<div class="explainer">
  <div class="ex-grid">
    <div class="ex-item">
      <h4 class="ex-van">Vanilla</h4>
      <p>The basic prompting condition. Each model is given the debate question with no further instruction and writes one essay. We report the most representative essay per LLM family, so vanilla totals five essays per debate.</p>
    </div>
    <div class="ex-item">
      <h4 class="ex-div">Diversified</h4>
      <p>The same five models are asked the same question, but explicitly instructed to produce varied responses. Many essays per family are sampled, roughly twenty per family per debate.</p>
    </div>
  </div>
</div>

<div class="body-grid">

  <aside class="sidebar">
    <input type="search" id="search-box" class="search-box" placeholder="Search debate titles…">
    <div class="filter-group">
      <div class="filter-head">Venue</div>
      <ul class="filter-list" data-filter="venue">
        <li class="active" data-val="all">All<span class="ct" id="ct-venue-all"></span></li>
        <li data-val="nyt">NYT Room for Debate<span class="ct" id="ct-venue-nyt"></span></li>
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
      <div class="filter-head">Topic</div>
      <ul class="filter-list" data-filter="topic">
        <li class="active" data-val="all">All<span class="ct" id="ct-topic-all"></span></li>
__TOPIC_LIS__
      </ul>
    </div>
  </aside>

  <main>
    <div class="toolbar">
      <div class="title" id="title-counter">Debates</div>
      <div class="sort">Sort: <span class="sort-btn active" data-sort="alphabet">alphabet</span> · <span class="sort-btn" data-sort="humans"># humans</span> · <span class="sort-btn" data-sort="diversified"># diversified</span></div>
    </div>

    <section id="binary-section">
      <h2 class="section-head">Binary debates <span id="binary-count">0</span></h2>
      <div class="cards" id="binary-cards"></div>
    </section>

    <section id="open-section" style="margin-top: 64px;">
      <h2 class="section-head">Open-ended debates <span id="open-count">0</span></h2>
      <div class="cards" id="open-cards"></div>
    </section>

  </main>
</div>

<script id="card-data" type="application/json">__DATA_JSON__</script>
<script>
const data = JSON.parse(document.getElementById('card-data').textContent);
const state = { venue: "all", qtype: "all", topic: "all", search: "", sort: "alphabet" };
const TOPICS = __TOPICS_JS__;

function binaryCardHtml(c) {
  const [hSo,hWo,hN,hWs,hSs,hN_] = c.humans_bar;
  const [vSo,vWo,vN,vWs,vSs,vN_] = c.vanilla_bar;
  const [dSo,dWo,dN,dWs,dSs,dN_] = c.diversified_bar;
  return `<div class="card" data-href="${c.href}">
    <div class="topic">${c.topic_chip}</div>
    <h3>${c.title}</h3>
    <div class="axis">
      <div class="axis-side oppose"><span class="axis-tag">Oppose</span>${c.oppose_side}</div>
      <div class="axis-side support"><span class="axis-tag">Support</span>${c.support_side}</div>
    </div>
    <div class="bars">
      <div class="bars-header">
        <span class="bars-title">Stance distribution per source</span>
        <span class="bars-sub"># essays</span>
      </div>
      <div class="bar-row">
        <span class="bar-label">Humans</span>
        <div class="bar">
          <div class="seg so" style="width: ${hSo}%;"></div>
          <div class="seg wo" style="width: ${hWo}%;"></div>
          <div class="seg n"  style="width: ${hN}%;"></div>
          <div class="seg ws" style="width: ${hWs}%;"></div>
          <div class="seg ss" style="width: ${hSs}%;"></div>
        </div>
        <span class="bar-num">${hN_}</span>
      </div>
      <div class="bar-row">
        <span class="bar-label">Vanilla</span>
        <div class="bar">
          <div class="seg so" style="width: ${vSo}%;"></div>
          <div class="seg wo" style="width: ${vWo}%;"></div>
          <div class="seg n"  style="width: ${vN}%;"></div>
          <div class="seg ws" style="width: ${vWs}%;"></div>
          <div class="seg ss" style="width: ${vSs}%;"></div>
        </div>
        <span class="bar-num">${vN_}</span>
      </div>
      <div class="bar-row">
        <span class="bar-label">Diversified</span>
        <div class="bar div-bar">
          <div class="seg so" style="width: ${dSo}%;"></div>
          <div class="seg wo" style="width: ${dWo}%;"></div>
          <div class="seg n"  style="width: ${dN}%;"></div>
          <div class="seg ws" style="width: ${dWs}%;"></div>
          <div class="seg ss" style="width: ${dSs}%;"></div>
        </div>
        <span class="bar-num">${dN_}</span>
      </div>
    </div>
    <div class="card-footer"><a href="${c.href}" class="open">Open →</a></div>
  </div>`;
}

function openCardHtml(c) {
  const exc = c.excerpt || '';
  const byline = c.lead_byline ? `<p class="question-quote">${c.lead_byline}: ${exc}</p>` : `<p class="question-quote">${exc}</p>`;
  const cd = c.clusters || {ratios:{humans:0, vanilla:0, diversified:0}, counts:{}};
  const ratioBar = (kind, pct) => `
    <div class="cl-row">
      <span class="cl-label">${ {h:"Humans", v:"Vanilla", d:"Diversified"}[kind] }</span>
      <div class="ratio-track">
        <div class="ratio-fill ${kind}" style="width: ${pct}%;"></div>
      </div>
      <span class="cl-num">${pct}<span class="cl-num-denom">%</span></span>
    </div>`;
  return `<div class="card card-open" data-href="${c.href}">
    <div class="topic">${c.topic_chip}</div>
    <h3>${c.title}</h3>
    ${byline}
    <div class="clusters">
      <div class="cl-header"><span class="ratio-label">Share unique main args<br>within debate</span></div>
      ${ratioBar('h', cd.ratios.humans)}
      ${ratioBar('v', cd.ratios.vanilla)}
      ${ratioBar('d', cd.ratios.diversified)}
    </div>
    <div class="card-footer"><a href="${c.href}" class="open">Open →</a></div>
  </div>`;
}

function passes(c) {
  if (state.venue !== "all" && c.venue !== state.venue) return false;
  if (state.qtype !== "all" && c.qtype !== state.qtype) return false;
  if (state.topic !== "all") {
    if (c.topic_text !== TOPICS[state.topic]) return false;
  }
  if (state.search && !c.title.toLowerCase().includes(state.search.toLowerCase())) return false;
  return true;
}

function sortRows(rows) {
  if (state.sort === "alphabet")     rows.sort((a,b) => a.title.localeCompare(b.title));
  else if (state.sort === "humans")  rows.sort((a,b) => b.n_humans - a.n_humans);
  else if (state.sort === "diversified") rows.sort((a,b) => b.n_diversified - a.n_diversified);
  return rows;
}

function render() {
  const all = [...data.binary, ...data.open];
  const filtered = sortRows(all.filter(passes));
  const bins = filtered.filter(c => c.qtype === 'stance');
  const ops  = filtered.filter(c => c.qtype !== 'stance');

  const binSec = document.getElementById('binary-section');
  const opSec  = document.getElementById('open-section');
  const binC   = document.getElementById('binary-cards');
  const opC    = document.getElementById('open-cards');

  document.getElementById('binary-count').textContent = bins.length;
  document.getElementById('open-count').textContent   = ops.length;
  document.getElementById('title-counter').textContent = `${filtered.length} debate${filtered.length===1?'':'s'}`;

  binSec.style.display = bins.length > 0 ? '' : 'none';
  opSec.style.display  = ops.length > 0  ? '' : 'none';
  binC.innerHTML = bins.length > 0 ? bins.map(binaryCardHtml).join('') : '';
  opC.innerHTML  = ops.length  > 0 ? ops.map(openCardHtml).join('')   : '';

  if (filtered.length === 0) {
    binSec.style.display = '';
    binC.innerHTML = '<div class="empty">No debates match these filters.</div>';
  }

  document.querySelectorAll('.card[data-href]').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('a') || e.target.closest('button')) return;
      if (card.dataset.href && card.dataset.href !== '#') window.location.href = card.dataset.href;
    });
  });

  updateCounts(all);
}

function updateCounts(all) {
  const base = all.filter(c => !state.search || c.title.toLowerCase().includes(state.search.toLowerCase()));
  document.getElementById('ct-venue-all').textContent = base.length;
  document.getElementById('ct-venue-nyt').textContent = base.filter(c => c.venue==='nyt').length;
  document.getElementById('ct-venue-br').textContent  = base.filter(c => c.venue==='br').length;
  const v = state.venue === 'all' ? base : base.filter(c => c.venue === state.venue);
  document.getElementById('ct-qtype-all').textContent  = v.length;
  document.getElementById('ct-qtype-stance').textContent = v.filter(c => c.qtype==='stance').length;
  document.getElementById('ct-qtype-open').textContent   = v.filter(c => c.qtype==='open_ended').length;
  document.getElementById('ct-qtype-lead').textContent   = v.filter(c => c.qtype==='lead_essay').length;
  const q = state.qtype === 'all' ? v : v.filter(c => c.qtype === state.qtype);
  document.getElementById('ct-topic-all').textContent = q.length;
  document.querySelectorAll('[id^="ct-topic-"]').forEach(el => {
    const t = el.id.replace('ct-topic-','');
    if (t === 'all') return;
    el.textContent = q.filter(c => c.topic_text === TOPICS[t]).length;
  });
}

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
const sb = document.getElementById('search-box');
if (sb) sb.addEventListener('input', e => { state.search = e.target.value; render(); });
document.querySelectorAll('.sort-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.sort = btn.dataset.sort;
    render();
  });
});

render();
</script>

</body>
</html>
'''


def topic_lis():
    return "".join(
        f'        <li data-val="{k}">{v}<span class="ct" id="ct-topic-{k}"></span></li>\n'
        for k, v in TOPIC_LABEL.items()
    )


def main():
    binary, openended = build_cards()
    print(f"binary: {len(binary)}, open-ended: {len(openended)}, total: {len(binary)+len(openended)}")

    payload = {"binary": binary, "open": openended}
    data_json = json.dumps(payload, ensure_ascii=False)
    topics_js = json.dumps(TOPIC_LABEL, ensure_ascii=False)

    html = HTML.replace("__TOPIC_LIS__", topic_lis())
    html = html.replace("__DATA_JSON__", data_json)
    html = html.replace("__TOPICS_JS__", topics_js)
    (DOCS / "index.html").write_text(html)
    print(f"index.html written: {(DOCS / 'index.html').stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
