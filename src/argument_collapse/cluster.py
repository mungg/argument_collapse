"""Argument clustering primitives.

Pure analysis logic (no IO, no rendering, no heavy deps) shared by the
content-analysis pipeline. The two reproducibility-critical pieces are:

* :data:`SIMILARITY` — the 4-label relation -> [0,1] similarity weight used
  to rank candidate representatives. Reported in the paper as ``S = 1.0``,
  ``0.7``, ``0.3``, ``0.0`` for ``equivalent``, ``strong_overlap``,
  ``weak_overlap`` and ``different`` respectively.
* :func:`select_llm_representatives` — picks one canonical essay per LLM
  source per cohort (the 5 vanilla medoids referred to in the paper's
  16-cohort filter and pairwise analyses).

Each LLM "source" is identified by ``f"{kind}-{model}"`` (for example
``vanilla-gpt``, ``diversified-claude``); humans are returned individually. Callers
are expected to filter the input ``essays`` / ``cohort_pairs`` to the
sources they want before passing them in.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, TypedDict


# Continuous similarity score per 4-label relation. Tuning this changes
# representative selection and any downstream rank-by-centrality logic.
SIMILARITY: dict[str, float] = {
    "equivalent":     1.0,
    "strong_overlap": 0.7,
    "weak_overlap":   0.3,
    "different":      0.0,
}


# Relation strings recognized by the pairwise judge. Centralised so call
# sites avoid magic strings.
RELATION_EQUIVALENT = "equivalent"
RELATION_STRONG_OVERLAP = "strong_overlap"
RELATION_WEAK_OVERLAP = "weak_overlap"
RELATION_DIFFERENT = "different"
RELATIONS: tuple[str, ...] = (
    RELATION_EQUIVALENT,
    RELATION_STRONG_OVERLAP,
    RELATION_WEAK_OVERLAP,
    RELATION_DIFFERENT,
)

# Common edge sets used to construct clusters. "strict" matches only
# equivalent edges; "loose" also includes strong_overlap (the merge
# threshold used in the paper's main and sub-argument analyses).
STRICT_RELATIONS: frozenset[str] = frozenset({RELATION_EQUIVALENT})
LOOSE_RELATIONS: frozenset[str] = frozenset({RELATION_EQUIVALENT, RELATION_STRONG_OVERLAP})

# Marker for human essays. Other ``kind`` values are treated as LLM sources.
HUMAN_KIND = "human"


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class EssayDict(TypedDict, total=False):
    """Expected shape of a single essay entry.

    Required: ``stem``, ``kind``. ``model`` is required when ``kind != "human"``
    so the source label ``f"{kind}-{model}"`` is unambiguous.
    """

    stem: str
    kind: str
    model: str | None


class PairDict(TypedDict, total=False):
    """Expected shape of a single pairwise relation entry.

    Required: ``essay_i``, ``essay_j``, ``relation``. The relation must be one
    of :data:`RELATIONS`.
    """

    essay_i: str
    essay_j: str
    relation: str


# ---------------------------------------------------------------------------
# Union-find
# ---------------------------------------------------------------------------

class UnionFind:
    """Minimal path-compressed union-find over hashable elements."""

    def __init__(self) -> None:
        self.parent: dict = {}

    def add(self, x) -> None:
        self.parent.setdefault(x, x)

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def __contains__(self, x) -> bool:
        return x in self.parent


# Back-compat alias for any caller using the legacy private name.
_UF = UnionFind


# ---------------------------------------------------------------------------
# Cluster construction
# ---------------------------------------------------------------------------

def build_clusters(
    nodes: Iterable[str],
    pairs: Iterable[PairDict],
    threshold: Iterable[str] | str = "loose",
) -> list[list[str]]:
    """Group ``nodes`` into connected components over the relations selected
    by ``threshold``.

    ``threshold`` is either a relation iterable (e.g. ``{"equivalent"}``) or
    one of the shorthand strings ``"strict"`` (equivalent edges only) and
    ``"loose"`` (equivalent + strong_overlap edges; the paper default).

    Returns the components in unspecified order; member order inside each
    component follows ``nodes``.
    """
    if isinstance(threshold, str):
        if threshold == "strict":
            relations = STRICT_RELATIONS
        elif threshold == "loose":
            relations = LOOSE_RELATIONS
        else:
            raise ValueError(
                f"unknown threshold shorthand: {threshold!r}; "
                "use 'strict', 'loose', or pass an explicit iterable"
            )
    else:
        relations = frozenset(threshold)

    nodes = list(nodes)
    nset = set(nodes)
    uf = UnionFind()
    for n in nodes:
        uf.add(n)
    for pair in pairs:
        if pair.get("relation") not in relations:
            continue
        a, b = pair["essay_i"], pair["essay_j"]
        if a in nset and b in nset and a != b:
            uf.union(a, b)
    groups: dict = defaultdict(list)
    for n in nodes:
        groups[uf.find(n)].append(n)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Per-source representative selection
# ---------------------------------------------------------------------------

def select_llm_representatives(
    cohort_pairs: Iterable[PairDict],
    essays: Iterable[EssayDict],
) -> dict[str, str]:
    """Pick one representative essay per LLM source in a cohort.

    For each LLM source (``f"{kind}-{model}"``) the representative is the
    most central essay in that source's modal ``equivalent``-cluster, where
    centrality is the sum of :data:`SIMILARITY` weights to the other members
    of the same modal cluster. Humans are returned individually.

    When a source's essays split into several equally-populous equivalent
    clusters (e.g. a model that took two positions 2-vs-2), the modal cluster
    is the one whose lexicographically-smallest member stem is smallest. This
    keeps the choice order-invariant: it does not depend on which stem
    became the union-find root, which would otherwise be sensitive to
    edge-insertion order.

    Parameters
    ----------
    cohort_pairs : iterable of :class:`PairDict`
        Pairwise relations between essays in the cohort. Self-pairs are
        ignored.
    essays : iterable of :class:`EssayDict`
        All essays in the cohort. ``kind`` and (for non-humans) ``model``
        are read to identify each essay's source.

    Returns
    -------
    dict[str, str]
        Mapping ``{stem: source_label}`` containing every human plus exactly
        one representative per distinct LLM source. ``source_label`` is
        ``"human"`` for humans and ``f"{kind}-{model}"`` for LLM reps.
    """
    essays = list(essays)
    cohort_pairs = list(cohort_pairs)

    # Lookup table for pair relations keyed by unordered pair.
    relation_by_pair: dict[frozenset[str], str | None] = {
        frozenset((p["essay_i"], p["essay_j"])): p.get("relation")
        for p in cohort_pairs
        if p.get("essay_i") != p.get("essay_j")
    }

    # Equivalent-only union-find: clusters whose members the judge ruled
    # mutually equivalent.
    uf = UnionFind()
    for e in essays:
        uf.add(e["stem"])
    for p in cohort_pairs:
        if p.get("relation") != RELATION_EQUIVALENT:
            continue
        a, b = p["essay_i"], p["essay_j"]
        if a in uf and b in uf:
            uf.union(a, b)
    stem_root = {e["stem"]: uf.find(e["stem"]) for e in essays}

    # Per-source modal equivalent-cluster.
    src_cluster_counts: dict[str, Counter] = defaultdict(Counter)
    src_members_by_root: dict[tuple[str, str], list[str]] = defaultdict(list)
    for e in essays:
        if e.get("kind") == HUMAN_KIND:
            continue
        src = f"{e['kind']}-{e.get('model') or '?'}"
        root = stem_root[e["stem"]]
        src_cluster_counts[src][root] += 1
        src_members_by_root[(src, root)].append(e["stem"])

    # Largest cluster wins; ties broken by the cluster's smallest member
    # stem (order-invariant) rather than the union-find root label
    # (order-dependent).
    modal_root_by_src: dict[str, str] = {}
    for src, counts in src_cluster_counts.items():
        max_count = max(counts.values())
        modal_root_by_src[src] = min(
            (r for r, c in counts.items() if c == max_count),
            key=lambda r: min(src_members_by_root[(src, r)]),
        )

    out: dict[str, str] = {}
    for e in sorted(essays, key=lambda x: x["stem"]):
        if e.get("kind") == HUMAN_KIND:
            out[e["stem"]] = HUMAN_KIND

    for src, root in modal_root_by_src.items():
        candidates = sorted(src_members_by_root[(src, root)])

        def centrality(stem: str) -> tuple[float, int]:
            score = 0.0
            observed = 0
            for other in candidates:
                if other == stem:
                    continue
                rel = relation_by_pair.get(frozenset((stem, other)))
                if rel is None:
                    continue
                score += SIMILARITY.get(rel, 0.0)
                observed += 1
            return score, observed

        # ``max`` keeps the first candidate on exact ties; sorting the
        # candidates above makes the tie-break deterministic without
        # changing the score itself.
        out[max(candidates, key=centrality)] = src

    return out
