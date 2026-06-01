#!/usr/bin/env python3
"""Reproduce headline main-argument results from the released data.

The script reads only the public gzipped JSONL tables under ``data/``. It
computes descriptive main-argument metrics used in the paper:

* vanilla uniqueness: humans vs one representative vanilla answer per LLM;
* vanilla human overlap: whether a vanilla LLM representative substantially
  overlaps any human main argument in the same debate;
* diversified uniqueness: within each model's diversified outputs;
* diversified recovery: human clusters touched by diversified outputs; and
* diversified grounding: generated clusters that overlap a human argument.

All overlap-based metrics use the paper's substantial-overlap boundary:
``equivalent`` or ``strong_overlap``.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Iterable

LOOSE = {"equivalent", "strong_overlap"}
MODELS = ["gpt", "gemini", "claude", "minimax", "deepseek"]


def read_jsonl_gz(path: Path) -> list[dict]:
    rows: list[dict] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def by_debate(rows: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[row["debate_id"]].append(row)
    return dict(out)


def comb(n: int, k: int) -> int:
    if k < 0 or n < 0 or k > n:
        return 0
    return math.comb(n, k)


def pair_key(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


def relation_map(rows: Iterable[dict]) -> dict[frozenset[str], str]:
    rel: dict[frozenset[str], str] = {}
    for row in rows:
        a, b = row.get("essay_i"), row.get("essay_j")
        if a and b and a != b:
            rel[pair_key(a, b)] = row.get("relation")
    return rel


def has_loose_edge(a: str, b: str, rel: dict[frozenset[str], str]) -> bool:
    return rel.get(pair_key(a, b)) in LOOSE


class UnionFind:
    def __init__(self, nodes: Iterable[str]):
        self.parent = {n: n for n in nodes}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self) -> list[list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for node in self.parent:
            grouped[self.find(node)].append(node)
        return list(grouped.values())


def clusters(nodes: list[str], rel: dict[frozenset[str], str]) -> list[list[str]]:
    uf = UnionFind(nodes)
    node_set = set(nodes)
    for key, relation in rel.items():
        if relation not in LOOSE:
            continue
        vals = list(key)
        if len(vals) != 2:
            continue
        a, b = vals
        if a in node_set and b in node_set:
            uf.union(a, b)
    return uf.groups()


def within_unique(nodes: list[str], rel: dict[frozenset[str], str], m: int | None = None) -> float | None:
    """Closed-form same-sized-sample unique rate for main arguments.

    A node is unique in a sample if it has no substantial-overlap edge to any
    other node in that sample. When ``m`` is smaller than the group size, this
    returns the expected unique share over all same-sized samples of size ``m``.
    """
    n = len(nodes)
    if n == 0:
        return None
    if n == 1:
        return 1.0
    if m is None:
        m = n
    m = max(1, min(m, n))
    if m == 1:
        return 1.0

    node_set = set(nodes)
    degree = {node: 0 for node in nodes}
    for key, relation in rel.items():
        if relation not in LOOSE:
            continue
        vals = list(key)
        if len(vals) != 2:
            continue
        a, b = vals
        if a in node_set and b in node_set:
            degree[a] += 1
            degree[b] += 1

    denom = comb(n - 1, m - 1)
    vals = [comb(n - 1 - degree[node], m - 1) / denom for node in nodes]
    return sum(vals) / len(vals)


def pct(x: float | None) -> str:
    if x is None:
        return "NA"
    return f"{100 * x:.1f}%"


def avg(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def model_label(row: dict) -> str | None:
    return row.get("model_short") or row.get("model")


def compute_venue(root: Path, venue: str) -> dict:
    toulmin = by_debate(read_jsonl_gz(root / venue / "toulmin.jsonl.gz"))
    llms = by_debate(read_jsonl_gz(root / venue / "llm_essays.jsonl.gz"))
    pairs = by_debate(read_jsonl_gz(root / venue / "main_argument_pairs.jsonl.gz"))

    vanilla_h_u: list[float] = []
    vanilla_v_u: list[float] = []
    vanilla_overlap_hits = 0
    vanilla_overlap_total = 0
    vanilla_debates = 0

    div_unique_by_model: dict[str, list[float]] = defaultdict(list)
    div_recall_by_model: dict[str, list[float]] = defaultdict(list)
    div_grounding_by_model: dict[str, list[float]] = defaultdict(list)
    div_pool_recall: list[float] = []
    div_pool_grounding: list[float] = []
    div_total_human_clusters = 0
    div_total_pooled_hits = 0

    for debate_id, trows in toulmin.items():
        rel = relation_map(pairs.get(debate_id, []))
        humans = [r["essay_id"] for r in trows if r.get("kind") == "human"]
        if not humans:
            continue

        lrows = llms.get(debate_id, [])
        reps = [
            r["essay_id"]
            for r in lrows
            if r.get("kind") == "vanilla" and r.get("is_representative") is True
        ]
        if humans and reps:
            m = min(len(humans), len(reps))
            vanilla_h_u.append(within_unique(humans, rel, m))
            vanilla_v_u.append(within_unique(reps, rel, m))
            vanilla_debates += 1
            for rep in reps:
                vanilla_overlap_total += 1
                if any(has_loose_edge(rep, h, rel) for h in humans):
                    vanilla_overlap_hits += 1

        human_clusters = clusters(humans, rel)
        if not human_clusters:
            continue
        div_total_human_clusters += len(human_clusters)

        div_rows = [r for r in lrows if r.get("kind") == "diversified" and r.get("effort") == "medium"]
        div_by_model: dict[str, list[str]] = defaultdict(list)
        for row in div_rows:
            model = model_label(row)
            if model in MODELS:
                div_by_model[model].append(row["essay_id"])

        pooled_cluster_hits: set[int] = set()
        pooled_generated_clusters: list[list[str]] = []
        for model, nodes in div_by_model.items():
            if not nodes:
                continue
            m = min(len(humans), len(nodes))
            div_unique_by_model[model].append(within_unique(nodes, rel, m))

            hit_clusters = set()
            for idx, cluster in enumerate(human_clusters):
                if any(has_loose_edge(d, h, rel) for d in nodes for h in cluster):
                    hit_clusters.add(idx)
                    pooled_cluster_hits.add(idx)
            div_recall_by_model[model].append(len(hit_clusters) / len(human_clusters))

            generated_clusters = clusters(nodes, rel)
            grounded = 0
            for cluster in generated_clusters:
                if any(has_loose_edge(d, h, rel) for d in cluster for h in humans):
                    grounded += 1
            div_grounding_by_model[model].append(grounded / len(generated_clusters) if generated_clusters else None)
            pooled_generated_clusters.extend(generated_clusters)

        if div_by_model:
            div_pool_recall.append(len(pooled_cluster_hits) / len(human_clusters))
            div_total_pooled_hits += len(pooled_cluster_hits)
            pooled_grounded = 0
            for cluster in clusters([d for nodes in div_by_model.values() for d in nodes], rel):
                if any(has_loose_edge(d, h, rel) for d in cluster for h in humans):
                    pooled_grounded += 1
            all_div_clusters = clusters([d for nodes in div_by_model.values() for d in nodes], rel)
            div_pool_grounding.append(pooled_grounded / len(all_div_clusters) if all_div_clusters else None)

    return {
        "venue": venue,
        "vanilla": {
            "n_debates": vanilla_debates,
            "human_unique_rate": avg(vanilla_h_u),
            "llm_unique_rate": avg(vanilla_v_u),
            "llm_arguments_overlapping_humans": (
                vanilla_overlap_hits / vanilla_overlap_total if vanilla_overlap_total else None
            ),
            "n_llm_representatives": vanilla_overlap_total,
        },
        "diversified": {
            "within_model_unique_rate": {m: avg(div_unique_by_model[m]) for m in MODELS},
            "human_cluster_recall_by_model": {m: avg(div_recall_by_model[m]) for m in MODELS},
            "generated_cluster_grounding_by_model": {m: avg(div_grounding_by_model[m]) for m in MODELS},
            "pooled_human_cluster_recall_all_clusters": (
                div_total_pooled_hits / div_total_human_clusters if div_total_human_clusters else None
            ),
            "pooled_human_cluster_recall_macro_debate": avg(div_pool_recall),
            "pooled_generated_cluster_grounding_macro_debate": avg(div_pool_grounding),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=Path("data"), help="Path to released data directory")
    ap.add_argument("--output", type=Path, default=Path("results/main_arg_results.json"), help="JSON output path")
    args = ap.parse_args()

    results = {venue: compute_venue(args.data_root, venue) for venue in ("nyt", "br")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")

    print("Main-argument reproduction summary")
    print("Overlap boundary: equivalent + strong_overlap")
    print()
    for venue in ("nyt", "br"):
        res = results[venue]
        v = res["vanilla"]
        print(f"[{venue.upper()}] Vanilla main-argument uniqueness")
        print(f"  debates: {v['n_debates']}")
        print(f"  humans:       {pct(v['human_unique_rate'])}")
        print(f"  vanilla LLMs: {pct(v['llm_unique_rate'])}")
        print(f"  vanilla LLM reps overlapping any human argument: {pct(v['llm_arguments_overlapping_humans'])}")
        print()

        d = res["diversified"]
        print(f"[{venue.upper()}] Diversified main-argument checks")
        print("  within-model unique rate:")
        for model in MODELS:
            print(f"    {model:<8} {pct(d['within_model_unique_rate'][model])}")
        print("  human-cluster recall by model:")
        for model in MODELS:
            print(f"    {model:<8} {pct(d['human_cluster_recall_by_model'][model])}")
        print(f"  pooled human-cluster recall, all clusters: {pct(d['pooled_human_cluster_recall_all_clusters'])}")
        print(f"  pooled human-cluster recall, macro by debate: {pct(d['pooled_human_cluster_recall_macro_debate'])}")
        print("  generated-cluster grounding by model:")
        for model in MODELS:
            print(f"    {model:<8} {pct(d['generated_cluster_grounding_by_model'][model])}")
        print(f"  pooled generated-cluster grounding, macro by debate: {pct(d['pooled_generated_cluster_grounding_macro_debate'])}")
        print()

    print(f"Detailed JSON written to {args.output}")


if __name__ == "__main__":
    main()
