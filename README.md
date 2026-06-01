# Argument Collapse

Code and data for the paper *Argument Collapse: LLMs Narrow the Argument Content and Structure in Public Debate*.

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
│   ├── structure.py                    # paragraph-level structure annotation
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
| `ac-structure`                | **Annotate** paragraph-level argumentative role and discourse mode.                      |
| `ac-metric`                   | **Compute** within-group unique rate U_m from a YAML spec.                             |

Each annotation row carries a `tagger_prompt_version` field so different prompt variants stay distinguishable in the released JSONL files:

| Stage                          | Base tag                  | Suffix (per cohort context kind) |
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

The public release uses aggregate gzipped JSONL tables partitioned by venue:

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
    └── ... same table names, with `sub_argument_pairs.jsonl.gz` empty when no BR sub-argument pair table is released
```

The loader also supports the older cohort-grouped working layout used by the annotation pipeline:

```
<data_root>/<venue>/<cohort>/
├── human/{00_question.md,00_lead.md,<author>.md}
├── generated/<stem>.md
└── analysis/{toulmin,main_argument_pairs,sub_argument_pairs}.jsonl
```

`data.detect_layout(path)` returns `"aggregate"` for the public release and `"cohort_grouped"` for the working layout. The public API (`iter_cohort_jsonl`, `cohort_analysis_path`, `find_human_responses`, ...) hides the difference where possible.

## Reproducing paper numbers

The reproduction wrapper for the headline sub-argument U_m numbers is included here. It expects the final LLM sub-argument pair rows in `data/nyt/sub_argument_pairs.jsonl.gz` and aborts with a clear error if the released table has not yet been populated with those rows:

```bash
./scripts/reproduce_subarg_diversity.sh
```

When the pair table is present, the script wraps `ac-metric um --spec configs/subarg_diversity_16cohort_nyt.yaml` and writes the detailed per-cohort breakdown to `results/subarg_diversity_16cohort_nyt.json`. Expected output (loose threshold, common-m, 16 NYT cohorts):

| Metric                                    | Strict | Loose |
|-------------------------------------------|--------|-------|
| Humans (cluster)                          | 94.9%  | 41.0% |
| Vanilla LLMs (medoid)                     | 60.6%  |  9.1% |
| Diversified (1-per-family)                | 81.4%  | 22.8% |
| Same position, different LLMs (S1)        | 56.4%  |  6.8% |
| Different positions, same LLM (S2)        | 72.7%  | 18.4% |

The diversified row is computed by sampling up to 200 one-per-family combinations per cohort with a fixed seed; the paper reports 22.9%, which is within sampling noise of the value above.

The dataset uses three LLM-condition codes:

| Code | Setup |
|---|---|
| `vanilla` | Default LLM answer with no instruction to diversify or follow a human source. |
| `diversified` | Single API call asking for a batch of N distinct responses. |
| `position-guided` | The LLM receives an anonymized descriptor for one human responder, plus that responder's extracted main argument, and writes from that position. |

### Re-running the annotation pipeline

To re-run the annotation pipeline end-to-end, provide a working-layout essay tree with local markdown bodies under `human/` and `generated/` (expensive: uses your own LLM API keys, on the order of $50 of spend, several hours). The public aggregate release does not redistribute human essay bodies. Use `./scripts/run_annotation_pipeline.sh` or invoke each stage directly:

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

# Step 4 — STRUCTURE ANNOTATION: paragraph-level argument role + discourse mode
ac-structure --venue NYT-Room-for-Debate-filtered \
             --kinds human,vanilla,diversified,position-guided \
             --layer both

# Step 5 — STANCE LABELLING (binary cohorts only, two stages)
ac-stance stage1 --venue NYT-Room-for-Debate-filtered \
                 --cohort are-americans-too-obsessed-with-cleanliness \
                 --output results/stance_sides.json
ac-stance stage2 --venue NYT-Room-for-Debate-filtered \
                 --sides  results/stance_sides.json \
                 --output results/stance_labels.json

# Step 6 — METRIC: sub-argument diversity U_m
ac-metric um \
    --spec   configs/subarg_diversity_16cohort_nyt.yaml \
    --output results/subarg_diversity_16cohort_nyt.json
```

---


## Temporary note: sub-argument pair export needed

The current local release rebuild includes the aggregate `sub_argument_pairs.jsonl.gz` table, but the locally available source files do not yet contain the final LLM--LLM sub-argument pair rows needed to reproduce the paper's sub-argument U_m table.

For the 16-cohort NYT sub-argument analysis, we need complete `analysis/sub_argument_pairs.jsonl` files that include within-group generated-generated pairs for the final conditions:

- `v1a` ↔ `v1a` for the vanilla/default LLM group.
- `v15a` ↔ `v15a` for the diversified group.
- `v4a` ↔ `v4a` for the position-guided group.

The U_m table does not require human--LLM sub-argument pairs, because it measures within-group uniqueness/reuse. It does require the human--human rows for the same 16 cohorts, plus the generated-generated rows above. The older local sub-argument pair files mostly contain `v3a`/`v25a` rows, which are not the final public conditions and should not be silently mapped to the release conditions.

## Data release

The `data/` directory packages the public-facing version of the corpus as gzipped JSONL tables. Each row is self-contained and joins on `(venue, debate_id)` plus `(venue, debate_id, essay_id)`. Data is partitioned by venue (`data/nyt/` and `data/br/`); rows still carry `venue`, so files can be concatenated cross-venue without ambiguity.

```
data/
├── nyt/           # 195 NYT Room for Debate debates
│   ├── debates.jsonl.gz                    195 rows
│   ├── human_essays.jsonl.gz             1,039
│   ├── llm_essays.jsonl.gz              16,661
│   ├── position_guides.jsonl.gz          1,039
│   ├── toulmin.jsonl.gz                 17,703
│   ├── main_argument_pairs.jsonl.gz    231,284
│   ├── sub_argument_pairs.jsonl.gz      11,840
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
    ├── sub_argument_pairs.jsonl.gz           0
    ├── grounding_pairs.jsonl.gz          2,240
    ├── structure_argument.jsonl.gz       7,168
    └── structure_discourse_mode.jsonl.gz 7,168
```

| File | What it holds |
|---|---|
| `debates.jsonl.gz` | Per-debate metadata: title, source, topic, question type, the full debate question (NYT) or full lead essay (BR), and the essay count under each condition. |
| `human_essays.jsonl.gz` | One row per human responder essay, with metadata only (author, bio, date, word count). The body text is not redistributed. See `scripts/refetch_human_essays.py` to recover it. |
| `llm_essays.jsonl.gz` | One row per LLM-generated essay, full text included. Three conditions (`vanilla`, `diversified`, `position-guided`) across five frontier LLMs (GPT-5.5, Gemini 3.1 Pro, Claude Opus 4.7, MiniMax M2.7, DeepSeek v4 Pro). Vanilla rows carry an `is_representative` boolean that flags the model-level medoid for each debate. |
| `position_guides.jsonl.gz` | One row per human source used for `position-guided` generation. Each row records the human source id, a name for traceability, an anonymized role description, and a tone description. Names are not shown to the generation model. |
| `toulmin.jsonl.gz` | Extracted main argument and ordered sub-arguments, one row per essay, for humans and all three LLM conditions. |
| `main_argument_pairs.jsonl.gz` | Pairwise judgments over each pair's main arguments, using a four-label scheme (`equivalent`, `strong_overlap`, `weak_overlap`, `different`) with a short rationale. |
| `sub_argument_pairs.jsonl.gz` | Pairwise judgments over sub-arguments. The current NYT export contains the available human-human subset; the final LLM-pair export must be populated before reproducing the paper sub-argument U_m table. The BR file is included for schema symmetry but currently has zero rows. |
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

`prompts/` ships every system and user prompt used in the pipeline, alongside rendered examples (`prompts/examples/`) and a programmatic index (`prompts/prompts.jsonl`) that maps each `prompt_version` tag to its full text. The index includes the annotation prompts (toulmin, main-argument judge, structure argument, structure discourse-mode), the dynamic generation prompts (with a Python helper that reproduces the exact text sent), and the preprocessing taggers (topic, question-type, sensitivity, position-guidance descriptor, temporal-change filter). See `prompts/README.md` for the map.

## License

- **Code** (this repository and `scripts/`): MIT. See `LICENSE`.
- **Derived data** (`llm_essays`, `position_guides`, `toulmin`, `*_pairs`, `structure_*`): CC-BY-4.0.
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
