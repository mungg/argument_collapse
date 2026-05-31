# Argument Collapse

Code for the paper *Argument Collapse: LLMs Flatten Long-Form Public Debate*.

This repository contains the analysis pipeline used to measure how LLM-generated
argumentative essays collapse onto a narrower range of main arguments,
supporting reasons, and paragraph-level structures than comparable human
essays.

## Installation

```bash
git clone https://github.com/mungg/argument_collapse.git
cd argument_collapse
pip install -e .
```

The package targets Python ≥ 3.10. LLM providers (OpenAI, Anthropic, Google
Vertex, OpenRouter) are pulled in as optional clients; install only the ones
you plan to call.

## Repository structure

```
src/argument_collapse/   # main package
├── annotate/            # LLM annotation passes
│   ├── toulmin.py                      # extraction: essay -> {main_argument, sub_arguments}
│   ├── pair_comparison_main_arg.py     # pairwise comparison of main arguments (4-label)
│   ├── pair_comparison_sub_arg.py      # pairwise comparison of sub-arguments  (4-label)
│   └── stance.py                       # per-essay stance labelling (2 stages)
├── cluster.py           # union-find argument clustering + medoid selection
├── metric.py            # within-group unique rate U_m, recovery rates
├── data.py              # cohort / essay loaders (handles two on-disk layouts)
└── inference/           # LLM provider wrappers (OpenAI, Vertex, OpenRouter)
configs/                 # paper-run YAML specs
                         #   subarg_diversity_16cohort_nyt.yaml
scripts/                 # reproduce_subarg_diversity.sh   (paper numbers)
                         # run_annotation_pipeline.sh      (full pipeline)
```

After `pip install -e .` the following CLI entry points are available:

| Command                       | What it does                                                                            |
|-------------------------------|-----------------------------------------------------------------------------------------|
| `ac-toulmin`                  | **Extract** each essay's main argument + supporting sub-arguments via LLM prompt.       |
| `ac-pair-comparison-main-arg` | **Compare** two essays' main arguments pairwise; emits one of four overlap labels.      |
| `ac-pair-comparison-sub-arg`  | **Compare** two essays' sub-arguments pairwise; emits one of four overlap labels.       |
| `ac-stance`                   | **Label** each essay's stance on the cohort's binary debate axis (`stage1` / `stage2`).|
| `ac-metric`                   | **Compute** within-group unique rate U_m from a YAML spec.                             |

Each annotation row carries a `tagger_prompt_version` field so different
prompt variants stay distinguishable in the released JSONL files:

| Stage                          | Base tag                  | Suffix (per cohort context kind) |
|--------------------------------|---------------------------|-----------------------------------|
| toulmin extraction             | `toulmin_annotation`      | `` / `_lead`                      |
| main-argument pair comparison  | `pair_comparison_main_arg`| `` / `_lead`                      |
| sub-argument pair comparison   | `pair_comparison_sub_arg` | `` / `_lead` / `_none`            |
| stance stage 1 (sides)         | `stance_stage1`           | —                                 |
| stance stage 2 (labels)        | `stance_stage2`           | —                                 |

## Configuring the data root

The data root resolves in this order:

1. `--data-root <path>` CLI flag (per-command)
2. `ARGUMENT_COLLAPSE_DATA_ROOT` environment variable
3. `./data/dataset` (default)

Two on-disk layouts are auto-detected by the loader:

**Public release (split layout)** — what the downloadable dataset uses:

```
<data_root>/
├── cohorts.jsonl                       # cohort index: venue, context_kind, ...
├── essays/<venue>/<cohort>/
│   ├── 00_question.md   or   00_lead.md
│   ├── humans/<author>.md
│   └── generated/<stem>.md
└── annotations/
    ├── toulmin.jsonl                   # flat across venues + cohorts
    ├── main_argument_pairs.jsonl
    ├── sub_argument_pairs.jsonl
    └── stance.jsonl                    # binary cohorts only
```

**Working / legacy layout (cohort-grouped)** — what the annotation pipeline
writes incrementally:

```
<data_root>/<venue>/<cohort>/
├── human/{00_question.md,00_lead.md,<author>.md}
├── generated/<stem>.md
└── analysis/{toulmin,main_argument_pairs,sub_argument_pairs}.jsonl
```

`data.detect_layout(path)` returns `"split"` or `"cohort_grouped"`; the
public API (`iter_cohort_jsonl`, `cohort_analysis_path`, `find_human_responses`, …)
hides the difference from callers.

## Reproducing paper numbers

The annotated dataset (annotations, LLM-generated essays, cohort metadata) is
released separately. Once it is downloaded under `data/dataset/` (or you
have set `ARGUMENT_COLLAPSE_DATA_ROOT`), the headline U_m numbers from
Section 4 of the paper are one shell call away:

```bash
./scripts/reproduce_subarg_diversity.sh
```

That wraps `ac-metric um --spec configs/subarg_diversity_16cohort_nyt.yaml`
and writes the detailed per-cohort breakdown to
`results/subarg_diversity_16cohort_nyt.json`. Expected
output (loose threshold, common-m, 16 NYT cohorts):

| Metric                                    | Strict | Loose |
|-------------------------------------------|--------|-------|
| Humans (cluster)                          | 94.9%  | 41.0% |
| Vanilla LLMs (medoid)                     | 60.6%  |  9.1% |
| Diversified (1-per-family)                | 81.4%  | 22.8% |
| Same position, different LLMs (S1)        | 56.4%  |  6.8% |
| Different positions, same LLM (S2)        | 72.7%  | 18.4% |

The diversified row is computed by sampling up to 200 1-per-family
combos per cohort with a fixed seed; the paper reports 22.9%, which is
within sampling noise of the value above.

The dataset uses three LLM-condition codes:

| Code           | Setup                                               |
|----------------|-----------------------------------------------------|
| `vanilla`      | Default LLM, no persona — out-of-the-box baseline.  |
| `diversified`  | 1-per-family diverse sampling at higher effort.     |
| `position`     | Position-grounded generation (essay's stance pre-assigned from the matched human's slug). |

### Re-running the annotation pipeline

To re-run the annotation pipeline end-to-end on the released markdown
essays (expensive — uses your own LLM API keys, ~$50 of spend, several
hours), use `./scripts/run_annotation_pipeline.sh` or invoke each stage
directly:

```bash
# Step 1 — EXTRACTION: per-essay main_argument + sub_arguments
ac-toulmin  --venue NYT-Room-for-Debate-filtered \
            --kinds human,vanilla,diversified,position

# Step 2 — PAIR COMPARISON: 4-label judge over main-argument pairs
ac-pair-comparison-main-arg --venue NYT-Room-for-Debate-filtered \
                            --kinds human,vanilla

# Step 3 — PAIR COMPARISON: 4-label judge over sub-argument pairs
ac-pair-comparison-sub-arg  --venue NYT-Room-for-Debate-filtered \
                            --kinds human,vanilla,diversified,position

# Step 4 — STANCE LABELLING (binary cohorts only, two stages)
ac-stance stage1 --venue NYT-Room-for-Debate-filtered \
                 --cohort are-americans-too-obsessed-with-cleanliness \
                 --output results/stance_sides.json
ac-stance stage2 --venue NYT-Room-for-Debate-filtered \
                 --sides  results/stance_sides.json \
                 --output results/stance_labels.json

# Step 5 — METRIC: sub-argument diversity U_m
ac-metric um \
    --spec   configs/subarg_diversity_16cohort_nyt.yaml \
    --output results/subarg_diversity_16cohort_nyt.json
```

## Data release

Original human essays from *NYT Room for Debate* and *Boston Review* are not
redistributed here because the publishers retain copyright. We release URLs,
parsed metadata, and our derived annotations (extracted main and sub
arguments, pairwise overlap labels, stance labels, cluster assignments)
alongside the LLM-generated essays produced under each provider's research
terms. See the data release note (forthcoming) for a download link.

## License

Code is released under the [MIT License](LICENSE). Derived annotations and
LLM-generated essays released with this project follow the same MIT terms;
the original NYT and BR essays remain under their respective publishers'
copyright.

## Citation

```bibtex
@inproceedings{argument_collapse_2026,
  title = {Argument Collapse: LLMs Flatten Long-Form Public Debate},
  author = {{TBD}},
  booktitle = {Proceedings of the Annual Meeting of the Association for Computational Linguistics},
  year = {2026},
}
```
