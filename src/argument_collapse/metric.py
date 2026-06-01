#!/usr/bin/env python3
"""Within-group unique rate U_m and related diversity metrics.

This module exposes the pair-level and group-level uniqueness measures used
throughout the paper:

* :func:`within_unique` — closed-form U_m on a within-group adjacency.
* :func:`essay_unique`  — per-essay analogue of within_unique.
* :func:`pair_recovery` — asymmetric A->B coverage (used for cross-group
  "how much of A is reachable from B" questions).
* :func:`pair_unique`   — symmetric pair-level unique rate
  ``u(A, B) = 1 - 0.5 (r(A->B) + r(B->A))``.

It also provides the data-loading and run-driver glue that turns the raw
``toulmin.jsonl`` + ``sub_argument_pairs.jsonl`` files emitted by
:mod:`argument_collapse.annotate.pair_comparison_sub_arg` into per-cohort U_m rows.

Run the CLI with ``uv run ac-metric um --spec <yaml>``.
The spec is a YAML file listing each cohort and which essay stems belong
to each group (H/V/D/P_s1/P_s2); see ``configs/`` for the subset specs
used in the paper analyses. The same module is importable so downstream
code (notebooks, papers) can call :func:`run_um` directly on an in-memory
spec.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from math import comb
from pathlib import Path
from typing import Any

from argument_collapse.data import (
    LAYOUT_AGGREGATE,
    detect_layout,
    get_data_root,
    iter_cohort_jsonl,
    normalize_venue,
    set_data_root,
)

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy is a hard install dep
    np = None  # type: ignore[assignment]

# 4-label thresholds used everywhere in the paper:
# - strict drops strong_overlap to require near-paraphrase clustering;
# - loose keeps strong_overlap, matching the headline U_m numbers.
THRESHOLDS = {
    "strict": frozenset({"equivalent"}),
    "loose": frozenset({"equivalent", "strong_overlap"}),
}


# ---------- core maths ----------

def build_adj(sub_to_essay: dict[str, str],
              pair_rel: dict[tuple[str, str], str],
              relation_set: frozenset[str] | set[str]) -> dict[str, set[str]]:
    """Within-group adjacency over sub-arguments.

    Edges connect sub-arguments from *different* essays whose pairwise
    judge relation is in ``relation_set`` (typically the strict/loose
    threshold). Same-essay sub-arguments are never connected, since this
    is about how distinct an essay's claims are from *other* essays in
    the group.
    """
    adj: dict[str, set[str]] = {s: set() for s in sub_to_essay}
    for (a, b), rel in pair_rel.items():
        if rel not in relation_set:
            continue
        if a not in sub_to_essay or b not in sub_to_essay:
            continue
        if sub_to_essay[a] == sub_to_essay[b]:
            continue
        adj[a].add(b)
        adj[b].add(a)
    return adj


def within_unique(sub_to_essay: dict[str, str],
                  pair_rel: dict[tuple[str, str], str],
                  m: int,
                  relation_set: frozenset[str] | set[str]) -> float:
    """Closed-form within-group unique rate U_m for group G.

    Under uniform sampling without replacement of size ``m`` from G,

        U_m(G) = (1 / |G|) * sum_i C(|G| - 1 - d_i, m - 1) / C(|G| - 1, m - 1)

    where ``d_i`` is the degree of sub-argument ``i`` in the within-group
    adjacency. Returns ``NaN`` when the group is empty.
    """
    adj = build_adj(sub_to_essay, pair_rel, relation_set)
    sub_ids = list(sub_to_essay.keys())
    G = len(sub_ids)
    if G == 0 or m == 0:
        return float("nan")
    m = min(m, G)
    if m == 1:
        return 1.0
    denom = comb(G - 1, m - 1)
    total = 0
    for s in sub_ids:
        avail = G - 1 - len(adj[s])
        if avail >= m - 1:
            total += comb(avail, m - 1)
    return total / (G * denom)


def essay_unique(essay_sub_ids: list[str],
                 other_sub_ids: list[str],
                 pair_rel: dict[tuple[str, str], str],
                 relation_set: frozenset[str] | set[str]) -> float:
    """Per-essay unique rate.

    Fraction of one essay's sub-arguments that have *no* match in
    ``other_sub_ids`` (typically the pool of sub-arguments belonging to
    the other essays in the same writer group, excluding self).
    """
    if not essay_sub_ids:
        return float("nan")
    other_set = set(other_sub_ids)
    unique = 0
    for i in essay_sub_ids:
        matched = False
        for j in other_set:
            if (i, j) in pair_rel and pair_rel[(i, j)] in relation_set:
                matched = True
                break
        if not matched:
            unique += 1
    return unique / len(essay_sub_ids)


def pair_recovery(src_subs: list[str],
                  tgt_subs: list[str],
                  pair_rel: dict[tuple[str, str], str],
                  relation_set: frozenset[str] | set[str]) -> float:
    """Asymmetric coverage ``r(src -> tgt)`` = fraction of source units
    matched by some unit in target. ``NaN`` when either side is empty."""
    if not src_subs or not tgt_subs:
        return float("nan")
    tgt_set = set(tgt_subs)
    matched = 0
    for s in src_subs:
        for t in tgt_set:
            if (s, t) in pair_rel and pair_rel[(s, t)] in relation_set:
                matched += 1
                break
    return matched / len(src_subs)


def pair_unique(a_subs: list[str], b_subs: list[str],
                pair_rel: dict[tuple[str, str], str],
                relation_set: frozenset[str] | set[str]) -> float:
    """Symmetric pair-level unique rate
    ``u(A, B) = 1 - 0.5 (r(A->B) + r(B->A))``."""
    r_ab = pair_recovery(a_subs, b_subs, pair_rel, relation_set)
    r_ba = pair_recovery(b_subs, a_subs, pair_rel, relation_set)
    if np is not None and (np.isnan(r_ab) or np.isnan(r_ba)):
        return float("nan")
    return 1.0 - 0.5 * (r_ab + r_ba)


def missing_within_pair_rows(sub_to_essay: dict[str, str],
                             pair_rel: dict[tuple[str, str], str]) -> int:
    """Count unjudged cross-essay sub-argument pairs inside a group."""
    by_essay: dict[str, list[str]] = {}
    for sub_id, essay_id in sub_to_essay.items():
        by_essay.setdefault(essay_id, []).append(sub_id)
    missing = 0
    for essay_i, essay_j in itertools.combinations(sorted(by_essay), 2):
        for sub_i in by_essay[essay_i]:
            for sub_j in by_essay[essay_j]:
                if (sub_i, sub_j) not in pair_rel and (sub_j, sub_i) not in pair_rel:
                    missing += 1
    return missing


def require_within_pair_coverage(cohort: str,
                                 label: str,
                                 sub_to_essay: dict[str, str],
                                 pair_rel: dict[tuple[str, str], str]) -> None:
    """Fail fast when a configured group lacks needed sub-argument labels.

    Missing labels must not be silently treated as non-overlap, because that
    would inflate the unique-rate metric.
    """
    missing = missing_within_pair_rows(sub_to_essay, pair_rel)
    if missing:
        raise ValueError(
            f"{cohort}: missing {missing} sub-argument pair rows for {label}. "
            "The selected group is not fully annotated for U_m."
        )


# ---------- cohort loading ----------

def load_cohort(cohort_dir: Path) -> tuple[dict[str, list[str]],
                                            dict[tuple[str, str], str]]:
    """Load the per-cohort artefacts produced by the annotation pipeline.

    Returns ``(essay_subs, pair_rel)``:

      * ``essay_subs[stem]`` — list of sub-argument IDs ``"{stem}::sub{NN}"``
        for that essay, sourced from ``toulmin.jsonl``.
      * ``pair_rel[(sub_i, sub_j)]`` — the 4-label judge relation for that
        pair, sourced from ``sub_argument_pairs.jsonl``. The dict is
        populated both directions so lookups in either order succeed.
    """
    toulmin_path = cohort_dir / "analysis" / "toulmin.jsonl"
    pairs_path = cohort_dir / "analysis" / "sub_argument_pairs.jsonl"

    essay_subs: dict[str, list[str]] = {}
    if toulmin_path.exists():
        for line in toulmin_path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            essay_subs[r["stem"]] = [
                f"{r['stem']}::sub{i:02d}"
                for i in range(len(r.get("sub_arguments", [])))
            ]

    pair_rel: dict[tuple[str, str], str] = {}
    if pairs_path.exists():
        for line in pairs_path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            pair_rel[(r["sub_i"], r["sub_j"])] = r["relation"]
            pair_rel[(r["sub_j"], r["sub_i"])] = r["relation"]
    return essay_subs, pair_rel


def release_stem(stem: str) -> str:
    """Map legacy source-side condition names inside generated essay stems
    to the public release names. Human stems are returned unchanged."""
    if "__" not in stem:
        return stem
    parts = stem.split("__")
    if len(parts) >= 4:
        parts[3] = {
            "v1a": "vanilla",
            "v15a": "diversified",
            "v4a": "position-guided",
        }.get(parts[3], parts[3])
    return "__".join(parts)


def pool_from_stems(essay_subs: dict[str, list[str]],
                    stems: list[str]) -> dict[str, str]:
    """Flatten ``[stem, ...]`` into a ``sub_id -> stem`` map used by
    :func:`within_unique` and friends. Specs written with old working-repo
    stems (``v1a``/``v15a``/``v4a``) also work against the public release
    names (``vanilla``/``diversified``/``position-guided``)."""
    out: dict[str, str] = {}
    for stem in stems:
        for candidate in (stem, release_stem(stem)):
            if candidate in essay_subs:
                for sub in essay_subs[candidate]:
                    out[sub] = candidate
                break
    return out


def load_cohort_from_rows(toulmin_rows: list[dict],
                          pair_rows: list[dict]) -> tuple[dict[str, list[str]],
                                                           dict[tuple[str, str], str]]:
    """Build ``(essay_subs, pair_rel)`` from aggregate release rows."""
    essay_subs: dict[str, list[str]] = {}
    for r in toulmin_rows:
        stem = r.get("essay_id") or r.get("stem")
        if not stem:
            continue
        essay_subs[stem] = [
            f"{stem}::sub{i:02d}"
            for i in range(len(r.get("sub_arguments", []) or []))
        ]

    pair_rel: dict[tuple[str, str], str] = {}
    for r in pair_rows:
        a, b, rel = r.get("sub_i"), r.get("sub_j"), r.get("relation")
        if not a or not b or not rel:
            continue
        pair_rel[(a, b)] = rel
        pair_rel[(b, a)] = rel
    return essay_subs, pair_rel


# ---------- spec-driven U_m driver ----------

def _macro_average(values: list[float]) -> float:
    """Average a list of floats, treating ``NaN`` as missing.

    Falls back to a pure-Python implementation when numpy is unavailable.
    """
    if np is not None:
        clean = [v for v in values if not (isinstance(v, float) and np.isnan(v))]
        return float(np.mean(clean)) if clean else float("nan")
    clean = [v for v in values if not (isinstance(v, float) and v != v)]
    return sum(clean) / len(clean) if clean else float("nan")


def _diversified_combos(essay_subs: dict[str, list[str]],
                         d_combos_spec: dict[str, list[str]],
                         max_combos: int = 200,
                         seed: int = 42,
                         ) -> tuple[int, list[dict[str, str]]]:
    """Enumerate 1-per-family diversified combos and return their sub-arg pools.

    ``d_combos_spec`` maps ``family -> [candidate_stem, ...]``. The
    combinatorial product picks one stem per family; when the product
    exceeds ``max_combos`` it is reproducibly sampled with ``seed``. The
    integer return value is ``d_min`` — the smallest possible combo's
    pool size, used to seed the cohort's common-m candidate when no
    combo would otherwise contribute.
    """
    by_fam: dict[str, list[str]] = {}
    for fam, stems in d_combos_spec.items():
        mapped = [
            candidate
            for stem in stems
            for candidate in (stem, release_stem(stem))
            if candidate in essay_subs
        ]
        if mapped:
            by_fam[fam] = mapped
    if len(by_fam) < len(d_combos_spec):
        # Treat missing families as the empty set, which makes the
        # product empty.
        return 0, []
    d_min = sum(min(len(essay_subs.get(stem, [])) for stem in stems)
                 for stems in by_fam.values()) if by_fam else 0
    if not by_fam:
        return 0, []
    fam_keys = list(by_fam.keys())
    combos = list(itertools.product(*(by_fam[k] for k in fam_keys)))
    rng = random.Random(seed)
    if len(combos) > max_combos:
        combos = rng.sample(combos, max_combos)
    pools: list[dict[str, str]] = []
    for combo in combos:
        pool: dict[str, str] = {}
        for stem in combo:
            for sub in essay_subs.get(stem, []):
                pool[sub] = stem
        if pool:
            pools.append(pool)
    return d_min, pools


def cohort_um_row(cohort: str,
                  groups: dict[str, Any],
                  essay_subs: dict[str, list[str]],
                  pair_rel: dict[tuple[str, str], str],
                  thresholds: dict[str, frozenset[str] | set[str]] = THRESHOLDS,
                  diversified_combos_max: int = 200,
                  diversified_combos_seed: int = 42,
                  ) -> dict[str, Any] | None:
    """Compute one cohort row.

    ``groups`` is the spec entry's groups dict. Returns ``None`` when
    every group is empty (so the common-m would be undefined). For each
    threshold name the row carries the corresponding U_m for H/V/D, the
    macro-averaged S1 and S2 U_m, and the per-label S2 U_m breakdown.

    When ``groups`` carries a ``D_combos: {family: [stem, ...]}`` block,
    the diversified U_m is computed as the average U_m over 1-per-family
    combos (sampled up to ``diversified_combos_max``). When only ``D`` is
    set, it's the U_m of the pooled diversified essays. ``D_combos`` takes
    precedence.
    """
    h_pool = pool_from_stems(essay_subs, groups.get("H", []) or [])
    v_pool = pool_from_stems(essay_subs, groups.get("V", []) or [])
    d_pool = pool_from_stems(essay_subs, groups.get("D", []) or [])
    d_combos_spec = groups.get("D_combos") or {}
    if d_combos_spec:
        d_min, d_combo_pools = _diversified_combos(
            essay_subs, d_combos_spec,
            max_combos=diversified_combos_max,
            seed=diversified_combos_seed,
        )
    else:
        d_min = 0
        d_combo_pools = []

    s1_block = groups.get("P_s1") or {}
    s1_iter = s1_block.values() if isinstance(s1_block, dict) else s1_block
    s1_pools = [
        pool for pool in (pool_from_stems(essay_subs, list(stems))
                          for stems in s1_iter)
        if pool
    ]

    s2_block = groups.get("P_s2") or {}
    if isinstance(s2_block, dict):
        s2_label_pools: dict[str, dict[str, str]] = {
            label: pool_from_stems(essay_subs, list(stems))
            for label, stems in s2_block.items()
        }
    else:
        s2_label_pools = {
            str(idx): pool_from_stems(essay_subs, list(stems))
            for idx, stems in enumerate(s2_block)
        }

    for label, pool in (("H", h_pool), ("V", v_pool), ("D", d_pool)):
        if pool:
            require_within_pair_coverage(cohort, label, pool, pair_rel)
    for idx, pool in enumerate(d_combo_pools):
        require_within_pair_coverage(cohort, f"D_combos[{idx}]", pool, pair_rel)
    for idx, pool in enumerate(s1_pools):
        require_within_pair_coverage(cohort, f"P_s1[{idx}]", pool, pair_rel)
    for label, pool in s2_label_pools.items():
        if pool:
            require_within_pair_coverage(cohort, f"P_s2[{label}]", pool, pair_rel)

    # |D| candidate for common-m: prefer the combo-based d_min when
    # D_combos is set, otherwise fall back to the pooled D size.
    d_candidate = d_min if d_combos_spec else len(d_pool)

    candidates = [len(h_pool), len(v_pool), d_candidate]
    candidates += [len(p) for p in s1_pools]
    candidates += [len(p) for p in s2_label_pools.values() if p]
    candidates = [c for c in candidates if c > 0]
    if not candidates:
        return None
    m = min(candidates)

    row: dict[str, Any] = {
        "cohort": cohort,
        "m": m,
        "sizes": {
            "H": len(h_pool),
            "V": len(v_pool),
            "D": d_candidate,
            "D_combos": len(d_combo_pools) if d_combos_spec else 0,
            "P_s1": [len(p) for p in s1_pools],
            "P_s2": {k: len(v) for k, v in s2_label_pools.items()},
        },
    }
    for tname, rel in thresholds.items():
        u_h = within_unique(h_pool, pair_rel, m, rel) if h_pool else float("nan")
        u_v = within_unique(v_pool, pair_rel, m, rel) if v_pool else float("nan")
        if d_combos_spec:
            if d_combo_pools:
                d_vals = [within_unique(pool, pair_rel, m, rel)
                          for pool in d_combo_pools]
                u_d = _macro_average(d_vals)
            else:
                u_d = float("nan")
        else:
            u_d = within_unique(d_pool, pair_rel, m, rel) if d_pool else float("nan")
        if s1_pools:
            s1_vals = [within_unique(p, pair_rel, m, rel) for p in s1_pools]
            u_s1 = _macro_average(s1_vals)
        else:
            u_s1 = float("nan")
        u_s2_per = {
            label: within_unique(p, pair_rel, m, rel)
            for label, p in s2_label_pools.items() if p
        }
        u_s2 = _macro_average(list(u_s2_per.values())) if u_s2_per else float("nan")
        row[tname] = {
            "U_human": u_h,
            "U_default": u_v,
            "U_diversified": u_d,
            "U_position_guided_s1": u_s1,
            "U_position_guided_s2": u_s2,
            "U_position_guided_s2_per_label": u_s2_per,
        }
    return row


def run_um(spec: dict[str, Any],
           data_root: Path | str | None = None,
           ) -> dict[str, Any]:
    """Run U_m across all cohorts in ``spec``.

    Spec shape::

      venue: <venue subdirectory>
      thresholds: [strict, loose]      # optional, defaults to both
      cohorts:                          # required
        <cohort_slug>:
          H:    [stem, ...]            # humans pool (one pool)
          V:    [stem, ...]            # default-LLM pool (one pool)
          D:    [stem, ...]            # diversified pool (one pool)
          P_s1: {position: [stem, ...]} # same position, different LLMs
          P_s2: {label:    [stem, ...]} # different positions, same LLM

    Returns ``{"rows": [...], "macro_strict": {...}, "macro_loose": {...}}``.
    """
    if np is None:
        raise RuntimeError("numpy is required for run_um; run `uv sync` from the repository root")

    venue = spec["venue"]
    cohorts = spec["cohorts"]
    threshold_names = spec.get("thresholds") or list(THRESHOLDS.keys())
    selected_thresholds = {n: THRESHOLDS[n] for n in threshold_names}

    root = Path(data_root) if data_root is not None else get_data_root()

    rows: list[dict[str, Any]] = []
    if detect_layout(root) == LAYOUT_AGGREGATE:
        venue_key = normalize_venue(venue)
        toulmin_by_cohort = dict(iter_cohort_jsonl(venue_key, "toulmin.jsonl", root))
        sub_pairs_by_cohort = dict(iter_cohort_jsonl(venue_key, "sub_argument_pairs.jsonl", root))
        for cohort, groups in cohorts.items():
            essay_subs, pair_rel = load_cohort_from_rows(
                toulmin_by_cohort.get(cohort, []),
                sub_pairs_by_cohort.get(cohort, []),
            )
            row = cohort_um_row(cohort, groups, essay_subs, pair_rel,
                                thresholds=selected_thresholds)
            if row is not None:
                rows.append(row)
    else:
        venue_root = root / venue
        for cohort, groups in cohorts.items():
            cohort_dir = venue_root / cohort
            if not cohort_dir.is_dir():
                continue
            essay_subs, pair_rel = load_cohort(cohort_dir)
            row = cohort_um_row(cohort, groups, essay_subs, pair_rel,
                                thresholds=selected_thresholds)
            if row is not None:
                rows.append(row)

    def macro_avg(field: str, tname: str) -> float:
        vals = [r[tname][field] for r in rows
                if r[tname].get(field) is not None
                and not (isinstance(r[tname][field], float)
                          and np.isnan(r[tname][field]))]
        return float(np.mean(vals)) * 100 if vals else float("nan")

    macros = {
        f"macro_{tname}": {
            field: macro_avg(field, tname)
            for field in ("U_human", "U_default", "U_diversified",
                          "U_position_guided_s1", "U_position_guided_s2")
        }
        for tname in selected_thresholds
    }
    return {"rows": rows, **macros}


# ---------- CLI ----------

def _load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml  # imported lazily so JSON-only users don't need pyyaml
        return yaml.safe_load(text)
    return json.loads(text)


def _print_table(result: dict[str, Any]) -> None:
    rows = result["rows"]
    print(f"Processed {len(rows)} cohorts (common-m per cohort)\n")
    header = f"{'Metric':>40s}  {'Strict':>8s}  {'Loose':>8s}"
    print(header)
    print("-" * len(header))
    for label, key in [
        ("Humans (cluster)",                "U_human"),
        ("Default LLMs (vanilla medoid)",   "U_default"),
        ("Diversified (1-per-family)",      "U_diversified"),
        ("Same position, diff LLMs (S1)",   "U_position_guided_s1"),
        ("Diff positions, same LLM (S2)",   "U_position_guided_s2"),
    ]:
        s = result.get("macro_strict", {}).get(key, float("nan"))
        l = result.get("macro_loose", {}).get(key, float("nan"))
        print(f"  {label:>38s}  {s:>7.1f}%  {l:>7.1f}%")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    um = sub.add_parser("um",
                        help="Compute within-group unique rate U_m from a spec.")
    um.add_argument("--spec", required=True,
                    help="YAML or JSON spec listing cohorts and group "
                         "assignments. See docstring for the schema.")
    um.add_argument("--data-root", default=None,
                    help="Dataset root directory; defaults to "
                         "$ARGUMENT_COLLAPSE_DATA_ROOT if set, otherwise "
                         "./data.")
    um.add_argument("--output", default=None,
                    help="Write the JSON result to this path "
                         "(default: stdout only).")
    um.add_argument("--no-table", action="store_true",
                    help="Suppress the human-readable summary table.")

    args = p.parse_args(argv)

    if args.data_root:
        set_data_root(args.data_root)

    spec = _load_spec(Path(args.spec))
    try:
        result = run_um(spec, data_root=args.data_root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.no_table:
        _print_table(result)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(
            result, indent=2,
            default=lambda x: None if (np is not None
                                       and isinstance(x, float)
                                       and np.isnan(x)) else x,
        ))
        print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
