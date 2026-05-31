# Argument Collapse

Code and data for the paper *Argument Collapse: LLMs Flatten Long-Form Public Debate*.

This repository contains:

- A **Python package** (`src/argument_collapse/`) implementing the analysis pipeline. The package measures how LLM-generated argumentative essays collapse onto a narrower range of main arguments, supporting reasons, and paragraph-level structures than comparable human essays.
- A **public data release** (`data/`) packaging the debates, essays, extractions, and judgments used in the paper as gzipped JSONL tables, alongside the prompts that produced them (`prompts/`).

## Installation

```bash
git clone https://github.com/mungg/argument_collapse.git
cd argument_collapse
pip install -e .
```

The package targets Python ≥ 3.10. LLM providers (OpenAI, Anthropic, Google Vertex, OpenRouter) are pulled in as optional clients; install only the ones you plan to call.

If you only want to load and inspect the released data, the lighter `analysis` extra (for pandas) and `huggingface` extra (for the `datasets` library) avoid pulling in the LLM provider stack:

```bash
pip install -e ".[analysis]"
pip install -e ".[huggingface]"
```

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
                         # refetch_human_essays.py         (reconstruct human bodies)
data/                    # released JSONL tables (see "Data release" below)
prompts/                 # released system + user prompts
```

After `pip install -e .` the following CLI entry points are available:

| Command                       | What it does                                                                            |
|-------------------------------|-----------------------------------------------------------------------------------------|
| `ac-toulmin`                  | **Extract** each essay's main argument + supporting sub-arguments via LLM prompt.       |
| `ac-pair-comparison-main-arg` | **Compare** two essays' main arguments pairwise; emits one of four overlap labels.      |
| `ac-pair-comparison-sub-arg`  | **Compare** two essays' sub-arguments pairwise; emits one of four overlap labels.       |
| `ac-stance`                   | **Label** each essay's stance on the cohort's binary debate axis (`stage1` / `stage2`).|
| `ac-metric`                   | **Compute** within-group unique rate U_m from a YAML spec.                             |

Each annotation row carries a `tagger_prompt_version` field so different prompt variants stay distinguishable in the released JSONL files:

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

**Working / legacy layout (cohort-grouped)** — what the annotation pipeline writes incrementally:

```
<data_root>/<venue>/<cohort>/
├── human/{00_question.md,00_lead.md,<author>.md}
├── generated/<stem>.md
└── analysis/{toulmin,main_argument_pairs,sub_argument_pairs}.jsonl
```

`data.detect_layout(path)` returns `"split"` or `"cohort_grouped"`; the public API (`iter_cohort_jsonl`, `cohort_analysis_path`, `find_human_responses`, …) hides the difference from callers.

## Reproducing paper numbers

The annotated dataset (annotations, LLM-generated essays, cohort metadata) is released separately. Once it is downloaded under `data/dataset/` (or you have set `ARGUMENT_COLLAPSE_DATA_ROOT`), the headline U_m numbers from Section 4 of the paper are one shell call away:

```bash
./scripts/reproduce_subarg_diversity.sh
```

That wraps `ac-metric um --spec configs/subarg_diversity_16cohort_nyt.yaml` and writes the detailed per-cohort breakdown to `results/subarg_diversity_16cohort_nyt.json`. Expected output (loose threshold, common-m, 16 NYT cohorts):

| Metric                                    | Strict | Loose |
|-------------------------------------------|--------|-------|
| Humans (cluster)                          | 94.9%  | 41.0% |
| Vanilla LLMs (medoid)                     | 60.6%  |  9.1% |
| Diversified (1-per-family)                | 81.4%  | 22.8% |
| Same position, different LLMs (S1)        | 56.4%  |  6.8% |
| Different positions, same LLM (S2)        | 72.7%  | 18.4% |

The diversified row is computed by sampling up to 200 1-per-family combos per cohort with a fixed seed; the paper reports 22.9%, which is within sampling noise of the value above.

The dataset uses three LLM-condition codes:

| Code             | Setup                                                                                       |
|------------------|---------------------------------------------------------------------------------------------|
| `vanilla`        | Default LLM, no persona. Out-of-the-box baseline.                                           |
| `diversified`    | Single API call asking for a batch of N distinct responses.                                 |
| `position-guided`| Position-grounded generation. The LLM is given an anonymized sketch of one human responder and asked to write from that writer's perspective. |

### Re-running the annotation pipeline

To re-run the annotation pipeline end-to-end on the released markdown essays (expensive: uses your own LLM API keys, on the order of $50 of spend, several hours), use `./scripts/run_annotation_pipeline.sh` or invoke each stage directly:

```bash
# Step 1 — EXTRACTION: per-essay main_argument + sub_arguments
ac-toulmin  --venue NYT-Room-for-Debate-filtered \
            --kinds human,vanilla,diversified,position-guided

# Step 2 — PAIR COMPARISON: 4-label judge over main-argument pairs
ac-pair-comparison-main-arg --venue NYT-Room-for-Debate-filtered \
                            --kinds human,vanilla

# Step 3 — PAIR COMPARISON: 4-label judge over sub-argument pairs
ac-pair-comparison-sub-arg  --venue NYT-Room-for-Debate-filtered \
                            --kinds human,vanilla,diversified,position-guided

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

---

## Data release

The `data/` directory packages the public-facing version of the corpus as gzipped JSONL tables. Each row is self-contained and joins on `(venue, debate_id)` plus `(venue, debate_id, essay_id)`. Data is partitioned by venue (`data/nyt/` and `data/br/`); rows still carry `venue`, so files can be concatenated cross-venue without ambiguity.

```
data/
├── nyt/           # 195 NYT Room for Debate debates
│   ├── debates.jsonl.gz                    195 rows
│   ├── human_essays.jsonl.gz             1,039
│   ├── llm_essays.jsonl.gz              16,661
│   ├── personas.jsonl.gz                 1,039
│   ├── toulmin.jsonl.gz                 17,703
│   ├── main_argument_pairs.jsonl.gz    231,284
│   ├── grounding_pairs.jsonl.gz          5,195
│   ├── structure_argument.jsonl.gz      17,679
│   └── structure_discourse_mode.jsonl.gz 17,679
└── br/            # 61 Boston Review forums
    ├── debates.jsonl.gz                     61 rows
    ├── human_essays.jsonl.gz               448
    ├── llm_essays.jsonl.gz               6,720
    ├── personas.jsonl.gz                   448
    ├── toulmin.jsonl.gz                  7,168
    ├── main_argument_pairs.jsonl.gz     58,755
    ├── grounding_pairs.jsonl.gz          2,240
    ├── structure_argument.jsonl.gz       7,168
    └── structure_discourse_mode.jsonl.gz 7,168
```

| File | What it holds |
|---|---|
| `debates.jsonl.gz` | Per-debate metadata: title, source, topic, question type, the full debate question (NYT) or full lead essay (BR), and the essay count under each condition. |
| `human_essays.jsonl.gz` | One row per human responder essay, with metadata only (author, bio, date, word count). The body text is not redistributed. See `scripts/refetch_human_essays.py` to recover it. |
| `llm_essays.jsonl.gz` | One row per LLM-generated essay, full text included. Three conditions (`vanilla`, `diversified`, `position-guided`) across five frontier LLMs (GPT-5.5, Gemini 3.1 Pro, Claude Opus 4.7, MiniMax M2.7, DeepSeek v4 Pro). Vanilla rows carry an `is_representative` boolean that flags the model-level medoid for each debate. |
| `personas.jsonl.gz` | One row per persona used to ground `position-guided` generation. Each persona records a name (not shown to the model), an anonymized role description, and a tone description. |
| `toulmin.jsonl.gz` | Extracted main argument and ordered sub-arguments, one row per essay, for humans and all three LLM conditions. |
| `main_argument_pairs.jsonl.gz` | Pairwise judgments over each pair's main arguments, using a four-label scheme (`equivalent`, `strong_overlap`, `weak_overlap`, `different`) with a short rationale. |
| `grounding_pairs.jsonl.gz` | A convenience subset: each row is one (human, position-guided) pair where the position-guided essay was grounded on that specific human. The sanity check that the model preserved the assigned thesis. |
| `structure_argument.jsonl.gz` | Per-paragraph argument-role labels: `thesis`, `support`, `concession`, `rebuttal`, `reframing`, `proposal`, `implication`, or `none`. |
| `structure_discourse_mode.jsonl.gz` | Per-paragraph discourse-mode labels: `argumentation`, `exposition`, `narration`, or `description`. |

See `SCHEMA.md` for column-level documentation. For a quick look at the format without decompressing the `.gz` files, see [`data/EXAMPLES.md`](data/EXAMPLES.md): one pretty-printed sample row from every table per venue.

### Quickstart

Load a single venue with pandas:

```python
import pandas as pd
from pathlib import Path

NYT = Path("data/nyt")
debates = pd.read_json(NYT / "debates.jsonl.gz",              lines=True)
toulmin = pd.read_json(NYT / "toulmin.jsonl.gz",              lines=True)
pairs   = pd.read_json(NYT / "main_argument_pairs.jsonl.gz",  lines=True)

# all NYT vanilla representatives (one per debate × model)
reps = pd.read_json(NYT / "llm_essays.jsonl.gz", lines=True)
reps = reps.query("condition == 'vanilla' and is_representative")
```

Using HuggingFace `datasets`:

```python
from datasets import load_dataset
toulmin = load_dataset("json", data_files="data/*/toulmin.jsonl.gz", split="train")
```

### Reconstructing the human-essay corpus

Human responder essays are not redistributed here; their original publishers retain copyright. `human_essays.jsonl.gz` carries every field needed to re-locate each essay (debate slug, author, date, word count). Run `scripts/refetch_human_essays.py` to walk the index and recover bodies from the published URLs, then merge them back into your local corpus.

## Prompts

`prompts/` ships every system and user prompt used in the pipeline, alongside rendered examples (`prompts/examples/`) and a programmatic index (`prompts/prompts.jsonl`) that maps each `prompt_version` tag to its full text. The index includes the four annotation prompts (toulmin, main-argument judge, structure argument, structure discourse-mode), the dynamic generation prompts (with a Python helper that reproduces the exact text sent), and the preprocessing taggers (topic, question-type, sensitivity, persona, temporal-change filter). See `prompts/README.md` for the map.

## License

- **Code** (this repository and `scripts/`): MIT. See `LICENSE`.
- **Derived data** (`llm_essays`, `personas`, `toulmin`, `*_pairs`, `structure_*`): CC-BY-4.0.
- **Original source content** (NYT debate prompts, BR lead essays): see `DATA_LICENSE.md` for per-source terms and the human-essay re-fetch procedure.

## Citation

```bibtex
@inproceedings{argument_collapse_2026,
  title = {Argument Collapse: LLMs Flatten Long-Form Public Debate},
  author = {{TBD}},
  booktitle = {Proceedings of the Annual Meeting of the Association for Computational Linguistics},
  year = {2026},
}
```
