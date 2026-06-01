# Argument Collapse

Code and data for the paper *Argument Collapse: LLMs Narrow the Argument Content and Structure in Public Debate*.

This repository contains:

- **Code** in `src/argument_collapse/` for measuring whether LLM essays repeat the same main arguments, supporting reasons, and paragraph structures more than human essays do.
- **Data** in `data/`, released as gzipped JSONL tables, plus the prompts used to generate and annotate the data in `prompts/`.

## Installation

We use [`uv`](https://docs.astral.sh/uv/) for dependency management.

```bash
git clone https://github.com/mungg/argument_collapse.git
cd argument_collapse
uv sync
```

The package targets Python ≥ 3.10. Run command-line tools through `uv run`, which uses the project environment created from `pyproject.toml` and `uv.lock`.

For data-loading or notebook workflows, sync the relevant optional extra:

```bash
uv sync --extra analysis      # pandas-based inspection
uv sync --extra huggingface   # Hugging Face datasets loader
```

## Repository structure

```
src/argument_collapse/   # main package
├── annotate/            # LLM annotation passes
│   ├── toulmin.py                      # extraction: essay -> {main_argument, sub_arguments}
│   ├── pair_comparison_main_arg.py     # pairwise comparison of main arguments (4-label)
│   ├── pair_comparison_sub_arg.py      # pairwise comparison of sub-arguments  (4-label)
│   ├── structure.py                    # paragraph-level structure annotation
│   └── stance.py                       # per-essay stance labelling (2 stages)
├── cluster.py           # grouping arguments and picking representative LLM answers
├── metric.py            # uniqueness and recovery metrics
├── data.py              # data loaders
└── inference/           # LLM provider wrappers (OpenAI, Vertex, OpenRouter)
configs/                 # YAML files for paper metrics
scripts/                 # reproduce numbers, rerun annotation, and re-fetch human essays
data/                    # released JSONL tables (see "Data release" below)
prompts/                 # released system + user prompts
```

After `uv sync`, the following CLI entry points are available through `uv run`:

| Command                       | What it does                                                                            |
|-------------------------------|-----------------------------------------------------------------------------------------|
| `ac-toulmin`                  | **Extract** each essay's main argument + supporting sub-arguments via LLM prompt.       |
| `ac-pair-comparison-main-arg` | **Compare** two essays' main arguments pairwise; emits one of four overlap labels.      |
| `ac-pair-comparison-sub-arg`  | **Compare** two essays' sub-arguments pairwise; emits one of four overlap labels.       |
| `ac-stance`                   | **Label** each essay's stance on binary debate questions.                              |
| `ac-structure`                | **Annotate** paragraph-level argumentative role and discourse mode.                      |
| `ac-metric`                   | **Compute** uniqueness and recovery metrics from a YAML file.                           |

Annotation rows include a `tagger_prompt_version` field that points back to the prompt used:

| Stage                          | Base tag                  | Suffix |
|--------------------------------|---------------------------|-----------------------------------|
| toulmin extraction             | `toulmin_annotation`      | `` / `_lead`                      |
| main-argument pair comparison  | `pair_comparison_main_arg`| `` / `_lead`                      |
| sub-argument pair comparison   | `pair_comparison_sub_arg` | `` / `_lead` / `_none`            |
| structure argument roles       | `structure_argument`      | —                                 |
| structure discourse mode       | `structure_discourse_mode`| —                                 |
| stance stage 1 (sides)         | `stance_stage1`           | —                                 |
| stance stage 2 (labels)        | `stance_stage2`           | —                                 |

## Configuring the data root

The data root resolves in this order:

1. `--data-root <path>` CLI flag (per-command)
2. `ARGUMENT_COLLAPSE_DATA_ROOT` environment variable
3. `./data` (default)

The public data is stored as gzipped JSONL tables, split by venue:

```
<data_root>/
├── nyt/
│   ├── debates.jsonl.gz
│   ├── human_essays.jsonl.gz
│   ├── llm_essays.jsonl.gz
│   ├── position_guides.jsonl.gz
│   ├── toulmin.jsonl.gz
│   ├── main_argument_pairs.jsonl.gz
│   ├── sub_argument_pairs.jsonl.gz
│   ├── grounding_pairs.jsonl.gz
│   ├── structure_argument.jsonl.gz
│   └── structure_discourse_mode.jsonl.gz
└── br/
    └── ... same table names
```

The loader also supports the older per-debate working layout used when rerunning annotation:

```
<data_root>/<venue>/<debate>/
├── human/{00_question.md,00_lead.md,<author>.md}
├── generated/<stem>.md
└── analysis/{toulmin,main_argument_pairs,sub_argument_pairs}.jsonl
```

The loader detects whether you are using the public tables or the older per-debate layout.

## Reproducing paper numbers

Main-argument and structure analyses use the broad NYT and BR tables. Sub-argument analysis is narrower by design, because it requires many pairwise judgments between supporting claims. The release therefore includes sub-argument pair annotations for selected analysis subsets, not for every possible essay pair in the full corpus.

The current public-condition export contains `374,414` NYT sub-argument pair rows across `83` debates and `31,466` BR rows across `11` forums. It includes only the public conditions used in the paper: `human`, `vanilla`, `diversified`, and `position-guided`. Older internal conditions are not exported. The NYT rows cover the shared-main vanilla comparison; diversified, position-guided, and BR sub-argument rows are included where available and should be used with the coverage checks below.

To compute the NYT sub-argument uniqueness table for a configured subset, run:

```bash
./scripts/reproduce_subarg_diversity.sh
```

The script runs `uv run ac-metric um --spec configs/subarg_diversity_16cohort_nyt.yaml` and writes details to `results/subarg_diversity_16cohort_nyt.json`. The metric code checks coverage before computing: if a config asks for a group whose sub-argument pairs are not fully annotated, it exits instead of treating missing labels as non-overlap. For configs that include diversified or position-guided groups, use a data root with the matching annotation subset.

The dataset uses three LLM-condition codes:

| Code | Setup |
|---|---|
| `vanilla` | The model answers normally. |
| `diversified` | The model is asked to produce several different answers in one call. |
| `position-guided` | The model writes from an anonymized human writer's main argument and background. |

### Re-running annotation

To rerun annotation, provide local markdown essays under `human/` and `generated/`. This uses your own LLM API keys and can cost about $50. The public release does not include human essay bodies. Use `./scripts/run_annotation_pipeline.sh` or run the steps directly:

```bash
# Step 1 — EXTRACTION: per-essay main_argument + sub_arguments
uv run ac-toulmin  --venue NYT-Room-for-Debate-filtered \
            --kinds human,vanilla,diversified,position-guided

# Step 2 — PAIR COMPARISON: 4-label judge over main-argument pairs
uv run ac-pair-comparison-main-arg --venue NYT-Room-for-Debate-filtered \
                            --kinds human,vanilla

# Step 3 — PAIR COMPARISON: 4-label judge over sub-argument pairs
uv run ac-pair-comparison-sub-arg  --venue NYT-Room-for-Debate-filtered \
                            --kinds human,vanilla,diversified,position-guided

# Step 4 — STRUCTURE ANNOTATION: paragraph-level argument role + discourse mode
uv run ac-structure --venue NYT-Room-for-Debate-filtered \
             --kinds human,vanilla,diversified,position-guided \
             --layer both

# Step 5 — STANCE LABELLING (binary cohorts only, two stages)
uv run ac-stance stage1 --venue NYT-Room-for-Debate-filtered \
                 --cohort are-americans-too-obsessed-with-cleanliness \
                 --output results/stance_sides.json
uv run ac-stance stage2 --venue NYT-Room-for-Debate-filtered \
                 --sides  results/stance_sides.json \
                 --output results/stance_labels.json

# Step 6 — METRIC: sub-argument uniqueness
uv run ac-metric um \
    --spec   configs/subarg_diversity_16cohort_nyt.yaml \
    --output results/subarg_diversity_16cohort_nyt.json
```

## Data release

The `data/` directory contains gzipped JSONL tables. Join debate-level rows with `(venue, debate_id)` and essay-level rows with `(venue, debate_id, essay_id)`.

```
data/
├── nyt/           # 195 NYT Room for Debate debates
│   ├── debates.jsonl.gz                    195 rows
│   ├── human_essays.jsonl.gz             1,039
│   ├── llm_essays.jsonl.gz              16,661
│   ├── position_guides.jsonl.gz          1,039
│   ├── toulmin.jsonl.gz                 17,703
│   ├── main_argument_pairs.jsonl.gz    231,284
│   ├── sub_argument_pairs.jsonl.gz     374,414
│   ├── grounding_pairs.jsonl.gz          5,195
│   ├── structure_argument.jsonl.gz      17,679
│   └── structure_discourse_mode.jsonl.gz 17,679
└── br/            # 61 Boston Review forums
    ├── debates.jsonl.gz                     61 rows
    ├── human_essays.jsonl.gz               448
    ├── llm_essays.jsonl.gz               6,720
    ├── position_guides.jsonl.gz            448
    ├── toulmin.jsonl.gz                  7,168
    ├── main_argument_pairs.jsonl.gz     58,755
    ├── sub_argument_pairs.jsonl.gz      31,466
    ├── grounding_pairs.jsonl.gz          2,240
    ├── structure_argument.jsonl.gz       7,168
    └── structure_discourse_mode.jsonl.gz 7,168
```

| File | What it holds |
|---|---|
| `debates.jsonl.gz` | Per-debate metadata: title, source, topic, question type, the full debate question (NYT) or full lead essay (BR), and the essay count under each condition. |
| `human_essays.jsonl.gz` | One row per human responder essay, with metadata only (author, bio, date, word count). The body text is not redistributed. See `scripts/refetch_human_essays.py` to recover it. |
| `llm_essays.jsonl.gz` | One row per LLM essay, with full text. Includes three conditions (`vanilla`, `diversified`, `position-guided`) across five LLMs. For `vanilla`, `is_representative` marks the one answer per model used in the paper. |
| `position_guides.jsonl.gz` | One row per human source used for `position-guided` generation. Names are kept for traceability but are not shown to the model. |
| `toulmin.jsonl.gz` | Extracted main argument and ordered sub-arguments, one row per essay, for humans and all three LLM conditions. |
| `main_argument_pairs.jsonl.gz` | Pairwise judgments over each pair's main arguments, using a four-label scheme (`equivalent`, `strong_overlap`, `weak_overlap`, `different`) with a short rationale. |
| `sub_argument_pairs.jsonl.gz` | Pairwise judgments over sub-arguments for selected analysis subsets. This is not a full-corpus all-pairs table; it contains the annotated NYT and BR subsets used for sub-argument checks where available. |
| `grounding_pairs.jsonl.gz` | A subset of main-argument pairs: each row compares one human essay with the position-guided essay based on that human. |
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

Human essay bodies are not redistributed because the original publishers retain copyright. `human_essays.jsonl.gz` includes metadata for finding them again. Use `scripts/refetch_human_essays.py` to rebuild a local copy from the publishers' sites.

## Prompts

`prompts/` contains the prompts used for generation and annotation. `prompts/prompts.jsonl` maps each `prompt_version` value in the data back to its prompt text. See `prompts/README.md` for details.

## License

- **Code** (this repository and `scripts/`): MIT. See `LICENSE`.
- **Derived data** (`llm_essays`, `position_guides`, `toulmin`, `*_pairs`, `structure_*`): CC-BY-4.0.
- **Original source content** (NYT debate prompts, BR lead essays): see `DATA_LICENSE.md` for per-source terms and the human-essay re-fetch procedure.

## Citation

```bibtex
@inproceedings{argument_collapse_2026,
  title = {Argument Collapse: LLMs Narrow the Argument Content and Structure in Public Debate},
  author = {{TBD}},
  booktitle = {Proceedings of the Annual Meeting of the Association for Computational Linguistics},
  year = {2026},
}
```
